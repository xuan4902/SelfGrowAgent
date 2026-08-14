"""SQLite 存储与仓库测试（内存库）。"""

import unittest

from selfgrow.storage.db import Database
from selfgrow.storage.repos import (
    get_learner,
    get_plan,
    save_assessment,
    save_learner,
    save_plan,
    save_review,
    save_spar_session,
    update_learner_progress,
)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.db = Database(path=":memory:")

    def tearDown(self):
        self.db.close()

    def test_learner_crud(self):
        save_learner(self.db, "u1", goal="提升向上管理", xp=0, level=1)
        row = get_learner(self.db, "u1")
        self.assertEqual(row["goal"], "提升向上管理")
        update_learner_progress(self.db, "u1", xp=200, level=2)
        self.assertEqual(get_learner(self.db, "u1")["xp"], 200)

    def test_assessment_roundtrip(self):
        radar = {"goal_alignment": 4, "report_structure": 2}
        gaps = ["report_structure"]
        save_assessment(self.db, "u1", "baseline", radar, gaps)
        rows = self.db.fetch_all("SELECT * FROM assessments WHERE learner_id='u1'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.db.loads(rows[0]["radar_json"]), radar)

    def test_plan_roundtrip(self):
        plan = {"weeks": [{"week": 1, "dimension": "report_structure"}], "current_week": 0}
        save_plan(self.db, "u1", plan)
        row = get_plan(self.db, "u1")
        self.assertEqual(row["plan"]["weeks"][0]["dimension"], "report_structure")

    def test_spar_and_review(self):
        save_spar_session(self.db, "u1", 1, "sp_report_01", [{"role": "npc", "content": "hi"}],
                          {"overall_level": 3})
        save_review(self.db, "u1", 1, {"keep": ["a"], "problem": ["b"], "try": ["c"]})
        spar = self.db.fetch_one("SELECT * FROM spar_sessions WHERE learner_id='u1'")
        self.assertEqual(spar["scenario_id"], "sp_report_01")
        review = self.db.fetch_one("SELECT * FROM reviews WHERE learner_id='u1'")
        self.assertEqual(self.db.loads(review["kolb_json"])["try"], ["c"])

    def test_schema_tables_exist(self):
        tables = {r["name"] for r in self.db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"learners", "assessments", "plans", "learning_records",
                    "spar_sessions", "reviews", "knowledge_docs"}
        self.assertTrue(expected <= tables)


if __name__ == "__main__":
    unittest.main()
