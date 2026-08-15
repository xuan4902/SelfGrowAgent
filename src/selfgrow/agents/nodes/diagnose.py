"""🔮 占卜师・诊断官：目标拆解 → 逐题情景测评（AI 自适应）→ 能力雷达 + 薄弱点定位。

两节点拆分（LangGraph 关键约束：interrupt 恢复会整体重跑节点、中断那轮不落盘）：
- diagnose_node（决策，不中断）：读累计作答 → 自适应追问 → 生成下一题或收尾出雷达。
- diagnose_wait_node（唯一中断）：读**已落盘**的 pending_question（不重新生成），
  逐题 interrupt 收集作答（恢复值 = {"question_id", "option"}）。

中断点：每道题的作答收集。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState, build_hud
from selfgrow.agents.tools import call_tool, generate_question, save_record
from selfgrow.agents.bank import has_unused_question
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

_MAX_PROBES = {"baseline": 4, "reassess": 2}  # 每阶段最多插入的追问数（自适应预算）


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


def _build_plan(
    breakdown: dict[str, Any], state: AgentState, framework: Any, reassess: bool
) -> list[dict[str, Any]]:
    """构造出题计划：基线=关键词命中维度在前 + 框架序补全；复测=薄弱维度聚焦高难度。"""
    if reassess:
        return [
            {"dimension": d, "min_difficulty": 2, "kind": "core"}
            for d in (state.get("gaps") or [])[:3]
        ]
    matched = breakdown.get("sub_goal_ids") or []
    rest = [d.id for d in framework.dimensions if d.id not in matched]
    return [
        {"dimension": d, "min_difficulty": 1, "kind": "core"}
        for d in list(matched) + rest
    ]


def _make_narration(
    breakdown: dict[str, Any], q: dict[str, Any], index: int, stage_label: str
) -> str:
    """当前题配套旁白（确定性，不额外占用 LLM 配额）。"""
    if index == 0:
        if stage_label == "复测":
            return "复测开始——让本座看看这两周你的修炼成果。\n第一题，先来试试水。"
        head = (breakdown.get("narration") or "").strip()
        return (head + "\n第一题，先来掂量掂量你的底子。") if head else "第一题，先来掂量掂量你的底子。"
    if q.get("kind") == "probe":
        return "这一题是本座特意加的难度考校：上一题你答得不太稳，换个更刁钻的再试试。"
    return "有意思，本座继续出题。"


def _finalize(
    state: AgentState, rt: Runtime, role: Any, called: list[dict[str, Any]],
    answers: list[dict[str, Any]], reassess: bool, framework: Any,
) -> dict[str, Any]:
    """测评收尾：计算雷达 + 复测合并保留已有维度 + 落库 + 定位薄弱点。"""
    scored = [{k: a[k] for k in ("question_id", "dimension", "option", "correct")} for a in answers]
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
        "assessment_done": True,
        "assessment_plan": [],
        "pending_question": None,
        "pending_narration": None,
        "radar": result.radar,
        "gaps": result.gaps,
        "radar_before": radar_before,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
        "llm_mode": rt.llm.mode,
    }


def diagnose_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    """决策节点（不中断）：逐题推进，plan 空且有作答时收尾。"""
    called: list[dict[str, Any]] = []
    framework = rt.framework
    role = get_role("diagnose")
    reassess = state.get("stage") == "reassess"
    stage_label = "复测" if reassess else "基线测评"

    # 1) 目标拆解（仅首次生成，避免恢复时 LLM 漂移 / 重复留痕）
    breakdown = state.get("goal_breakdown")
    if breakdown is None:
        breakdown = _breakdown_goal(framework, state.get("goal", ""))
        breakdown["narration"] = rt.llm.complete(
            role.system_prompt,
            with_ctx(breakdown, with_task("goal_breakdown", "测评前拆解我的目标")),
        )

    answers = list(state.get("assessment_answers", []))
    probes = list(state.get("assessment_probes", []))
    plan = list(state.get("assessment_plan", []))
    asked = list(state.get("assessment_questions", []))

    # 2) 自适应追问：上一题答错 → 同维度插一道更难的题（预算内且题库有余）
    if answers and not answers[-1]["correct"]:
        last = answers[-1]
        last_diff = 1
        for qq in asked:
            if qq.get("id") == last["question_id"]:
                last_diff = qq.get("difficulty", 1)
                break
        used_ids = [qq.get("id") for qq in asked]
        budget = _MAX_PROBES["reassess"] if reassess else _MAX_PROBES["baseline"]
        if (
            last["dimension"] not in probes
            and len(probes) < budget
            and has_unused_question(rt.domain, last["dimension"], last_diff + 1, used_ids)
        ):
            plan.insert(
                0,
                {
                    "dimension": last["dimension"],
                    "min_difficulty": last_diff + 1,
                    "kind": "probe",
                },
            )
            probes.append(last["dimension"])

    # 3) 计划清空且有作答 → 收尾
    if not plan and answers:
        return _finalize(state, rt, role, called, answers, reassess, framework)

    # 4) 首次进入：建计划
    if not plan:
        plan = _build_plan(breakdown, state, framework, reassess)
        if not plan:
            return _finalize(state, rt, role, called, answers, reassess, framework)

    # 5) 出下一题（AI 生成，Mock 走题库确定性拼装，解析失败回退 bank）
    item = plan.pop(0)
    used_ids = [qq.get("id") for qq in asked]
    q = call_tool(
        called, "generate_question", generate_question,
        llm=rt.llm, role_prompt=role.system_prompt,
        dimension=item["dimension"], min_difficulty=item["min_difficulty"],
        used_ids=used_ids, domain=rt.domain,
        stage="reassess" if reassess else "baseline",
        goal=state.get("goal", ""),
        prior_answers=answers[-6:],
    )
    q["kind"] = item["kind"]
    index = len(answers)
    narration = _make_narration(breakdown, q, index, stage_label)

    return {
        "goal_breakdown": breakdown,
        "pending_question": q,
        "pending_narration": narration,
        "assessment_plan": plan,
        "assessment_probes": probes,
        "assessment_done": False,
        "tools_called": state.get("tools_called", []) + called,
        "llm_mode": rt.llm.mode,
    }


def diagnose_wait_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    """唯一中断点：展示**已落盘**的单题并收集作答（零 LLM / 零工具，防重复生成）。"""
    role = get_role("diagnose")
    reassess = state.get("stage") == "reassess"
    stage_label = "复测" if reassess else "基线测评"

    q = state.get("pending_question")
    if q is None:
        # 防御：理论上不会走到（diagnose_node 总是先落 pending_question）
        return {"assessment_done": True, "llm_mode": rt.llm.mode}

    index = len(state.get("assessment_answers", []))
    total = index + 1 + len(state.get("assessment_plan", []))
    hud = build_hud(state, "diagnose", index=index, total=total, stage_label=stage_label)
    scene = {
        "title": f"{stage_label} · 第 {index + 1} 题",
        "location": "占卜师的水晶占卜屋",
        "mood": "神秘" if not reassess else "肃穆",
    }

    resume = interrupt(
        {
            "assessment": {
                "stage_label": stage_label,
                "question": q,
                "index": index,
                "total": total,
                "narration": state.get("pending_narration") or "",
                "scene": scene,
                "role": role.id,
                "banner": role.banner(),
                "hud": hud,
            }
        }
    )

    # 归一化作答（question_id 必须对得上当前题，option 必须落在选项范围）
    if not isinstance(resume, dict):
        resume = {}
    qid = resume.get("question_id", q.get("id"))
    opt = resume.get("option", 0)
    if isinstance(opt, bool):  # bool 是 int 子类，需排除
        opt = 0
    try:
        opt = int(opt)
    except (TypeError, ValueError):
        opt = 0
    opt = max(0, min(opt, len(q.get("options", [])) - 1))
    correct = (qid == q.get("id")) and (opt == q.get("correct"))

    answers = list(state.get("assessment_answers", [])) + [
        {
            "question_id": qid,
            "dimension": q.get("dimension"),
            "option": opt,
            "correct": correct,
            "difficulty": q.get("difficulty", 1),
        }
    ]
    asked = list(state.get("assessment_questions", [])) + [q]

    return {
        "assessment_answers": answers,
        "assessment_questions": asked,
        "pending_question": None,
        "pending_narration": None,
        "assessment_done": False,
        "tools_called": list(state.get("tools_called", [])),
        "llm_mode": rt.llm.mode,
    }
