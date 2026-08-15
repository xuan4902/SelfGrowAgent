"""动态场景引擎测试：场景生成留痕/字段齐全/确定性、跨维度重新生成、周内跨回合复用。

核心断言（Mock 确定性）：
- generate_scenario 走 call_tool 留痕，返回含 boss 人设/环境/压力/利害/开场白的完整场景。
- 同维度同输出；异维度异场景；pick_scenario 深拷贝不污染缓存。
- 全流程：W1(expectation_management)、W2(handling_feedback) 维度不同 ⇒ 每周现场生成 1 次；
  周内两回合复用同一场景 ⇒ generate_scenario 共调用 2 次、场景标题 W1/W2 各一。
"""

from __future__ import annotations

import unittest

from selfgrow.agents.bank import pick_scenario
from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import ScriptedAnswerer, run_graph
from selfgrow.agents.runtime import default_runtime
from selfgrow.agents.state import new_initial_state
from selfgrow.agents.tools import call_tool, generate_scenario
from selfgrow.storage.db import Database

GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


class TestSparScene(unittest.TestCase):
    def test_generate_scenario_trace_and_fields(self) -> None:
        db = Database(path=":memory:")
        rt = default_runtime(db=db)
        log: list[dict] = []
        s = call_tool(
            log, "generate_scenario", generate_scenario,
            llm=rt.llm, role_prompt="sys",
            dimension="expectation_management", difficulty_hint=1,
            domain=rt.domain, goal=GOAL,
            user_profile={"weakest": "handling_feedback"},
        )
        self.assertEqual(log[0]["name"], "generate_scenario")  # 工具调用留痕（评审证据）
        self.assertEqual(s["dimension"], "expectation_management")
        for k in ("title", "goal", "environment", "pressure", "stakes", "npc"):
            self.assertIn(k, s, f"场景缺字段 {k}")
        self.assertIn("level", s["pressure"])
        self.assertIn("desc", s["pressure"])
        self.assertTrue(s["npc"].get("opening"))
        self.assertTrue(s["npc"].get("mock_lines"))

    def test_scenario_deterministic_same_dim(self) -> None:
        db = Database(path=":memory:")
        rt = default_runtime(db=db)
        a = generate_scenario(rt.llm, "sys", dimension="report_structure",
                              difficulty_hint=1, domain=rt.domain)
        b = generate_scenario(rt.llm, "sys", dimension="report_structure",
                              difficulty_hint=1, domain=rt.domain)
        self.assertEqual(a["id"], b["id"], "同维度同输出（确定性）")
        c = generate_scenario(rt.llm, "sys", dimension="handling_feedback",
                              difficulty_hint=1, domain=rt.domain)
        self.assertNotEqual(a["id"], c["id"], "异维度应生成不同场景")

    def test_pick_scenario_deep_copy_isolation(self) -> None:
        s1 = pick_scenario("managing_up", "goal_alignment")
        s2 = pick_scenario("managing_up", "goal_alignment")
        s1["npc"]["opening"] = "被污染了"
        self.assertNotEqual(s2["npc"]["opening"], "被污染了", "返回深拷贝，不污染缓存")

    def test_spar_full_flow_generation_and_reuse(self) -> None:
        """W1/W2 维度不同 → 各生成 1 次；周内两回合复用同一场景（共 2 次留痕）。"""
        db = Database(path=":memory:")
        rt = default_runtime(db=db)
        graph = build_graph(runtime=rt)
        init = new_initial_state("scene_01", GOAL)
        spars: list[dict] = []

        def hook(payload: dict) -> None:
            if "spar" in payload:
                spars.append(payload["spar"])

        final = run_graph(graph, init, thread_id="scene_01",
                          answerer=ScriptedAnswerer(), on_interrupt=hook)

        # BOSS HUD 字段齐全
        for s in spars:
            self.assertTrue(s["scene_title"])
            self.assertIn("environment", s)
            self.assertIn("stakes", s)
            self.assertTrue(s["boss"]["name"])
            self.assertTrue(s["boss"]["role"])
            self.assertIn("pressure_now", s)
            self.assertLessEqual(s["pressure_now"], 5)
            self.assertIn("npc_line", s)

        # 3 个对线 interrupt：W1 两回合 + W2 一回合（spar_transcript 跨周累积）
        self.assertEqual(len(spars), 3)
        titles = [s["scene_title"] for s in spars]
        self.assertEqual(len(set(titles)), 2, "W1/W2 应各一个专属场景（维度不同重新生成）")

        # 场景生成留痕：周内两回合复用（维度一致不重生成），跨周各生成 1 次 → 共 2 次
        names = [t["name"] for t in final["tools_called"]]
        self.assertEqual(names.count("generate_scenario"), 2)


if __name__ == "__main__":
    unittest.main()
