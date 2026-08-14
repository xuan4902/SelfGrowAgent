"""LLM 抽象与工厂：双模（真 Claude / 确定性 Mock）。

选择规则：
- SELFGROW_LLM=claude -> 强制真模型（无 key / 未装 SDK 时报错）
- SELFGROW_LLM=mock    -> 强制 Mock
- 未设置               -> 有 ANTHROPIC_API_KEY 且已装 anthropic 则用真模型，否则 Mock
"""

from __future__ import annotations

import os
import re
from typing import Protocol

TASK_PATTERN = re.compile(r"\[TASK:\s*(\w+)\]")
CTX_MARKER = "CTX:"


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    """模型提供方。complete 输入角色系统提示 + 用户内容，输出文本。"""

    mode: str

    def complete(self, system: str, user: str) -> str: ...


def extract_task(user: str) -> str | None:
    """从用户内容提取 [TASK:xxx] 标签。"""
    m = TASK_PATTERN.search(user)
    return m.group(1) if m else None


def with_task(task: str, text: str) -> str:
    """给用户内容打上任务标签（Mock 路由用）。"""
    return f"[TASK: {task}]\n{text}"


def with_ctx(data: dict, text: str) -> str:
    """把结构化上下文注入用户内容（JSON 行），供模板填充。"""
    import json

    return f"{CTX_MARKER} {json.dumps(data, ensure_ascii=False)}\n{text}"


def get_llm() -> LLMProvider:
    from selfgrow.llm.claude_provider import ClaudeLLM
    from selfgrow.llm.mock_provider import MockLLM

    env_mode = os.environ.get("SELFGROW_LLM", "").strip().lower()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if env_mode == "claude":
        return ClaudeLLM()
    if env_mode == "mock":
        return MockLLM()
    if has_key:
        try:
            return ClaudeLLM()
        except (ImportError, LLMError):
            return MockLLM()
    return MockLLM()
