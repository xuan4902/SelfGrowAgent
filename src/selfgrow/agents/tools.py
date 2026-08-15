"""工具注册表：题目/场景生成（LLM+题库兜底）/ 知识库检索 / 框架加载 / 数据落库 / 可视化。

节点通过 call_tool 调用并留痕（tools_called），作为评审证据。
LLM 负责内容生成，代码负责选型与校验：真模型现场出题/出场景，Mock 走题库确定性拼装，
解析失败回退确定性 bank，保证双模行为一致、循环永不卡死。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from selfgrow.agents.bank import pick_question, pick_scenario
from selfgrow.competency.loader import load_framework
from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.radar import render_ascii_radar
from selfgrow.llm.base import with_ctx, with_task
from selfgrow.rag.knowledge_base import KnowledgeBase, KnowledgeHit

DEFAULT_DOMAIN = "managing_up"


# ---- 工具函数（纯逻辑 + LLM 内容生成） ----

def load_framework_tool(domain: str = DEFAULT_DOMAIN) -> CompetencyFramework:
    return load_framework(domain)


def _sanitize_question(q: Any, dimension: str, min_difficulty: int, used: list[str]) -> dict[str, Any] | None:
    """校验/归一化 LLM 返回的题目 JSON；不合法返回 None。"""
    if not isinstance(q, dict) or not q.get("scenario"):
        return None
    opts = q.get("options")
    if not isinstance(opts, list) or len(opts) < 2:
        return None
    correct = q.get("correct")
    if not isinstance(correct, int) or isinstance(correct, bool) or not (0 <= correct < len(opts)):
        correct = 0
    q["options"] = [str(o) for o in opts]
    q["correct"] = correct
    q.setdefault("dimension", dimension)
    q.setdefault("difficulty", min_difficulty)
    q.setdefault("rationale", "")
    q.setdefault("id", f"gen_{dimension}_{len(used) + 1}")
    return q


def generate_question(
    llm: Any,
    role_prompt: str,
    dimension: str | None = None,
    min_difficulty: int = 1,
    used_ids: list[str] | None = None,
    domain: str = DEFAULT_DOMAIN,
    stage: str = "baseline",
    goal: str = "",
    prior_answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成一道情景测评题（AI 逐题自适应）。Mock 走题库确定性拼装；真模型现场出题。

    返回 {id, dimension, difficulty, scenario, options[], correct, rationale}。
    """
    used = list(used_ids or [])
    ctx = {
        "domain": domain,
        "dimension": dimension,
        "min_difficulty": min_difficulty,
        "used_ids": used,
        "stage": stage,
        "goal": goal,
        "prior_answers": (prior_answers or [])[:6],
    }
    raw = llm.complete(
        role_prompt,
        with_ctx(ctx, with_task("assess_question", "生成一道情景测评题（只输出 JSON）")),
    )
    try:
        q = _sanitize_question(json.loads(raw), dimension, min_difficulty, used)
        if q is not None:
            return q
    except (ValueError, TypeError):
        pass
    # 兜底：确定性题库选取（Claude 解析失败 / Mock 兜底均走这里）
    q = pick_question(domain, dimension, min_difficulty, used)
    if q is None:
        q = {
            "id": f"gen_{dimension}_{len(used) + 1}",
            "dimension": dimension,
            "difficulty": min_difficulty,
            "scenario": "面对一个棘手的职场任务，你更倾向于怎么处理？",
            "options": ["直接照办", "先澄清目标与约束再行动", "自行权衡处理", "暂缓处理"],
            "correct": 1,
            "rationale": "先澄清目标与约束，是对齐的第一步。",
        }
    return q


def _sanitize_scenario(s: Any, dimension: str, difficulty_hint: int | None) -> dict[str, Any] | None:
    """校验/归一化 LLM 返回的场景 JSON；不合法返回 None。"""
    if not isinstance(s, dict) or not s.get("title"):
        return None
    s.setdefault("dimension", dimension)
    s.setdefault("difficulty", difficulty_hint or 3)
    s.setdefault("environment", "")
    s.setdefault("stakes", "")
    s.setdefault("ideal", "")
    s.setdefault("pressure", {"level": 3, "desc": ""})
    npc = s.get("npc")
    if not isinstance(npc, dict):
        npc = {}
        s["npc"] = npc
    npc.setdefault("role", "上级")
    npc.setdefault("persona", "")
    npc.setdefault("opening", "「说说你的情况。」")
    npc.setdefault("mock_lines", ["（等待你的回应）"])
    pressure = s.get("pressure")
    if not isinstance(pressure, dict) or not isinstance(pressure.get("level", 3), int):
        s["pressure"] = {"level": 3, "desc": ""}
    return s


def generate_scenario(
    llm: Any,
    role_prompt: str,
    dimension: str | None = None,
    difficulty_hint: int | None = None,
    domain: str = DEFAULT_DOMAIN,
    goal: str = "",
    user_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成一个职场情景副本（老板人设/环境/事件/利害压力）。Mock 走场景库确定性拼装。"""
    ctx = {
        "domain": domain,
        "dimension": dimension,
        "difficulty_hint": difficulty_hint,
        "goal": goal,
        "user_profile": user_profile or {},
    }
    raw = llm.complete(
        role_prompt,
        with_ctx(ctx, with_task("spar_scene", "生成一个职场情景副本（只输出 JSON）")),
    )
    try:
        s = _sanitize_scenario(json.loads(raw), dimension, difficulty_hint)
        if s is not None:
            return s
    except (ValueError, TypeError):
        pass
    return pick_scenario(domain, dimension)


def search_knowledge(kb: KnowledgeBase, query: str, top_k: int = 3) -> list[KnowledgeHit]:
    return kb.retrieve(query, top_k=top_k)


def load_profile(db: Any, learner_id: str) -> dict[str, Any] | None:
    from selfgrow.storage.repos import get_learner

    return get_learner(db, learner_id)


def save_record(db: Any, table: str, data: dict[str, Any]) -> int:
    from selfgrow.storage.repos import save_assessment, save_learner, save_learning_record, save_plan, save_review, save_spar_session

    dispatch: dict[str, Callable] = {
        "learners": save_learner,
        "assessments": save_assessment,
        "plans": save_plan,
        "learning_records": save_learning_record,
        "spar_sessions": save_spar_session,
        "reviews": save_review,
    }
    fn = dispatch.get(table)
    if fn is None:
        raise ValueError(f"未知落库表: {table}")
    return fn(db, **data)


def render_radar_tool(framework: CompetencyFramework, radar: dict[str, int]) -> str:
    return render_ascii_radar(framework, radar)


def build_mindmap(plan: dict[str, Any], out_path: str | Path) -> str:
    """把闯关路线渲染为 mermaid 思维导图，写入文件并返回文本。"""
    weeks = plan.get("weeks", [])
    lines = ["mindmap", "  root((向上管理 · 闯关路线))"]
    for w in weeks:
        lines.append(f"    W{w['week']}[{w['topic']}]")
    mermaid = "\n".join(lines)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(mermaid, encoding="utf-8")
    return mermaid


# ---- 调用留痕 ----

def _brief(v: Any, limit: int = 80) -> Any:
    if isinstance(v, dict):
        return {k: _brief(x, limit) for k, x in list(v.items())[:6]}
    if isinstance(v, (list, tuple)):
        return [str(x)[:40] for x in v[:3]]
    s = str(v)
    return s[:limit] + ("…" if len(s) > limit else "")


def call_tool(log: list[dict[str, Any]], name: str, fn: Callable, **kwargs: Any) -> Any:
    """执行工具并记录到调用日志（评审证据：工具调用）。"""
    result = fn(**kwargs)
    log.append({"name": name, "args": _brief(kwargs), "result": _brief(result)})
    return result
