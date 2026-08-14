"""⚔️ 陪练武士・陪练官：沉浸式副本对线（多轮）→ 打完按 rubric 反馈。

评审点：多轮交互 + 情景模拟 + 结果验证（错因分析/同类推荐）。
中断点：每回合收集用户回应（恢复值 = 字符串）。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from selfgrow.agents.roles import get_role
from selfgrow.agents.runtime import Runtime
from selfgrow.agents.state import AgentState
from selfgrow.agents.tools import call_tool, get_scenario, save_record
from selfgrow.competency.rubric import evaluate_response
from selfgrow.llm.base import with_ctx, with_task

_MAX_TURNS = 2  # 每副本 2 个来回（演示；真环境可调大）


def _npc_line(scenario: dict[str, Any], user_turns: int, rt: Runtime) -> str:
    """按回合取 NPC 台词：Mock 用脚本轮转；真模型由 LLM 生成。"""
    npc = scenario.get("npc", {})
    if user_turns == 0:
        return npc.get("opening", "（NPC 开场）")
    mock_lines = npc.get("mock_lines", [])
    if rt.llm.mode == "claude":
        return rt.llm.complete(
            get_role("spar").system_prompt,
            with_ctx(
                {
                    "mock_lines": mock_lines,
                    "turn": user_turns,
                    "persona": npc.get("persona", ""),
                    "scenario": scenario.get("title", ""),
                },
                with_task("spar_npc", "请扮演 NPC 回应学习者"),
            ),
        )
    idx = (user_turns - 1) % max(1, len(mock_lines))
    return mock_lines[idx]


def _user_text(transcript: list[dict[str, str]]) -> str:
    return "\n".join(m["content"] for m in transcript if m.get("role") == "user")


def spar_node(state: AgentState, rt: Runtime) -> dict[str, Any]:
    called: list[dict[str, Any]] = []
    role = get_role("spar")
    framework = rt.framework

    # 当前周维度
    week = state.get("current_week", 0) + 1
    dim_id = state["plan"]["weeks"][week - 1]["dimension"]

    # 取场景（工具调用；若已有则复用）
    if state.get("scenario"):
        scenario = state["scenario"]
    else:
        scenario = call_tool(
            called, "get_scenario", get_scenario, domain=rt.domain, dimension=dim_id
        )

    transcript = list(state.get("spar_transcript", []))
    user_turns = sum(1 for m in transcript if m.get("role") == "user")

    # 中断：等待用户出手（恢复值 = 用户回应文本）
    npc_line = _npc_line(scenario, user_turns, rt)
    move = interrupt(
        {
            "spar": {
                "scenario_title": scenario.get("title", ""),
                "scenario_goal": scenario.get("goal", ""),
                "npc_line": npc_line,
                "user_turns": user_turns,
                "max_turns": _MAX_TURNS,
                "banner": role.banner(),
            }
        }
    )
    move = str(move or "").strip() or "（未回应）"

    new_entries = [
        {"role": "npc", "content": npc_line},
        {"role": "user", "content": move},
    ]
    updated = transcript + new_entries

    if user_turns + 1 >= _MAX_TURNS:
        # 打完：rubric 打分 + 错因分析 + 同类推荐
        text = _user_text(updated)
        evaluated = evaluate_response(framework, dim_id, text)
        ctx = {
            "overall_level": evaluated.overall_level,
            "mistakes": evaluated.mistakes,
            "suggestions": evaluated.suggestions,
            "dimension_name": framework.get_dimension(dim_id).name,
        }
        narrative = rt.llm.complete(
            role.system_prompt,
            with_ctx(ctx, with_task("spar_feedback", "对战结束，给出反馈")),
        )
        feedback = {
            **evaluated.to_dict(),
            "narrative": narrative,
            "next_scenario": "同维度更高难度副本 / 换一个维度再战",
        }
        call_tool(
            called, "save_record", save_record,
            db=rt.db, table="spar_sessions",
            data={
                "learner_id": state["learner_id"],
                "week": week,
                "scenario_id": scenario.get("id", ""),
                "transcript": updated,
                "feedback": feedback,
            },
        )
        message = f"{role.banner()} 对战结束！\n{narrative}"
        return {
            "scenario": scenario,
            "spar_transcript": updated,
            "spar_feedback": feedback,
            "battle_over": True,
            "tools_called": state.get("tools_called", []) + called,
            "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
        }

    message = f"{role.banner()} 进入副本《{scenario.get('title', '')}》：\n{npc_line}"
    return {
        "scenario": scenario,
        "spar_transcript": updated,
        "battle_over": False,
        "tools_called": state.get("tools_called", []) + called,
        "messages": state.get("messages", []) + [{"role": role.id, "content": message}],
    }
