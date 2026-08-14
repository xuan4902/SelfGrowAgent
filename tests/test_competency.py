"""能力框架加载与结构校验测试。"""

import unittest

from selfgrow.competency.loader import (
    FrameworkNotFoundError,
    FrameworkValidationError,
    load_framework,
)


class TestCompetencyFramework(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fw = load_framework("managing_up")

    def test_load_dimensions(self):
        self.assertEqual(len(self.fw.dimensions), 6)
        expected_ids = [
            "goal_alignment",
            "report_structure",
            "expectation_management",
            "resource_acquisition",
            "upward_communication",
            "handling_feedback",
        ]
        self.assertEqual(self.fw.dimension_ids(), expected_ids)

    def test_each_dimension_has_5_levels(self):
        for d in self.fw.dimensions:
            self.assertEqual(len(d.levels), 5, f"维度 {d.id} 应有 5 级")
            self.assertEqual([lv.level for lv in d.levels], [1, 2, 3, 4, 5])

    def test_rubric_weights_sum_to_one(self):
        for d in self.fw.dimensions:
            self.assertAlmostEqual(d.rubric_weight_sum(), 1.0, places=4, msg=f"{d.id} rubric 权重")

    def test_improvement_path(self):
        dim = self.fw.get_dimension("report_structure")
        self.assertIn("结论先行", dim.improvement_path(1))

    def test_validate_passes(self):
        self.assertEqual(self.fw.validate(), [])

    def test_missing_framework_raises(self):
        with self.assertRaises(FrameworkNotFoundError):
            load_framework("no_such_domain")

    def test_invalid_framework_rejected(self):
        # 构造一个缺维度/缺级别的假框架，校验应报错
        bad = self.fw.to_dict()
        bad["dimensions"][0]["levels"] = bad["dimensions"][0]["levels"][:3]
        import json
        from selfgrow.competency.models import CompetencyFramework

        fw2 = CompetencyFramework.from_dict(bad)
        self.assertTrue(fw2.validate())


if __name__ == "__main__":
    unittest.main()
