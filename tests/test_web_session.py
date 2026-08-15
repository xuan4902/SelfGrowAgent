"""Web 会话层测试（无 HTTP）：SessionManager 直测多轮 interrupt/恢复、取消、校验、并发上限。

内存有界：每次测试一个会话、:memory: DB、关掉 janitor。
与 test_graph_e2e 同断言口径：xp==100 / level==3 / 中断计数。
"""

from __future__ import annotations

import time
import unittest

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import ScriptedAnswerer
from selfgrow.agents.runtime import default_runtime
from selfgrow.storage.db import Database
from selfgrow.web.sessions import (
    AnswerValidationError,
    SessionLimitError,
    SessionManager,
)

GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


def make_manager(**kw) -> SessionManager:
    kw.setdefault(
        "runtime_factory", lambda: default_runtime(db=Database(path=":memory:"))
    )
    kw.setdefault("graph_factory", build_graph)
    kw.setdefault("janitor_interval", None)
    return SessionManager(**kw)


class TestWebSession(unittest.TestCase):
    @staticmethod
    def _answer_body(payload: dict) -> dict:
        """把 ScriptedAnswerer 的恢复值映射成 HTTP body（assessment 已是单题 {question_id, option}，其余用 value）。"""
        value = ScriptedAnswerer().answer(payload)
        if "assessment" in payload:
            return value
        return {"value": value}

    def _wait_waiting(self, s, timeout: float = 15.0):
        """轮询直到 waiting；done/error/cancelled 时返回 None（避免最后一次提交后的竞态）。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if s.status in ("done", "error", "cancelled"):
                return None
            if s.status == "waiting" and s.current_payload is not None:
                return s.current_payload
            time.sleep(0.02)
        raise TimeoutError("等待会话进入 waiting 超时")

    def _drive_to_done(self, s, timeout: float = 30.0) -> dict:
        while True:
            if s.status == "done":
                return s.final
            if s.status in ("error", "cancelled"):
                raise AssertionError(f"会话终止: {s.status}")
            payload = self._wait_waiting(s, timeout)
            if payload is None:
                continue  # 已 done，下轮循环返回
            s.submit_answer(self._answer_body(payload))

    def test_full_loop_via_web_session(self) -> None:
        """脚本化喂答案跑通全流程：中断计数、战报、线程正常结束。"""
        m = make_manager()
        s = m.create(GOAL)
        final = self._drive_to_done(s)

        self.assertEqual(s.status, "done")
        self.assertEqual(final["llm_mode"], "mock")
        self.assertEqual(final["xp"], 100)
        self.assertEqual(final["level"], 3)

        # 中断负载计数：基线+复测 assessment、每周 learn、spar、每周 review。
        # spar：第 1 周对线 2 回合；spar_transcript 跨周累积，第 2 周首回合即触发
        # 打完反馈 → 只中断 1 次（引擎现有行为，实录见 artifacts/demo_auto_run.txt「回合 3/2」）。
        counts: dict[str, int] = {}
        for ev in s.history:
            if ev["type"] == "interrupt":
                key = next(iter(ev["payload"]))
                counts[key] = counts.get(key, 0) + 1
        # 单题测评：基线 10 + 复测 3 = 13；learn/spar/review 每周各一次（spar 跨周累积 3 回合）
        self.assertEqual(counts.get("assessment"), 13)
        self.assertEqual(counts.get("learn"), 2)
        self.assertEqual(counts.get("spar"), 3)
        self.assertEqual(counts.get("review"), 2)

        # 战报结构
        r = final["report"]
        self.assertEqual(r["xp"], 100)
        self.assertEqual(r["level"], 3)
        self.assertTrue(r["improved"])
        self.assertIn("radar_before", r)
        self.assertIn("radar_after", r)
        self.assertEqual(r["tools_used"], sorted({t["name"] for t in final["tools_called"]}))

        # 事件序：最后一条是 done(done)；run 线程已结束
        self.assertEqual(s.history[-1]["type"], "done")
        self.assertEqual(s.history[-1]["status"], "done")
        s.thread.join(timeout=5)
        self.assertFalse(s.thread.is_alive())

    def test_cancel_releases_waiting_thread(self) -> None:
        """waiting 态取消：5s 内 status==cancelled、线程不活、末事件 done(cancelled)。"""
        m = make_manager()
        s = m.create(GOAL)
        self._wait_waiting(s)
        s.cancel()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and s.status != "cancelled":
            time.sleep(0.02)
        self.assertEqual(s.status, "cancelled")
        s.thread.join(timeout=5)
        self.assertFalse(s.thread.is_alive())
        self.assertEqual(s.history[-1]["type"], "done")
        self.assertEqual(s.history[-1]["status"], "cancelled")

    def test_invalid_answer_keeps_session_waiting(self) -> None:
        """非法答案不吞消息：仍 waiting、payload 不变；合法答案能继续推进。"""
        m = make_manager()
        s = m.create(GOAL)
        payload = self._wait_waiting(s)
        self.assertIn("assessment", payload)

        with self.assertRaises(AnswerValidationError):
            s.submit_answer({"question_id": "x", "option": 0})  # question_id 不匹配 → 400 语义
        self.assertEqual(s.status, "waiting")
        self.assertEqual(s.current_payload, payload)

        # 合法答案恢复流程
        s.submit_answer(self._answer_body(payload))
        self.assertNotEqual(s.status, "error")
        s.cancel()
        s.thread.join(timeout=5)  # 让 run 线程走完 finally（关闭 DB）

    def test_concurrency_limit(self) -> None:
        """max_sessions=2 时第三个会话创建抛 SessionLimitError。"""
        m = make_manager(max_sessions=2)
        s1 = m.create(GOAL)
        s2 = m.create(GOAL)
        with self.assertRaises(SessionLimitError):
            m.create(GOAL)
        s1.cancel()
        s2.cancel()
        s1.thread.join(timeout=5)
        s2.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
