"""真 Claude 实现（anthropic SDK）。未配置 key 或未安装 SDK 时报清晰错误。"""

from __future__ import annotations

import os

from selfgrow.llm.base import LLMError


class ClaudeLLM:
    mode = "claude"

    def __init__(self, model: str | None = None, max_tokens: int = 2048):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - 仅在缺依赖时触发
            raise LLMError(
                "未安装 anthropic SDK。请先 `pip install -e \".[engine]\"` 或 `pip install anthropic`。"
            ) from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise LLMError("未设置 ANTHROPIC_API_KEY 环境变量，无法使用真模型模式。")
        self._client = anthropic.Anthropic(api_key=api_key)
        # 默认使用最新 Claude 模型；可用 SELFGROW_MODEL 覆盖
        self._model = model or os.environ.get("SELFGROW_MODEL") or "claude-sonnet-4-5"
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [getattr(block, "text", "") for block in resp.content]
        return "".join(parts).strip()
