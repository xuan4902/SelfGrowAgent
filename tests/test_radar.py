"""能力雷达计算与薄弱点定位测试。"""

import unittest

from selfgrow.competency.loader import load_framework
from selfgrow.competency.radar import (
    compute_radar,
    render_ascii_radar,
    top_gaps,
)


class TestRadar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fw = load_framework("managing_up")

    def _answer(self, correct_by_dim):
        """按维度构造作答记录：每维给 n 题，指定答对数。"""
        answers = []
        for dim_id, (total, correct) in correct_by_dim.items():
            for i in range(total):
                answers.append(
                    {"question_id": f"{dim_id}_{i}", "dimension": dim_id, "correct": i < correct}
                )
        return answers

    def test_compute_radar_basic(self):
        # 每维 3 题；goal 对 3 题(满分)，report 对 0 题(最低)，其余对 2 题
        answers = self._answer(
            {
                "goal_alignment": (3, 3),
                "report_structure": (3, 0),
                "expectation_management": (3, 2),
                "resource_acquisition": (3, 2),
                "upward_communication": (3, 2),
                "handling_feedback": (3, 2),
            }
        )
        r = compute_radar(self.fw, answers)
        self.assertEqual(r.radar["goal_alignment"], 5)
        self.assertEqual(r.radar["report_structure"], 1)
        # 最弱的是 report_structure，最弱维度排在 gaps[0]
        self.assertEqual(r.gaps[0], "report_structure")
        self.assertEqual(r.gaps[-1], "goal_alignment")
        self.assertIn("最需要修炼的是「汇报结构」", r.summary)

    def test_top_gaps(self):
        radar = {
            "goal_alignment": 4,
            "report_structure": 2,
            "expectation_management": 3,
            "resource_acquisition": 5,
            "upward_communication": 3,
            "handling_feedback": 4,
        }
        gaps = top_gaps(self.fw, radar, k=2)
        self.assertEqual(gaps, ["report_structure", "expectation_management"])

    def test_unanswered_dimension_defaults_to_l1(self):
        answers = [{"question_id": "x", "dimension": "goal_alignment", "correct": True}]
        r = compute_radar(self.fw, answers)
        # 未作答维度应回落到 1 级（依赖期起点）
        self.assertEqual(r.radar["report_structure"], 1)

    def test_ascii_render(self):
        radar = {d.id: 3 for d in self.fw.dimensions}
        out = render_ascii_radar(self.fw, radar)
        for d in self.fw.dimensions:
            self.assertIn(d.name, out)
        self.assertIn("能力雷达", out)


if __name__ == "__main__":
    unittest.main()
