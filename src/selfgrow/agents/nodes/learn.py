"""📖 讲师・知识官：RAG 检索 → 苏格拉底式讲解 → 询问下一步（继续问/去演练/复盘）。

评审点：知识增强（RAG）+ 多轮交互 + 教学友好（不给答案给引导）。
中断点：收集用户选择（继续问 / 去演练 / 复盘）。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState, build_hud
from selfgrow.agents.tools import call_tool, save_record, search_knowledge
from selfgrow.llm.base import with_ctx, with_task


def learn_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    role = get_role("learn")
    plan = state["plan"]
    week = state.get("current_week", 0) + 1
    week_info = plan["weeks"][week - 1]
    dim_id = week_info["dimension"]
    dim = rt.framework.get_dimension(dim_id)
    dim_name = dim.name if dim else dim_id
    turns = state.get("learn_turns", 0)

    # 1) RAG 检索（工具调用）
    hits = call_tool(
        called, "search_knowledge", search_knowledge,
        kb=rt.kb, query=week_info["knowledge_query"], top_k=2,
    )
    hits_dicts = [h.to_dict() for h in hits]

    # 2) 讲师讲解（注入画像 = 记住你）
    ctx = {
        "dimension_name": dim_name,
        "week": week,
        "knowledge_hits": [f"{h.title}｜{h.section}" for h in hits],
        "goal": state.get("goal", ""),
        "turn": turns,
    }
    lesson = rt.llm.complete(
        role.system_prompt,
        with_ctx(ctx, with_task("lesson", f"第 {week} 关：{dim_name} 教学")),
    )

    # 3) 中断：收集用户下一步
    hud = build_hud(state, "learn", week=week, stage_label=f"拜师学艺 · W{week}")
    action = interrupt(
        {
            "learn": {
                "week": week,
                "dimension_name": dim_name,
                "lesson": lesson,
                "milestone": week_info.get("milestone", ""),
                "challenge": week_info.get("challenge", ""),
                "options": ["继续问", "去演练", "复盘"],
                "banner": role.banner(),
                "hud": hud,
            }
        }
    )
    action = str(action or "去演练")

    # 4) 首次讲解时落库（工具调用）
    if turns == 0:
        call_tool(
            called, "save_record", save_record,
            db=rt.db, table="learning_records",
            data={
                "learner_id": state["learner_id"],
                "week": week,
                "dimension": dim_id,
                "lesson": lesson,
                "knowledge_hits": hits_dicts,
            },
        )

    message = (
        f"{role.banner()} 第 {week} 关「{dim_name}」讲解完成。\n{lesson}"
    )
    return {
        "knowledge_hits": hits_dicts,
        "lesson": lesson,
        "learn_turns": turns + 1 if action == "继续问" else 0,
        "user_action": action,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
    }
