"""Mock LLM 确定性测试。"""

import unittest

from selfgrow.llm.base import extract_task, with_ctx, with_task
from selfgrow.llm.mock_provider import MockLLM


class TestMockLLM(unittest.TestCase):
    def setUp(self):
        self.llm = MockLLM()

    def test_task_routing(self):
        out = self.llm.complete(
            "系统提示",
            with_task("lesson", "本周主题"),
        )
        self.assertIn("知识库", out)

    def test_deterministic_same_input_same_output(self):
        user = with_task("lesson", "目标对齐")
        a = self.llm.complete("sys", user)
        b = self.llm.complete("sys", user)
        self.assertEqual(a, b)

    def test_ctx_injection(self):
        user = with_ctx({"mock_lines": ["第一句", "第二句"], "turn": 1}, "s")
        user = with_task("spar_npc", user)
        out = self.llm.complete("sys", user)
        self.assertEqual(out, "第二句")

    def test_unknown_task_falls_back_to_chat(self):
        out = self.llm.complete("sys", with_task("no_such", "x"))
        self.assertIn("示例回复", out)

    def test_extract_task(self):
        self.assertEqual(extract_task("[TASK: plan]\n hi"), "plan")
        self.assertIsNone(extract_task("no tag here"))

    def test_spar_feedback_template(self):
        user = with_ctx({"overall_level": 2, "mistakes": ["A"], "suggestions": ["B"]}, "s")
        out = self.llm.complete("sys", with_task("spar_feedback", user))
        self.assertIn("L2", out)
        self.assertIn("A", out)


if __name__ == "__main__":
    unittest.main()
