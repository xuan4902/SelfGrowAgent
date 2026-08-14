"""知识库（RAG）：把语料分块 → 向量化 → 存入 VectorStore → 检索。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from selfgrow.rag.embedder import BigramHashEmbedder, Embedder
from selfgrow.rag.loader import Chunk, load_corpus
from selfgrow.storage.vector_store import VectorStore, create_vector_store

DEFAULT_DOMAIN = "managing_up"


@dataclass
class KnowledgeHit:
    doc_id: str
    title: str
    section: str
    content: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "title": self.title, "section": self.section,
                "content": self.content, "score": self.score}


class KnowledgeBase:
    """一次性构建 + 检索。构建幂等（重复 build 覆盖）。"""

    def __init__(
        self,
        domain: str = DEFAULT_DOMAIN,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.domain = domain
        self.store = store or create_vector_store()
        self.embedder = embedder or BigramHashEmbedder()
        self._chunks: dict[str, Chunk] = {}
        self._built = False

    def build(self) -> int:
        """加载语料并建立索引，返回 chunk 数。"""
        chunks = load_corpus(self.domain)
        self.store.clear()
        self._chunks = {}
        for c in chunks:
            vec = self.embedder.embed(c.to_text())
            self.store.add(
                c.doc_id,
                vec,
                {"title": c.title, "section": c.section, "content": c.content[:200]},
            )
            self._chunks[c.doc_id] = c
        self._built = True
        return len(chunks)

    def retrieve(self, query: str, top_k: int = 3) -> list[KnowledgeHit]:
        if not self._built:
            self.build()
        vec = self.embedder.embed(query)
        hits = self.store.search(vec, top_k=top_k)
        out: list[KnowledgeHit] = []
        for h in hits:
            chunk = self._chunks.get(h.doc_id)
            if chunk is None:
                continue
            out.append(
                KnowledgeHit(
                    doc_id=h.doc_id,
                    title=chunk.title,
                    section=chunk.section,
                    content=chunk.content,
                    score=h.score,
                )
            )
        return out

    def count(self) -> int:
        return self.store.count() if self._built else 0
