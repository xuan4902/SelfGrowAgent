"""📜 史官・复盘官（毕业）：复测后输出通关战报 + 沉淀技能库。

评审点：结果验证（量化成长）+ 上下文记忆（前后雷达对比）。
"""

from __future__ import annotations

from typing import Any

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState
from selfgrow.agents.tools import call_tool, save_record
from selfgrow.llm.base import with_ctx, with_task


def _compute_level(xp: int) -> int:
    # 50 XP/级：2 周通关 ≈ Lv.3，成长反馈更直观
    return 1 + xp // 50


def graduate_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    role = get_role("review")
    framework = rt.framework
    learner_id = state["learner_id"]

    before = state.get("radar_before") or {}
    after = state.get("radar", {})
    improved = [
        framework.get_dimension(d).name
        for d in framework.dimension_ids()
        if after.get(d, 1) > before.get(d, 1)
    ]
    remaining_gaps = [
        framework.get_dimension(d).name
        for d in framework.dimension_ids()
        if after.get(d, 1) <= 1
    ]
    xp = state.get("xp", 0)
    level = _compute_level(xp)

    report = {
        "goal": state.get("goal", ""),
        "xp": xp,
        "level": level,
        "improved": improved,
        "remaining_gaps": remaining_gaps,
        "radar_before": before,
        "radar_after": after,
        "tools_used": sorted({t["name"] for t in state.get("tools_called", [])}),
    }

    # 落库学习者成长档案（工具调用）
    call_tool(
        called, "save_record", save_record,
        db=rt.db, table="learners",
        data={"learner_id": learner_id, "goal": state.get("goal", ""), "xp": xp, "level": level},
    )

    narrative = rt.llm.complete(
        role.system_prompt,
        with_ctx(
            {"xp_gained": xp, "level": level, "improved": improved},
            with_task("report", "生成通关战报"),
        ),
    )
    report["summary"] = narrative

    message = f"{role.banner()} 战报已归档！\n{narrative}\n📈 成长维度：{'、'.join(improved) if improved else '（复测与基线持平，建议换一个领域再练）'}"
    return {
        "report": report,
        "xp": xp,
        "level": level,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
    }
