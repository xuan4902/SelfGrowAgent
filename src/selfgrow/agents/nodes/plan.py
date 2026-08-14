"""🗺️ 制图师・规划师：生成闯关路线；复测后动态调整剩余关卡。

评审点：计划生成 + 动态调整（官方能力点 2）。
"""

from __future__ import annotations

from typing import Any

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState
from selfgrow.agents.tools import call_tool, build_mindmap, save_record
from selfgrow.agents.planning import adjust_plan, build_mindmap_text, generate_plan
from selfgrow.llm.base import with_ctx, with_task
from selfgrow.paths import PROJECT_ROOT

_TOTAL_WEEKS = 2  # 演示用；真实场景可配到 8 周


def plan_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    framework = rt.framework
    role = get_role("plan")
    reassess = state.get("stage") == "reassess"
    learner_id = state["learner_id"]

    if reassess:
        # ---- 动态调整分支 ----
        # plan 里的 current_week 需同步 state 真实进度（generate_plan 初始为 0）
        plan_state = dict(state["plan"])
        plan_state["current_week"] = state.get("current_week", 0)
        plan, adj = adjust_plan(framework, plan_state, state["radar"])
        call_tool(
            called, "save_record", save_record,
            db=rt.db, table="plans",
            data={"learner_id": learner_id, "plan": plan},
        )
        message = f"{role.banner()} {adj}"
        return {
            "plan": plan,
            "adjustment": adj,
            "reassess_done": True,
            "tools_called": state.get("tools_called", []) + called,
            "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
        }

    # ---- 首次生成 ----
    plan = generate_plan(framework, state["radar"], state.get("gaps"), total_weeks=_TOTAL_WEEKS)
    first_dim = framework.get_dimension(plan["weeks"][0]["dimension"])
    narration = rt.llm.complete(
        role.system_prompt,
        with_ctx(
            {"weeks": _TOTAL_WEEKS, "first_dimension_name": first_dim.name if first_dim else ""},
            with_task("plan_narrate", "请绘制我的闯关路线"),
        ),
    )

    # 工具调用：落库 + 思维导图
    call_tool(
        called, "save_record", save_record,
        db=rt.db, table="plans",
        data={"learner_id": learner_id, "plan": plan},
    )
    mindmap_path = PROJECT_ROOT / "data" / "artifacts" / f"mindmap_{learner_id}.mmd"
    call_tool(called, "build_mindmap", build_mindmap, plan=plan, out_path=mindmap_path)

    message = f"{role.banner()} {narration}"
    return {
        "plan": plan,
        "adjustment": "",
        "reassess_done": False,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
        "mindmap_text": build_mindmap_text(plan),
    }
