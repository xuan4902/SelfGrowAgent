"""🔮 占卜师・诊断官：目标拆解 → 情景测评 → 能力雷达 + 薄弱点定位。

中断点：收集测评作答。恢复值 = {"answers": [{"question_id", "option"}, ...]}。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState
from selfgrow.agents.tools import (
    call_tool,
    generate_assessment,
    save_record,
)
from selfgrow.competency.radar import compute_radar, summarize
from selfgrow.llm.base import with_ctx, with_task

# 目标诉求 → 优先拆解维度（规则式，真模型模式下 LLM 负责细化叙述）
_GOAL_KEYWORDS: dict[str, list[str]] = {
    "goal_alignment": ["目标", "对齐", "方向", "优先级", "okr", "规划"],
    "report_structure": ["汇报", "表达", "总结", "周报", "报告", "说话", "发言"],
    "expectation_management": ["期待", "预期", "标准", "交付", "需求"],
    "resource_acquisition": ["资源", "预算", "加人", "支持", "争取"],
    "upward_communication": ["沟通", "向上", "同步", "领导", "老板", "汇报"],
    "handling_feedback": ["反馈", "批评", "复盘", "改进"],
}


def _breakdown_goal(framework: Any, goal: str) -> dict[str, Any]:
    """把模糊诉求拆成能力维度（规则 + 兜底）。"""
    lower = goal.lower()
    matched: list[str] = []
    for dim_id, kws in _GOAL_KEYWORDS.items():
        if any(k in goal or k in lower for k in kws):
            matched.append(dim_id)
    if not matched:
        matched = [framework.dimensions[0].id, framework.dimensions[1].id, framework.dimensions[2].id]
    # 去重保序
    seen: list[str] = []
    for m in matched:
        if m not in seen:
            seen.append(m)
    sub_goals = seen[:3]
    names = [framework.get_dimension(d).name for d in sub_goals]
    return {
        "domain": framework.domain,
        "domain_name": framework.name,
        "sub_goals": names,
        "sub_goal_ids": sub_goals,
    }


def _normalize_answers(
    questions: list[dict[str, Any]], payload: Any
) -> list[dict[str, Any]]:
    """把用户作答映射为评分输入 [{question_id, dimension, option, correct}]。"""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("answers") or []
    qmap = {q["id"]: q for q in questions}
    out: list[dict[str, Any]] = []
    for a in raw:
        qid = a.get("question_id")
        q = qmap.get(qid)
        if q is None:
            continue
        opt = int(a.get("option", 0))
        out.append(
            {
                "question_id": qid,
                "dimension": q["dimension"],
                "option": opt,
                "correct": opt == q["correct"],
            }
        )
    return out


def diagnose_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    framework = rt.framework
    reassess = state.get("stage") == "reassess"

    # 1) 目标拆解（任务理解）
    breakdown = _breakdown_goal(framework, state.get("goal", ""))
    role = get_role("diagnose")

    # 2) 出题（工具调用）
    if reassess:
        weak = state.get("gaps", [])[:3]
        questions = call_tool(
            called, "generate_assessment", generate_assessment,
            focus_dims=weak, per_dim=2, min_difficulty=2,
        )
        stage_label = "复测"
    else:
        questions = call_tool(
            called, "generate_assessment", generate_assessment, per_dim=2
        )
        stage_label = "基线测评"

    narration = rt.llm.complete(
        role.system_prompt,
        with_ctx(breakdown, with_task("goal_breakdown", f"{stage_label}，请拆解我的目标")),
    )

    # 3) 中断：收集作答（恢复值 = {"answers": [...]}）
    answers_payload = interrupt(
        {
            "assessment": {
                "stage_label": stage_label,
                "questions": questions,
                "role": role.id,
                "banner": role.banner(),
                "narration": narration,
            }
        }
    )

    # 4) 计算雷达与薄弱点
    scored = _normalize_answers(questions, answers_payload)
    result = compute_radar(framework, scored)

    # 复测只更新被测评的维度，保留其余维度已有水平（避免雷达被清零）
    if reassess and state.get("radar"):
        merged = dict(state["radar"])
        for dim_id in result.radar:
            if result.answered.get(dim_id, 0) > 0:
                merged[dim_id] = result.radar[dim_id]
        result.radar = merged
        result.gaps = sorted(
            (d.id for d in framework.dimensions),
            key=lambda dim_id: (merged.get(dim_id, 5), framework.dimension_ids().index(dim_id)),
        )
        result.summary = summarize(framework, result.gaps, hint="复测已更新，难度可动态调整")

    # 5) 落库（工具调用）
    call_tool(
        called, "save_record", save_record,
        db=rt.db, table="assessments",
        data={
            "learner_id": state["learner_id"],
            "kind": "reassess" if reassess else "baseline",
            "radar": result.radar,
            "gaps": result.gaps,
        },
    )

    radar_before = state.get("radar_before")
    if not reassess and radar_before is None:
        radar_before = dict(result.radar)

    dims = {d.id: d.name for d in framework.dimensions}
    weakest = dims.get(result.gaps[0], result.gaps[0]) if result.gaps else ""
    message = (
        f"{role.banner()} 测评完成！雷达已生成。\n"
        f"你当前最需要修炼的是「{weakest}」。\n{result.summary}"
    )

    return {
        "goal_breakdown": breakdown,
        "assessment_questions": questions,
        "radar": result.radar,
        "gaps": result.gaps,
        "radar_before": radar_before,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [
            {"role": role.id, "content": message},
        ],
        "llm_mode": rt.llm.mode,
    }
