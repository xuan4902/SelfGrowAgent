"""口语语义解析：把 ASR 文本映射为结构化动作（测评选项 / 学习动作 / 确认 / 重说）。

纯函数、确定性，无外部依赖，可完整单测。
"""

from __future__ import annotations

import re
from typing import Any

RETRY = "RETRY"  # 要求重说

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4}
_LETTERS = {"a": 0, "b": 1, "c": 2, "d": 3}
_RETRY_WORDS = ("重说", "重来", "重录", "没听清", "没听请", "不对", "不是这个", "换一个", "再读一遍")

# 分词用的标点（必须写成字符类 [..]；裸串会被当作字面序列，无法匹配单个标点）
_PUNCT_RE = re.compile(r"[，。、；：,.;:!?！？\s]+")


def _norm(text: str) -> str:
    return _PUNCT_RE.sub("", str(text or ""))


def _to_index(word: str) -> int | None:
    if word.isdigit():
        n = int(word)
        return n - 1 if 1 <= n <= 4 else None
    if word in _CN_NUM:
        return _CN_NUM[word] - 1
    if word.lower() in _LETTERS:
        return _LETTERS[word.lower()]
    return None


def parse_option(text: str, question: dict[str, Any]) -> tuple[int | None, bool]:
    """解析测评选项。

    返回 (选项下标或 None, 是否精确命中)。
    - ordinal/字母直接命中（如「第二项」「选2」「B」）→ 精确（is_exact=True），可自动通过
    - 选项内容关键词唯一命中 → 命中的那一项，is_exact=False（仍需确认兜底）
    - 多命中 / 无命中 → (None, False) → 重听
    """
    raw = _norm(text)
    if not raw:
        return None, False
    for w in _RETRY_WORDS:
        if w in raw:
            return RETRY, False  # type: ignore[return-value]

    # 1) 序数/字母精确匹配
    m = re.search(r"第\s*([0-9一二两三四])\s*(个|项|题|选项|条)?", raw)
    if m:
        idx = _to_index(m.group(1))
        if idx is not None:
            return idx, True
    m = re.search(r"(选|我选|选择)?\s*(?:项|题)?\s*([0-9一二两三四])\s*(吧|项|个|号|题)?$", raw)
    if m and m.group(2):
        idx = _to_index(m.group(2))
        if idx is not None:
            return idx, True
    m = re.search(r"([a-dA-D])\s*(项|选项)?", raw)
    if m:
        return _to_index(m.group(1)), True

    # 2) 选项内容关键词唯一命中
    hits = _content_hits(raw, question.get("options", []))
    if hits is not None:
        return hits, False
    return None, False


def _bigram_sim(a: str, b: str) -> float:
    """字符二元组覆盖率（容忍个别字增删/换序），∈[0,1]。与 RAG 同源。"""
    if not a or not b:
        return 0.0

    def bigrams(s: str) -> set[str]:
        return {s[i : i + 2] for i in range(len(s) - 1)}

    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return 2.0 * len(ga & gb) / (len(ga) + len(gb))


def _content_hits(raw: str, options: list[str]) -> int | None:
    """统计每个选项被口语命中的证据分：整句包含(强) + bigram 相似(弱)。

    唯一且证据分 ≥ 0.55 才采用，否则重听。非精确命中后仍需确认兜底。
    """
    scores: list[float] = []
    for opt in options:
        tokens = [t for t in _PUNCT_RE.split(opt) if len(t) >= 2]
        containment = sum(
            1 for t in tokens if t in raw or (len(raw) >= 2 and raw in t)
        )
        sim = _bigram_sim(_PUNCT_RE.sub("", opt), raw)
        scores.append(containment + sim)
    best = max(scores, default=0.0)
    if best < 0.55:
        return None
    winners = [i for i, s in enumerate(scores) if s >= best - 1e-9]
    return winners[0] if len(winners) == 1 else None


_ACTION_KEYWORDS: dict[str, list[str]] = {
    "去演练": ["演练", "去练", "开打", "实战", "出发", "副本", "对线", "打一局"],
    "继续问": ["继续问", "继续", "再问", "追问", "多讲", "再讲", "多问", "再学"],
    "复盘": ["复盘", "总结", "回顾", "反思", "回放", "整理"],
}


def parse_action(text: str, options: list[str]) -> str | None:
    """把口语映射到给定动作之一（关键词计分，最高者胜出）。"""
    raw = _norm(text)
    if not raw:
        return None
    best_action: str | None = None
    best_score = 0
    for action in options:
        kws = _ACTION_KEYWORDS.get(action, [])
        score = sum(1 for k in kws if k in raw)
        if score > best_score:
            best_score = score
            best_action = action
    return best_action if best_score > 0 else None


_YES_WORDS = ("对", "是", "确认", "确定", "可以", "好的", "嗯", "对呀", "没错", "是的")
_NO_WORDS = ("重说", "重来", "不对", "不是", "错了", "重录", "没听清", "换")


def parse_confirm(text: str) -> str | None:
    """确认语：返回 'yes' / 'no' / None（无法判断）。"""
    raw = _norm(text)
    if not raw:
        return None
    for w in _NO_WORDS:
        if w in raw:
            return "no"
    for w in _YES_WORDS:
        if w in raw:
            return "yes"
    return None
