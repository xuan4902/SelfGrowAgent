"""题库/场景库确定性选取（纯函数、缓存读、零引擎依赖）。

供 tools.py（LLM 生成失败时的兜底）与 mock_provider.py（Mock 路由）共用，
避免它们互相 import 产生环。全部确定性：同输入同输出。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from selfgrow.paths import ASSESSMENTS_DIR, SCENARIOS_DIR

_QUESTIONS: dict[str, list[dict[str, Any]]] = {}
_SCENARIOS: dict[str, list[dict[str, Any]]] = {}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_questions(domain: str) -> list[dict[str, Any]]:
    if domain not in _QUESTIONS:
        path = ASSESSMENTS_DIR / f"{domain}_questions.json"
        if not path.exists():
            raise FileNotFoundError(f"题库不存在: {path}")
        _QUESTIONS[domain] = _load_json(path)["questions"]
    return _QUESTIONS[domain]


def load_scenarios(domain: str) -> list[dict[str, Any]]:
    if domain not in _SCENARIOS:
        path = SCENARIOS_DIR / f"{domain}_scenarios.json"
        if not path.exists():
            raise FileNotFoundError(f"场景库不存在: {path}")
        _SCENARIOS[domain] = _load_json(path)["scenarios"]
    return _SCENARIOS[domain]


def pick_question(
    domain: str,
    dimension: str | None = None,
    min_difficulty: int = 1,
    used_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    """目标维度首个未用且难度达标题；无则放宽到任意维度；仍无返回 None。"""
    used = set(used_ids or [])
    if dimension:
        cands = [
            q for q in load_questions(domain)
            if q.get("dimension") == dimension
            and q.get("difficulty", 1) >= min_difficulty
            and q.get("id") not in used
        ]
        if cands:
            return copy.deepcopy(cands[0])
    for q in load_questions(domain):
        if q.get("id") not in used:
            return copy.deepcopy(q)
    return None


def has_unused_question(
    domain: str, dimension: str, min_difficulty: int, used_ids: list[str] | None = None
) -> bool:
    """该维度是否还有难度≥min 且未用过的题（自适应追问的预算判断）。"""
    used = set(used_ids or [])
    return any(
        q.get("dimension") == dimension
        and q.get("difficulty", 1) >= min_difficulty
        and q.get("id") not in used
        for q in load_questions(domain)
    )


def pick_scenario(domain: str, dimension: str | None = None) -> dict[str, Any]:
    """按维度取情景副本；无匹配则取首个。返回深拷贝避免污染缓存。"""
    scenarios = load_scenarios(domain)
    for s in scenarios:
        if dimension and s.get("dimension") == dimension:
            return copy.deepcopy(s)
    return copy.deepcopy(scenarios[0])


def scenario_title_for_id(domain: str, scenario_id: str) -> str:
    for s in load_scenarios(domain):
        if s.get("id") == scenario_id:
            return s.get("title", scenario_id)
    return scenario_id
