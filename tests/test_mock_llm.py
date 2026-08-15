"""Mock LLM 确定性测试。"""

import json
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

    # ---- 新增：逐题自适应出题 / 动态场景（确定性、纯 ctx） ----

    def test_assess_question_task_deterministic(self):
        user = with_ctx(
            {"domain": "managing_up", "dimension": "expectation_management",
             "min_difficulty": 1, "used_ids": [], "stage": "baseline"},
            "s",
        )
        user = with_task("assess_question", user)
        a = self.llm.complete("sys", user)
        b = self.llm.complete("sys", user)
        self.assertEqual(a, b)  # 同输入同输出
        q = json.loads(a)
        self.assertEqual(q["dimension"], "expectation_management")
        self.assertIn("scenario", q)
        self.assertEqual(len(q["options"]), 4)
        self.assertIn("correct", q)
        self.assertIn("rationale", q)

    def test_assess_question_respects_difficulty_and_used(self):
        # min_difficulty=2 → 难度 2 或更高；used 里的题不再返回
        user = with_ctx(
            {"domain": "managing_up", "dimension": "goal_alignment",
             "min_difficulty": 2, "used_ids": [], "stage": "baseline"},
            "s",
        )
        q = json.loads(self.llm.complete("sys", with_task("assess_question", user)))
        self.assertGreaterEqual(q["difficulty"], 2)

        user2 = with_ctx(
            {"domain": "managing_up", "dimension": "goal_alignment",
             "min_difficulty": 1, "used_ids": [q["id"]], "stage": "baseline"},
            "s",
        )
        q2 = json.loads(self.llm.complete("sys", with_task("assess_question", user2)))
        self.assertNotEqual(q["id"], q2["id"])

    def test_spar_scene_task_full_fields(self):
        user = with_ctx(
            {"domain": "managing_up", "dimension": "report_structure",
             "difficulty_hint": 1, "goal": "提升汇报能力", "user_profile": {"weakest": "handling_feedback"}},
            "s",
        )
        user = with_task("spar_scene", user)
        out = self.llm.complete("sys", user)
        s = json.loads(out)
        self.assertEqual(s["dimension"], "report_structure")
        self.assertTrue(s["title"])
        self.assertIn("environment", s)
        self.assertIn("stakes", s)
        self.assertIn("npc", s)
        pressure = s["pressure"]
        self.assertIn("level", pressure)
        self.assertIn("desc", pressure)
        npc = s["npc"]
        self.assertTrue(npc.get("opening"))
        self.assertTrue(npc.get("mock_lines"))
        # 确定性：同维度同场景
        again = json.loads(self.llm.complete("sys", user))
        self.assertEqual(s["id"], again["id"])


if __name__ == "__main__":
    unittest.main()
