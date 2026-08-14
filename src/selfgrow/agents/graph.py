"""LangGraph 编排：五节点 + 条件边 + InMemorySaver 断点续学。

拓扑：
START → diagnose → plan ─(stage==reassess)→ graduate → END
                      └─(else)→ learn ─(继续问)→ learn
                                      ├─(去演练)→ spar ─(未完)→ spar
                                      │             └─(打完)→ review
                                      └─(复盘)→ review ─(week<total)→ learn
                                                       ├─(week==total,未复测)→ diagnose(reassess)
                                                       └─(复测完成)→ graduate
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from selfgrow.agents.nodes import (
    diagnose_node,
    graduate_node,
    learn_node,
    plan_node,
    review_node,
    spar_node,
)
from selfgrow.agents.runtime import Runtime, default_runtime
from selfgrow.agents.state import AgentState


def router_after_plan(state: dict[str, Any]) -> str:
    # 复测后若计划已无剩余周 → 毕业；否则继续剩余关卡
    if state.get("stage") == "reassess":
        cur = state.get("current_week", 0)
        total = state.get("plan", {}).get("total_weeks", 1)
        return "graduate" if cur >= total else "learn"
    return "learn"


def router_after_learn(state: dict[str, Any]) -> str:
    action = state.get("user_action", "去演练")
    if action == "复盘":
        return "review"
    if action == "继续问":
        return "learn"
    return "spar"


def router_after_spar(state: dict[str, Any]) -> str:
    return "review" if state.get("battle_over") else "spar"


def router_after_review(state: dict[str, Any]) -> str:
    cur = state.get("current_week", 0)
    total = state.get("plan", {}).get("total_weeks", 1)
    # 到达中途检查点且尚未复测 → 复测诊断（动态调整）
    if not state.get("reassess_done") and cur >= max(1, total // 2):
        return "diagnose"
    if cur < total:
        return "learn"
    return "graduate"  # 复测完成且周数已满 → 毕业


def build_graph(runtime: Runtime | None = None) -> Any:
    """装配 StateGraph 并编译（InMemorySaver checkpointer，thread_id=learner_id）。"""
    rt = runtime or default_runtime()

    def bind(fn: Callable) -> Callable:
        # 节点签名：fn(state, rt)
        return lambda state: fn(state, rt)

    g = StateGraph(AgentState)
    g.add_node("diagnose", bind(diagnose_node))
    g.add_node("plan", bind(plan_node))
    g.add_node("learn", bind(learn_node))
    g.add_node("spar", bind(spar_node))
    g.add_node("review", bind(review_node))
    g.add_node("graduate", bind(graduate_node))

    g.add_edge(START, "diagnose")
    g.add_edge("diagnose", "plan")
    g.add_conditional_edges(
        "plan", router_after_plan, {"learn": "learn", "graduate": "graduate"}
    )
    g.add_conditional_edges(
        "learn", router_after_learn, {"learn": "learn", "spar": "spar", "review": "review"}
    )
    g.add_conditional_edges(
        "spar", router_after_spar, {"spar": "spar", "review": "review"}
    )
    g.add_conditional_edges(
        "review",
        router_after_review,
        {"learn": "learn", "diagnose": "diagnose", "graduate": "graduate"},
    )
    g.add_edge("graduate", END)

    return g.compile(checkpointer=InMemorySaver())
