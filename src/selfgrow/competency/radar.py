"""能力雷达：由作答记录聚合出各维度 1-5 级，并定位薄弱点。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.loader import load_framework

# 作答条目：{question_id, dimension, option(0-3), correct(bool)}
ANSWER_SCORE = 5  # 满分对应 5 级


@dataclass
class RadarResult:
    radar: dict[str, int]          # {dimension: 1-5}
    scores: dict[str, float]       # {dimension: 原始均分 0-1}
    answered: dict[str, int]       # {dimension: 作答数}
    gaps: list[str]                # 薄弱维度，升序排列（最弱在前）
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "radar": self.radar,
            "scores": self.scores,
            "answered": self.answered,
            "gaps": self.gaps,
            "summary": self.summary,
        }


def compute_radar(framework: CompetencyFramework, answers: list[dict[str, Any]]) -> RadarResult:
    """根据 MCQ 作答记录计算雷达。每个作答条目含 dimension 与 correct 布尔。"""
    acc: dict[str, list[bool]] = {d.id: [] for d in framework.dimensions}
    for a in answers:
        dim = a.get("dimension")
        if dim not in acc:
            continue
        acc[dim].append(bool(a.get("correct", False)))

    scores: dict[str, float] = {}
    radar: dict[str, int] = {}
    answered: dict[str, int] = {}
    for d in framework.dimensions:
        lst = acc[d.id]
        answered[d.id] = len(lst)
        if not lst:
            scores[d.id] = 0.0
            radar[d.id] = 1  # 未作答视为依赖期起点
            continue
        avg = sum(1 if x else 0 for x in lst) / len(lst)
        scores[d.id] = round(avg, 4)
        radar[d.id] = max(1, min(5, round(avg * ANSWER_SCORE)))

    # 薄弱维度：按分数升序，同分按维度顺序
    gaps = sorted(
        (d.id for d in framework.dimensions),
        key=lambda dim_id: (scores[dim_id], framework.dimension_ids().index(dim_id)),
    )

    return RadarResult(
        radar=radar,
        scores=scores,
        answered=answered,
        gaps=gaps,
        summary=summarize(framework, gaps, hint="建议作为第一周闯关主题"),
    )


def summarize(framework: CompetencyFramework, gaps: list[str], hint: str = "") -> str:
    """生成测评结论：最强 / 最弱（供复测合并后重算，避免与已合并雷达不一致）。"""
    weakest = framework.get_dimension(gaps[0]) if gaps else None
    strongest = framework.get_dimension(gaps[-1]) if gaps else None
    tail = f"，{hint}" if hint else "。"
    return f"你当前最强的是「{strongest.name}」，最需要修炼的是「{weakest.name}」{tail}"


def top_gaps(framework: CompetencyFramework, radar: dict[str, int], k: int = 2) -> list[str]:
    """按雷达值升序取最薄弱 k 个维度。"""
    ordered = sorted(
        (d.id for d in framework.dimensions),
        key=lambda dim_id: (radar.get(dim_id, 5), framework.dimension_ids().index(dim_id)),
    )
    return ordered[:k]


def render_ascii_radar(framework: CompetencyFramework, radar: dict[str, int]) -> str:
    """把雷达渲染为 ASCII 横向条（终端友好、可贴入文档）。"""
    lines = [f"📡 能力雷达 · {framework.name}"]
    width = 10  # 满格
    bar = "█"
    for d in framework.dimensions:
        level = radar.get(d.id, 1)
        filled = int(round(level / 5 * width))
        label = f"{d.name:<5}"
        lines.append(f"  {label} {bar * filled}{'·' * (width - filled)}  L{level}")
    return "\n".join(lines)


def mermaid_radar(framework: CompetencyFramework, radar: dict[str, int]) -> str:
    """输出雷达的 mermaid（供文档/演示）。"""
    rows = []
    for d in framework.dimensions:
        rows.append(f"    {d.name} (L{radar.get(d.id, 1)})")
    return "graph LR\n    A[能力雷达] --> B[最强]\n" + "\n".join(
        f"    A -->|{d.name}| D{i}" for i, d in enumerate(framework.dimensions)
    )
