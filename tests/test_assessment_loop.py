"""逐题自适应测评循环测试：单题 interrupt、答错→同维更难题追问、复测聚焦薄弱维度。

核心断言（Mock 确定性）：
- 基线 = 6 核心 + 至多 4 追问 = 10 题；复测 = gaps[:3] = 3 题；总计 13 个测评 interrupt。
- 每个 interrupt 只带一道题（payload 顶层仅 "assessment"），含 hud。
- 答错维度 ⇒ 下一题同维度、难度 +1、kind == "probe"。
- 复测只测薄弱维度，不再重复基线全量。
"""

from __future__ import annotations

import unittest

from langgraph.types import Command

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runtime import default_runtime
from selfgrow.agents.state import new_initial_state
from selfgrow.storage.db import Database

GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


class TestAssessmentLoop(unittest.TestCase):
    def _run(self, answerer) -> tuple[dict, list[dict]]:
        """驱动图跑到底，返回 (最终 state, 全部 interrupt 负载列表)。"""
        db = Database(path=":memory:")
        rt = default_runtime(db=db)
        graph = build_graph(runtime=rt)
        config = {"configurable": {"thread_id": "loop_01"}}
        init = new_initial_state("loop_01", GOAL)
        interrupts: list[dict] = []
        first = True
        while True:
            if first:
                stream = graph.stream(init, config=config)
                first = False
            else:
                stream = graph.stream(Command(resume=answerer(interrupts[-1])), config=config)
            for _ in stream:
                pass
            snap = graph.get_state(config)
            if not snap.next:
                return snap.values, interrupts
            interrupts.append(snap.tasks[0].interrupts[0].value)

    # ---- 作答器：assess 用自定义策略，learn/spar/review 固定脚本（保证图跑到底） ----

    @staticmethod
    def _make_answerer(assess_fn) -> callable:
        def answer(payload: dict) -> object:
            if "assessment" in payload:
                return assess_fn(payload["assessment"])
            if "learn" in payload:
                return "去演练"
            if "spar" in payload:
                return "结论先行：需要确认优先级，建议砍非核心功能保交付。"
            if "review" in payload:
                return "复盘：提前同步风险并带上方案。"
            return "好的，继续。"
        return answer

    @staticmethod
    def _script_assess(inner: dict) -> dict:
        """ScriptedAnswerer 同款：复测/强维度答对，其余答错（造出清晰薄弱点）。"""
        q = inner["question"]
        if "复测" in (inner.get("stage_label") or "") or q["dimension"] in ("goal_alignment", "report_structure"):
            opt = q["correct"]
        else:
            opt = (q["correct"] + 1) % len(q["options"])
        return {"question_id": q["id"], "option": opt}

    @staticmethod
    def _stage_interrupts(interrupts: list[dict], stage: str) -> list[dict]:
        """只挑指定测评阶段（基线测评/复测）的 interrupt 负载。"""
        return [p for p in interrupts
                if (p.get("assessment") or {}).get("stage_label") == stage]

    # ---- 测试 ----

    def test_baseline_ten_single_question_interrupts(self) -> None:
        final, interrupts = self._run(self._make_answerer(self._script_assess))

        base = self._stage_interrupts(interrupts, "基线测评")
        self.assertEqual(len(base), 10, "基线应为 6 核心 + 4 追问 = 10 题")

        # 单题契约：顶层只有 assessment；每道题含 question/hud/旁白
        for p in base:
            self.assertEqual(set(p.keys()), {"assessment"})
            inner = p["assessment"]
            self.assertIn("question", inner)
            self.assertIn("hud", inner)
            self.assertIn("narration", inner)
            self.assertIn("index", inner)
            self.assertIn("total", inner)

        # 测评 interrupt 总数为 13（基线 10 + 复测 3）；复测阶段答案含评分字段
        assessment = sum(1 for p in interrupts if "assessment" in p)
        self.assertEqual(assessment, 13)
        reassess = self._stage_interrupts(interrupts, "复测")
        first = reassess[0]["assessment"]["question"]
        self.assertTrue({"id", "dimension", "difficulty", "options", "correct"} <= set(first), set(first))

    def test_wrong_answer_triggers_same_dim_harder_probe(self) -> None:
        """只答错 expectation_management ⇒ 基线 7 题：核心 + 同维度难度 +1 的追问（kind=probe）。"""
        captured: list[dict] = []

        def assess(inner: dict) -> dict:
            q = inner["question"]
            captured.append({**dict(q), "stage": inner.get("stage_label")})
            if q["dimension"] == "expectation_management":
                return {"question_id": q["id"], "option": (q["correct"] + 1) % len(q["options"])}
            return {"question_id": q["id"], "option": q["correct"]}

        _, interrupts = self._run(self._make_answerer(assess))

        # 基线：6 核心 + 1 追问（仅答错维度）
        base = self._stage_interrupts(interrupts, "基线测评")
        self.assertEqual(len(base), 7, "只答错 1 维 → 6 核心 + 1 追问")

        exp_base = [c for c in captured
                    if c["dimension"] == "expectation_management" and c["stage"] == "基线测评"]
        self.assertEqual(len(exp_base), 2, "基线该维度应核心 1 题 + 追问 1 题")
        self.assertTrue(
            any(c.get("kind") == "probe" and c.get("difficulty", 1) >= 2 for c in exp_base),
            "追问应是同维度更难题（difficulty>=2, kind=probe）",
        )

    def test_reassess_three_focuses_on_gaps(self) -> None:
        """复测全对 → 恰 3 题，且只覆盖薄弱维度（难度>=2）。"""
        final, interrupts = self._run(self._make_answerer(self._script_assess))

        reassess = self._stage_interrupts(interrupts, "复测")
        self.assertEqual(len(reassess), 3, "复测 = gaps[:3]，全对无追问")
        dims = {p["assessment"]["question"]["dimension"] for p in reassess}
        self.assertTrue(dims <= set(final["gaps"]), f"复测维度 {dims} 应 ∈ 薄弱维度 {final['gaps']}")
        self.assertTrue(
            all(p["assessment"]["question"].get("difficulty", 1) >= 2 for p in reassess),
            "复测题目难度应 >=2",
        )
        # 复测后所有复测维度提升到 5
        for d in dims:
            self.assertEqual(final["radar"][d], 5)

    def test_total_interrupts_and_assessment_count(self) -> None:
        """全流程：20 个中断，其中 13 个测评（基线 10 + 复测 3）。"""
        _, interrupts = self._run(self._make_answerer(self._script_assess))
        self.assertEqual(len(interrupts), 20)
        assessment = sum(1 for p in interrupts if "assessment" in p)
        self.assertEqual(assessment, 13)


if __name__ == "__main__":
    unittest.main()
