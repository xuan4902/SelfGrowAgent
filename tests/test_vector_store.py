"""向量库适配器测试（InMemory）。"""

import unittest

from selfgrow.storage.vector_store import InMemoryVectorStore


class TestInMemoryVectorStore(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryVectorStore()

    def test_add_search_order(self):
        self.store.add("a", [1.0, 0.0, 0.0], {"title": "A"})
        self.store.add("b", [0.0, 1.0, 0.0], {"title": "B"})
        hits = self.store.search([0.99, 0.01, 0.0], top_k=2)
        self.assertEqual(hits[0].doc_id, "a")
        self.assertGreater(hits[0].score, hits[1].score)

    def test_count_and_clear(self):
        self.store.add("a", [1.0, 0.0])
        self.assertEqual(self.store.count(), 1)
        self.store.clear()
        self.assertEqual(self.store.count(), 0)

    def test_metadata_preserved(self):
        self.store.add("x", [1.0, 0.0], {"k": "v"})
        hit = self.store.search([1.0, 0.0], top_k=1)[0]
        self.assertEqual(hit.metadata["k"], "v")


if __name__ == "__main__":
    unittest.main()
