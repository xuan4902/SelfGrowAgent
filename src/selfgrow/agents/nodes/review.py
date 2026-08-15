"""📜 史官・复盘官：Kolb 经验学习循环引导 → 落库 → 推进周进度。

评审点：结果验证 + 上下文记忆（记录学习记录，支撑战报与续学）。
中断点：收集用户的复盘反思（恢复值 = 字符串）。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState, build_hud
from selfgrow.agents.tools import call_tool, save_record
from selfgrow.llm.base import with_ctx, with_task

_WEEK_XP = 50


def review_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    role = get_role("review")
    plan = state["plan"]
    week = state.get("current_week", 0) + 1
    week_info = plan["weeks"][week - 1]
    dim = rt.framework.get_dimension(week_info["dimension"])
    dim_name = dim.name if dim else week_info["dimension"]

    # 1) Kolb 复盘引导（LLM）
    guide = rt.llm.complete(
        role.system_prompt,
        with_ctx({"dimension_name": dim_name}, with_task("review", "复盘引导")),
    )

    # 2) 中断：收集复盘反思（恢复值 = 用户复盘文本）
    hud = build_hud(state, "review", week=week, stage_label=f"史官复盘 · W{week}")
    reflection = interrupt(
        {
            "review": {
                "week": week,
                "dimension_name": dim_name,
                "guide": guide,
                "banner": role.banner(),
                "hud": hud,
            }
        }
    )
    reflection = str(reflection or "").strip() or "（未填写）"

    # 3) 落库（工具调用）+ 推进进度
    kolb = {"week": week, "dimension": week_info["dimension"], "reflection": reflection}
    call_tool(
        called, "save_record", save_record,
        db=rt.db, table="reviews",
        data={"learner_id": state["learner_id"], "week": week, "kolb": kolb},
    )

    new_week = state.get("current_week", 0) + 1
    total = plan["total_weeks"]
    xp = state.get("xp", 0) + _WEEK_XP
    # 中途(≥一半进度)未复测 → 进入复测做动态调整；否则继续每周推进
    checkpoint = max(1, total // 2)
    need_reassess = new_week >= checkpoint and not state.get("reassess_done")
    stage = "reassess" if need_reassess else "weekly"

    # 进入复测前清空逐题测评的累计状态（基线作答不得污染复测雷达）
    assessment_reset: dict[str, Any] = {}
    if need_reassess:
        assessment_reset = {
            "assessment_answers": [],
            "assessment_questions": [],
            "assessment_plan": [],
            "assessment_probes": [],
            "assessment_done": False,
            "pending_question": None,
            "pending_narration": None,
        }

    message = (
        f"{role.banner()} 第 {week} 关复盘已归档，成长 +{_WEEK_XP} XP。\n{guide}"
    )
    return {
        "review": kolb,
        "current_week": new_week,
        "xp": xp,
        "stage": stage,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
        **assessment_reset,
    }
