"""能力框架数据模型（dataclass + 序列化）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScaleLevel:
    """全局评级标尺（1 依赖期 ~ 5 精通期）。"""

    level: int
    label: str
    desc: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScaleLevel":
        return cls(level=d["level"], label=d["label"], desc=d["desc"])

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "label": self.label, "desc": self.desc}


@dataclass
class DimensionLevel:
    """某维度的某一级行为锚定 + 向上一级的提升路径。"""

    level: int
    anchor: str
    path: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DimensionLevel":
        return cls(level=d["level"], anchor=d["anchor"], path=d["path"])

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "anchor": self.anchor, "path": self.path}


@dataclass
class RubricCriterion:
    """演练/开放作答的评分维度。"""

    criterion: str
    desc: str
    weight: float

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RubricCriterion":
        return cls(criterion=d["criterion"], desc=d["desc"], weight=float(d["weight"]))

    def to_dict(self) -> dict[str, Any]:
        return {"criterion": self.criterion, "desc": self.desc, "weight": self.weight}


@dataclass
class Dimension:
    """一项子能力：名称 + 5 级行为锚定 + 演练评分标准。"""

    id: str
    name: str
    description: str
    levels: list[DimensionLevel] = field(default_factory=list)
    rubric: list[RubricCriterion] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Dimension":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            levels=[DimensionLevel.from_dict(x) for x in d["levels"]],
            rubric=[RubricCriterion.from_dict(x) for x in d.get("rubric", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "levels": [x.to_dict() for x in self.levels],
            "rubric": [x.to_dict() for x in self.rubric],
        }

    def level(self, n: int) -> DimensionLevel | None:
        """取第 n 级（1-5），越界返回 None。"""
        for x in self.levels:
            if x.level == n:
                return x
        return None

    def improvement_path(self, n: int) -> str:
        """第 n 级向上一级的行动建议。"""
        x = self.level(n)
        return x.path if x else ""

    def rubric_weight_sum(self) -> float:
        return round(sum(c.weight for c in self.rubric), 4)


@dataclass
class CompetencyFramework:
    """整个能力框架（一个领域）。"""

    domain: str
    name: str
    description: str
    scale: list[ScaleLevel] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CompetencyFramework":
        return cls(
            domain=d["domain"],
            name=d["name"],
            description=d.get("description", ""),
            scale=[ScaleLevel.from_dict(x) for x in d.get("scale", [])],
            dimensions=[Dimension.from_dict(x) for x in d["dimensions"]],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "name": self.name,
            "description": self.description,
            "scale": [x.to_dict() for x in self.scale],
            "dimensions": [x.to_dict() for x in self.dimensions],
        }

    def get_dimension(self, dim_id: str) -> Dimension | None:
        for d in self.dimensions:
            if d.id == dim_id:
                return d
        return None

    def dimension_ids(self) -> list[str]:
        return [d.id for d in self.dimensions]

    def validate(self) -> list[str]:
        """结构校验，返回错误列表（空 = 通过）。"""
        errors: list[str] = []
        if not self.dimensions:
            errors.append("dimensions 为空")
        for d in self.dimensions:
            if len(d.levels) != 5:
                errors.append(f"维度 {d.id} 的 levels 数量应为 5，实际 {len(d.levels)}")
            for i, lv in enumerate(d.levels, start=1):
                if lv.level != i:
                    errors.append(f"维度 {d.id} 的 levels 顺序错误：期望 {i}，实际 {lv.level}")
            if d.rubric:
                s = d.rubric_weight_sum()
                if abs(s - 1.0) > 1e-6:
                    errors.append(f"维度 {d.id} 的 rubric 权重之和应为 1.0，实际 {s}")
        return errors
