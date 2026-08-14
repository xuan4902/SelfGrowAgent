"""能力框架加载与校验。"""

from __future__ import annotations

import json
from functools import lru_cache

from selfgrow.competency.models import CompetencyFramework
from selfgrow.paths import FRAMEWORKS_DIR


class FrameworkNotFoundError(FileNotFoundError):
    pass


class FrameworkValidationError(ValueError):
    pass


@lru_cache(maxsize=32)
def load_framework(domain: str) -> CompetencyFramework:
    """按领域 id 加载并校验能力框架。结果缓存，避免重复 IO。"""
    path = FRAMEWORKS_DIR / f"{domain}.json"
    if not path.exists():
        raise FrameworkNotFoundError(f"未找到能力框架: {path}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    framework = CompetencyFramework.from_dict(raw)
    errors = framework.validate()
    if errors:
        raise FrameworkValidationError(f"框架 {domain} 校验失败: {'; '.join(errors)}")
    return framework


def clear_framework_cache() -> None:
    load_framework.cache_clear()
