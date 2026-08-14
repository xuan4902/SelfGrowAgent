"""RAG 知识库检索测试（InMemory 向量库 + bigram embedding）。"""

import unittest

from selfgrow.rag.knowledge_base import KnowledgeBase
from selfgrow.rag.loader import chunk_text, load_corpus


class TestRAG(unittest.TestCase):
    def test_load_corpus_non_empty(self):
        chunks = load_corpus("managing_up")
        self.assertGreater(len(chunks), 20)
        # 语料应覆盖多篇文档
        titles = {c.title for c in chunks}
        self.assertGreaterEqual(len(titles), 8)

    def test_chunk_text_by_headings(self):
        text = "# 标题\n## 第一节\n内容内容内容内容内容内容内容内容\n## 第二节\n更多内容内容内容内容内容内容内容内容\n"
        blocks = chunk_text(text, min_chars=5)
        self.assertGreaterEqual(len(blocks), 2)
        self.assertEqual(blocks[0][0], "第一节")

    def test_retrieve_relevant(self):
        kb = KnowledgeBase(domain="managing_up")
        n = kb.build()
        self.assertGreater(n, 20)
        hits = kb.retrieve("向上汇报应该结论先行还是先讲背景", top_k=3)
        self.assertTrue(hits)
        # 第一命中应带『汇报』相关上下文
        top = hits[0].content + hits[0].title
        self.assertTrue(any(k in top for k in ("结论先行", "汇报", "金字塔")))

    def test_retrieve_matches_expected_doc(self):
        kb = KnowledgeBase(domain="managing_up")
        kb.build()
        hits = kb.retrieve("如何争取资源 用ROI论证", top_k=1)
        self.assertTrue(hits)
        self.assertIn("资源", hits[0].title + hits[0].section)


if __name__ == "__main__":
    unittest.main()
