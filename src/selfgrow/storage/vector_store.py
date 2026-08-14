"""向量存储适配器：协议 + InMemory 兜底 + Milvus 生产实现。

选择：环境变量 SELFGROW_VECTOR_STORE（默认 "memory"；设 "milvus" 走 Milvus）。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SearchHit:
    doc_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    """向量库协议：add / search / count / clear。"""

    def add(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None: ...

    def search(self, vector: list[float], top_k: int = 3) -> list[SearchHit]: ...

    def count(self) -> int: ...

    def clear(self) -> None: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """纯内存向量库（stdlib 余弦），零依赖兜底。"""

    def __init__(self) -> None:
        self._vectors: list[list[float]] = []
        self._meta: list[dict[str, Any]] = []
        self._ids: list[str] = []

    def add(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        self._ids.append(doc_id)
        self._vectors.append(list(vector))
        self._meta.append(dict(metadata or {}))

    def search(self, vector: list[float], top_k: int = 3) -> list[SearchHit]:
        scored = [
            (_cosine(vector, v), i) for i, v in enumerate(self._vectors)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        hits: list[SearchHit] = []
        for score, idx in scored[:top_k]:
            if score <= 0:
                continue
            hits.append(SearchHit(doc_id=self._ids[idx], score=round(score, 4), metadata=self._meta[idx]))
        return hits

    def count(self) -> int:
        return len(self._vectors)

    def clear(self) -> None:
        self._vectors.clear()
        self._meta.clear()
        self._ids.clear()


class MilvusVectorStore:
    """Milvus 生产实现（需 pymilvus 与运行中的 Milvus，可选依赖）。"""

    COLLECTION = "selfgrow_kb"

    def __init__(self, dim: int = 256, uri: str | None = None):
        try:
            from pymilvus import MilvusClient  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "未安装 pymilvus。请 `pip install -e \".[milvus]\"`，并确认 Milvus 服务已启动。"
            ) from e
        self._dim = dim
        self._uri = uri or os.environ.get("MILVUS_URI", "http://localhost:19530")
        from pymilvus import MilvusClient

        self._client = MilvusClient(uri=self._uri)
        self._ensure_collection()

    def _ensure_collection(self) -> None:  # pragma: no cover - 需真实 Milvus
        from pymilvus import DataType

        if not self._client.has_collection(self.COLLECTION):
            self._client.create_collection(
                collection_name=self.COLLECTION,
                dimension=self._dim,
                metric_type="COSINE",
            )

    def add(self, doc_id: str, vector: list[float], metadata: dict[str, Any] | None = None) -> None:
        data = [{"id": doc_id, "vector": vector, **(metadata or {})}]
        self._client.insert(collection_name=self.COLLECTION, data=data)

    def search(self, vector: list[float], top_k: int = 3) -> list[SearchHit]:
        res = self._client.search(
            collection_name=self.COLLECTION, data=[vector], limit=top_k, output_fields=["*"]
        )
        hits: list[SearchHit] = []
        for row in (res[0] if res else []):
            hits.append(
                SearchHit(
                    doc_id=row.get("id", ""),
                    score=round(float(row.get("distance", 0.0)), 4),
                    metadata={k: v for k, v in row.items() if k not in ("id", "vector", "distance")},
                )
            )
        return hits

    def count(self) -> int:
        return int(self._client.get_collection_stats(self.COLLECTION).get("row_count", 0))

    def clear(self) -> None:  # pragma: no cover
        from pymilvus import DataType  # noqa: F401

        self._client.drop_collection(self.COLLECTION)
        self._ensure_collection()


def create_vector_store() -> VectorStore:
    """按环境变量创建向量库实例。"""
    mode = os.environ.get("SELFGROW_VECTOR_STORE", "memory").strip().lower()
    if mode == "milvus":
        return MilvusVectorStore()
    return InMemoryVectorStore()
