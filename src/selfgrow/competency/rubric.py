"""演练/开放作答的评分：按维度 rubric 打分。

双模设计：Mock 用确定性关键词启发式（保证测试与演示可复现）；
真模型模式由 LLMProvider 生成结构化打分，这里只做归一化聚合。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from selfgrow.competency.models import CompetencyFramework, RubricCriterion


class RubricLLM(Protocol):
    """评分 LLM 接口：输入开放作答文本 + 评分标准，输出每项 0-1 分。"""

    def score_open_response(
        self, text: str, criteria: list[RubricCriterion]
    ) -> dict[str, float]: ...


@dataclass
class RubricResult:
    scores: dict[str, float]          # {criterion: 0-1}
    weighted: float                   # 加权总分 0-1
    overall_level: int                # 映射到 1-5 级
    mistakes: list[str]               # 错因（可读）
    suggestions: list[str]            # 改进建议

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": self.scores,
            "weighted": round(self.weighted, 4),
            "overall_level": self.overall_level,
            "mistakes": self.mistakes,
            "suggestions": self.suggestions,
        }


# 与 rubric 描述强相关的启发式关键词（Mock 评分用；真模型模式忽略）
_MOCK_HINTS: dict[str, list[str]] = {
    "目标挂接": ["目标", "对齐", "优先级", "贡献", "季"],
    "优先级确认": ["确认", "优先级", "排期", "先后", "取舍"],
    "信息更新": ["同步", "更新", "变化", "进展"],
    "主动建议": ["建议", "方案", "优化", "提议", "替代"],
    "结论先行": ["结论", "先", "一句话", "核心"],
    "结构化表达": ["第一", "第二", "首先", "其次", "1.", "2.", "要点"],
    "数据支撑": ["%", "数字", "数据", "增长", "数量", "3", "%" ],
    "信息筛选": ["不需要", "不必", "重点", "筛选", "无关"],
    "澄清标准": ["验收", "标准", "交付", "时限", "什么时候", "确认"],
    "现实约束": ["约束", "做不到", "现实", "有限", "平衡", "风险"],
    "缓冲机制": ["提前", "缓冲", "节点", "偏差", "预警"],
    "可信度": ["承诺", "兑现", "靠谱", "可查"],
    "论证有力": ["ROI", "回报", "价值", "收益", "为什么", "目标"],
    "诉求清晰": ["需要", "要", "资源", "人", "预算", "时间"],
    "替代方案": ["替代", "备选", "方案B", "妥协", "折中"],
    "韧性": ["再试", "迭代", "重新", "下次", "调整"],
    "透明同步": ["同步", "进展", "更新", "汇报", "周报"],
    "及时求助": ["求助", "卡", "阻碍", "需要", "支持", "帮忙"],
    "报喜也报忧": ["风险", "问题", "坏消息", "不顺利", "延迟"],
    "风格适配": ["方式", "习惯", "风格", "节奏", "喜欢"],
    "冷静接收": ["谢谢", "明白", "理解", "记下", "好的"],
    "区分事实情绪": ["事实", "情绪", "具体", "例子", "哪里"],
    "确认理解": ["复述", "确认", "我理解", "是不是", "对吗"],
    "跟进转化": ["改进", "计划", "跟进", "落实", "行动"],
}


def _heuristic_score(text: str, criterion: RubricCriterion) -> float:
    """按关键词命中率给 0-1 分（Mock 专用，确定性）。"""
    hints = _MOCK_HINTS.get(criterion.criterion, [])
    if not hints:
        return 0.5
    hits = sum(1 for h in hints if h in text)
    return round(min(1.0, hits / max(1, len(hints)) * 1.4), 4)


class MockRubricEvaluator:
    """确定性启发式评分（无 API Key 时使用）。"""

    def score_open_response(
        self, text: str, criteria: list[RubricCriterion]
    ) -> dict[str, float]:
        return {c.criterion: _heuristic_score(text, c) for c in criteria}


class ClaudeRubricEvaluator:
    """真模型评分：由 LLMProvider 实现，这里透传。"""

    def __init__(self, llm: RubricLLM):
        self._llm = llm

    def score_open_response(
        self, text: str, criteria: list[RubricCriterion]
    ) -> dict[str, float]:
        return self._llm.score_open_response(text, criteria)


def evaluate_response(
    framework: CompetencyFramework,
    dimension_id: str,
    text: str,
    evaluator: RubricLLM | None = None,
) -> RubricResult:
    """对一次开放作答按维度 rubric 打分。evaluator 为空时用 Mock 启发式。"""
    dim = framework.get_dimension(dimension_id)
    if dim is None or not dim.rubric:
        raise ValueError(f"维度 {dimension_id} 缺少 rubric 定义")
    criteria = dim.rubric

    if evaluator is None:
        evaluator = MockRubricEvaluator()  # type: ignore[assignment]

    raw = evaluator.score_open_response(text, criteria)
    scores = {c.criterion: max(0.0, min(1.0, raw.get(c.criterion, 0.0))) for c in criteria}
    weighted = sum(scores[c.criterion] * c.weight for c in criteria)
    overall_level = max(1, min(5, round(weighted * 5)))

    mistakes, suggestions = _diagnose(text, dim.rubric, scores)
    return RubricResult(
        scores=scores,
        weighted=round(weighted, 4),
        overall_level=overall_level,
        mistakes=mistakes,
        suggestions=suggestions,
    )


def _diagnose(
    text: str, criteria: list[RubricCriterion], scores: dict[str, float]
) -> tuple[list[str], list[str]]:
    """低分项 → 错因；高分项 → 强化建议（Mock 确定性）。"""
    mistakes: list[str] = []
    suggestions: list[str] = []
    for c in criteria:
        s = scores.get(c.criterion, 0.0)
        if s < 0.4:
            mistakes.append(f"「{c.criterion}」偏弱：{c.desc}")
        elif s >= 0.75:
            suggestions.append(f"「{c.criterion}」做得不错，继续保持")
    if not mistakes:
        mistakes.append("整体结构基本完整，重点打磨表达的细节颗粒度")
    if not suggestions:
        suggestions.append("把关键结论放在最前面，用一句话先说结果")
    return mistakes, suggestions
