"""工具注册表：知识库检索 / 测评生成 / 框架加载 / 场景取用 / 数据落库 / 可视化。

节点通过 call_tool 调用并留痕（tools_called），作为评审证据。
所有工具为纯函数（含数据读取），确定性、可测试。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from selfgrow.competency.loader import load_framework
from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.radar import render_ascii_radar
from selfgrow.paths import ASSESSMENTS_DIR, SCENARIOS_DIR
from selfgrow.rag.knowledge_base import KnowledgeBase, KnowledgeHit

DEFAULT_DOMAIN = "managing_up"

# 题库/场景库缓存
_QUESTIONS: dict[str, list[dict[str, Any]]] = {}
_SCENARIOS: dict[str, list[dict[str, Any]]] = {}


def _load_questions(domain: str) -> list[dict[str, Any]]:
    if domain not in _QUESTIONS:
        path = ASSESSMENTS_DIR / f"{domain}_questions.json"
        if not path.exists():
            raise FileNotFoundError(f"题库不存在: {path}")
        _QUESTIONS[domain] = json.loads(path.read_text(encoding="utf-8"))["questions"]
    return _QUESTIONS[domain]


def _load_scenarios(domain: str) -> list[dict[str, Any]]:
    if domain not in _SCENARIOS:
        path = SCENARIOS_DIR / f"{domain}_scenarios.json"
        if not path.exists():
            raise FileNotFoundError(f"场景库不存在: {path}")
        _SCENARIOS[domain] = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    return _SCENARIOS[domain]


# ---- 工具函数（纯逻辑） ----

def load_framework_tool(domain: str = DEFAULT_DOMAIN) -> CompetencyFramework:
    return load_framework(domain)


def generate_assessment(
    domain: str = DEFAULT_DOMAIN,
    focus_dims: list[str] | None = None,
    per_dim: int = 2,
    min_difficulty: int = 1,
) -> list[dict[str, Any]]:
    """抽取测评题目。focus_dims 为空 = 全维度基线测评；否则聚焦指定维度（复测用）。"""
    bank = _load_questions(domain)
    if not focus_dims:
        focus_dims = sorted({q["dimension"] for q in bank})
    picked: list[dict[str, Any]] = []
    for dim in focus_dims:
        cand = [q for q in bank if q["dimension"] == dim and q.get("difficulty", 1) >= min_difficulty]
        # 确定性选取：取前 per_dim 道（题库已按难度递增排列）
        picked.extend(cand[:per_dim])
    return picked


def search_knowledge(kb: KnowledgeBase, query: str, top_k: int = 3) -> list[KnowledgeHit]:
    return kb.retrieve(query, top_k=top_k)


def get_scenario(
    domain: str = DEFAULT_DOMAIN, dimension: str | None = None, difficulty_hint: int | None = None
) -> dict[str, Any]:
    """按维度取情景副本；无匹配则取首个。"""
    scenarios = _load_scenarios(domain)
    if dimension:
        for s in scenarios:
            if s["dimension"] == dimension:
                return s
    for s in scenarios:
        if difficulty_hint and s.get("difficulty") == difficulty_hint:
            return s
    return scenarios[0]


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
