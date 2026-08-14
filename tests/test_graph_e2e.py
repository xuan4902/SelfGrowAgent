"""LangGraph 端到端测试：mock 模式下全链路闭环（诊断→规划→学习→演练→复盘→复测→毕业）。

评审证据覆盖：任务理解(目标拆解)、计划生成、多轮交互(中断/恢复)、工具调用、RAG、上下文记忆(断点续学/落库)、结果验证(前后雷达对比)。
"""

from __future__ import annotations

import unittest

from langgraph.types import Command

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import ScriptedAnswerer, run_graph
from selfgrow.agents.runtime import default_runtime
from selfgrow.agents.state import new_initial_state
from selfgrow.competency.models import CompetencyFramework
from selfgrow.storage.db import Database
from selfgrow.storage.repos import get_assessments, get_learner, get_plan

LEARNER_ID = "e2e_01"
GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


def _build() -> tuple[Database, object, dict[str, object]]:
    db = Database(path=":memory:")
    rt = default_runtime(db=db)
    graph = build_graph(runtime=rt)
    init = new_initial_state(LEARNER_ID, GOAL)
    final = run_graph(graph, init, thread_id=LEARNER_ID, answerer=ScriptedAnswerer())
    return db, graph, final


class TestGraphE2E(unittest.TestCase):
    def test_full_loop_mock_completes_and_reports(self) -> None:
        db, graph, final = _build()
        framework: CompetencyFramework = default_runtime(db=db).framework

        # 1) 流程完整：复测完成、周数跑满
        self.assertTrue(final["reassess_done"])
        self.assertEqual(final["current_week"], final["plan"]["total_weeks"])
        self.assertEqual(final["llm_mode"], "mock")

        # 2) 任务理解：目标被拆解成子能力
        breakdown = final["goal_breakdown"]
        self.assertTrue(breakdown["sub_goals"])
        self.assertEqual(breakdown["domain_name"], framework.name)

        # 3) 计划生成：每周含维度/目标/语料/场景
        plan = final["plan"]
        self.assertEqual(plan["total_weeks"], 2)
        for w in plan["weeks"]:
            self.assertIn("dimension", w)
            self.assertTrue(w["topic"])
            self.assertTrue(w["goal"])
            self.assertTrue(w["scenario_id"])
            self.assertTrue(w["knowledge_query"])

        # 4) 结果验证：基线 vs 最终雷达 → 明确成长
        before = final["radar_before"]
        after = final["radar"]
        self.assertEqual(before["goal_alignment"], 5)
        self.assertEqual(before["report_structure"], 5)
        improved = final["report"]["improved"]
        self.assertTrue(improved, "复测后应有至少一项能力提升")
        for dim_id in framework.dimension_ids():
            if framework.get_dimension(dim_id).name in improved:
                self.assertGreater(after[dim_id], before[dim_id])

        # 5) 演练反馈结构完整
        feedback = final["spar_feedback"]
        self.assertIn("scores", feedback)
        self.assertIn("overall_level", feedback)
        self.assertIn("mistakes", feedback)
        self.assertIn("suggestions", feedback)
        self.assertIn("narrative", feedback)
        self.assertGreaterEqual(feedback["overall_level"], 1)

        # 6) 战报结构完整
        report = final["report"]
        self.assertIn("xp", report)
        self.assertIn("level", report)
        self.assertIn("radar_before", report)
        self.assertIn("radar_after", report)
        self.assertGreater(report["xp"], 0)

        # 7) 工具调用日志：五类关键工具全触发
        tool_names = {t["name"] for t in final["tools_called"]}
        for expect in ("generate_assessment", "search_knowledge", "get_scenario", "save_record", "build_mindmap"):
            self.assertIn(expect, tool_names)

        # 8) 上下文记忆：五角色消息 + 关系型落库完整
        roles = {m["role"] for m in final["messages"]}
        self.assertTrue({"diagnose", "plan", "learn", "spar", "review"} <= roles)
        learner = get_learner(db, LEARNER_ID)
        self.assertEqual(learner["xp"], 100)
        self.assertEqual(learner["level"], 3)
        kinds = [a["kind"] for a in get_assessments(db, LEARNER_ID)]
        self.assertEqual(sorted(kinds), ["baseline", "reassess"])
        saved_plan = get_plan(db, LEARNER_ID)["plan"]
        self.assertEqual(saved_plan["total_weeks"], 2)
        sessions = db.fetch_all("SELECT * FROM spar_sessions WHERE learner_id=?", (LEARNER_ID,))
        self.assertEqual(len(sessions), 2, "两周演练各落一次 spar_session")
        self.assertEqual(len(db.fetch_all("SELECT * FROM reviews WHERE learner_id=?", (LEARNER_ID,))), 2)
        self.assertEqual(len(db.fetch_all("SELECT * FROM learning_records WHERE learner_id=?", (LEARNER_ID,))), 2)

    def test_resume_after_interrupt_preserves_context(self) -> None:
        """断点续学：第一次 interrupt 后 partial state 已落盘，恢复值驱动后续流程。"""
        db = Database(path=":memory:")
        rt = default_runtime(db=db)
        graph = build_graph(runtime=rt)
        config = {"configurable": {"thread_id": "resume_01"}}
        init = new_initial_state("resume_01", "提升汇报能力")
        answerer = ScriptedAnswerer()

        # 首次推进 → 停在测评 interrupt
        for _ in graph.stream(init, config):
            pass
        snap = graph.get_state(config)
        self.assertTrue(snap.next, "图应停在第一个中断点")
        payload = snap.tasks[0].interrupts[0].value
        self.assertIn("assessment", payload)
        # 中断点可读到的是 interrupt 负载与既有会话上下文（含初始 goal）
        self.assertEqual(snap.values["goal"], "提升汇报能力")
        self.assertEqual(snap.values["learner_id"], "resume_01")

        # 逐个恢复直到结束（验证多轮恢复链路）
        for _ in range(20):
            if not snap.next:
                break
            resume_val = answerer.answer(snap.tasks[0].interrupts[0].value)
            for _ in graph.stream(Command(resume=resume_val), config):
                pass
            snap = graph.get_state(config)
        self.assertFalse(snap.next, "所有中断恢复后图应到达 END")
        final = snap.values
        self.assertTrue(final["reassess_done"])
        self.assertGreater(len(final["messages"]), 10)
        # 断点续学语义：thread_id 复用时同一会话上下文延续
        self.assertEqual(final["goal"], "提升汇报能力")

    def test_dynamic_adjustment_reorders_remaining_week(self) -> None:
        """复测后制图师应重排剩余关卡，指向新暴露的薄弱维度。"""
        db, _, final = _build()
        plan = final["plan"]
        # 第 1 周学「管理期待」，复测暴露「应对反馈」仍弱 → 剩余 1 关重排为应对反馈
        dims = [w["dimension"] for w in plan["weeks"]]
        self.assertEqual(dims[0], "expectation_management")
        self.assertEqual(dims[1], "handling_feedback")
        self.assertIn("handling_feedback", final["gaps"])


if __name__ == "__main__":
    unittest.main()
