"""Embedding 抽象 + 零依赖实现：中文 char-bigram 哈希向量（L2 归一，余弦相似）。

生产环境可替换为真实 embedding 模型（配合 Milvus），只需实现 Embedder 协议。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    """把文本编码为稠密向量。"""

    dim: int

    def embed(self, text: str) -> list[float]: ...


class BigramHashEmbedder:
    """中文 char-bigram 哈希编码：确定性、零依赖、对中文短文本效果够用。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _tokens(self, text: str) -> list[str]:
        t = re.sub(r"\s+", "", text.lower())
        t = re.sub(r"[#*`\-_|]", "", t)  # 去 markdown 符号
        if not t:
            return []
        if len(t) <= 2:
            return [t]
        return [t[i : i + 2] for i in range(len(t) - 1)]

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in self._tokens(text):
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
