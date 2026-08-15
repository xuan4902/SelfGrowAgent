"""LangGraph 的 AgentState 定义。

设计要点：所有列表字段用「replace 语义 + 节点显式合并」而非 reducer——
因为 interrupt 恢复时节点会整体重跑，reducer 会导致重复追加。
每个节点返回全量（已有 + 本次新增），配合 checkpointer 实现跨轮/跨节点会话记忆。
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # ---- 会话 ----
    learner_id: str
    goal: str                              # 原始模糊诉求
    messages: list[dict[str, str]]         # 对话历史（多轮/续学）

    # ---- 诊断 ----
    goal_breakdown: dict[str, Any]         # 拆解：sub_goals / domain_name
    assessment_questions: list[dict[str, Any]]   # 已出题目
    assessment_answers: list[dict[str, Any]]     # 已评分作答 [{question_id, dimension, option, correct, difficulty}]
    assessment_plan: list[dict[str, Any]]        # 待出题计划 [{dimension, min_difficulty, kind}]
    assessment_done: bool                        # 本轮测评完成（router 判据）
    assessment_probes: list[str]                 # 已插追问的维度（自适应预算控制）
    pending_question: dict[str, Any] | None      # 待中断展示的当前题（落盘供 diagnose_wait 读取）
    pending_narration: str | None                # 当前题配套旁白
    radar: dict[str, int]                  # 当前能力雷达 {dim: 1-5}
    radar_before: dict[str, int] | None    # 基线雷达（成长对比）
    gaps: list[str]                        # 薄弱维度（升序）
    stage: str                             # "baseline" | "reassess"

    # ---- 规划 ----
    plan: dict[str, Any]                   # {weeks, total_weeks, current_week, status}
    current_week: int
    adjustment: str                        # 动态调整说明
    reassess_done: bool
    mindmap_text: str                      # 闯关路线 mermaid（交付物）

    # ---- 学习 ----
    knowledge_hits: list[dict[str, Any]]   # RAG 检索结果
    lesson: str                            # 讲师讲解
    learn_turns: int                       # 讲师追问轮次
    user_action: str                       # 用户选择：继续问/去演练/复盘

    # ---- 演练 ----
    scenario: dict[str, Any]
    spar_transcript: list[dict[str, str]]  # [{role, content}]
    spar_feedback: dict[str, Any]
    battle_over: bool

    # ---- 复盘 ----
    review: dict[str, Any]                 # Kolb 四段
    report: dict[str, Any]                 # 毕业战报
    xp: int
    level: int

    # ---- 基础设施 ----
    llm_mode: str                          # "mock" | "claude"
    tools_called: list[dict[str, Any]]     # 工具调用日志（评审证据）


def new_initial_state(learner_id: str, goal: str) -> dict[str, Any]:
    """新建会话的初始状态。"""
    return {
        "learner_id": learner_id,
        "goal": goal,
        "messages": [],
        "current_week": 0,
        "learn_turns": 0,
        "assessment_questions": [],
        "assessment_answers": [],
        "assessment_plan": [],
        "assessment_probes": [],
        "assessment_done": False,
        "pending_question": None,
        "pending_narration": None,
        "radar_before": None,
        "stage": "baseline",
        "reassess_done": False,
        "battle_over": False,
        "xp": 0,
        "level": 1,
        "spar_transcript": [],
        "tools_called": [],
        "llm_mode": "mock",
    }


def build_hud(
    state: dict[str, Any],
    stage: str,
    week: int | None = None,
    index: int | None = None,
    total: int | None = None,
    stage_label: str | None = None,
) -> dict[str, Any]:
    """构造前端 HUD（旅程点/周/进度/XP/等级），随每个 interrupt 下发。"""
    plan = state.get("plan") or {}
    hud: dict[str, Any] = {
        "stage": stage,
        "week": week if week is not None else state.get("current_week", 0),
        "total_weeks": plan.get("total_weeks", 0),
        "xp": state.get("xp", 0),
        "level": state.get("level", 1),
    }
    if index is not None:
        hud["index"] = index
    if total is not None:
        hud["total"] = total
    if stage_label is not None:
        hud["stage_label"] = stage_label
    return hud
