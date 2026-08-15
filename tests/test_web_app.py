"""Web 应用层测试：TestClient 端到端（建会话 → SSE 推流 → POST 答案 → 战报/done）+ 错误码。

约定：每个测试一个内存会话；SSE 断流重连靠后端重放 history + id 去重（本测试验证报告/done 可重放）。
"""

from __future__ import annotations

import json
import threading
import time
import unittest

from fastapi.testclient import TestClient

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import ScriptedAnswerer
from selfgrow.agents.runtime import default_runtime
from selfgrow.storage.db import Database
from selfgrow.web.app import create_app
from selfgrow.web.sessions import SessionManager


def make_app() -> TestClient:
    manager = SessionManager(
        runtime_factory=lambda: default_runtime(db=Database(path=":memory:")),
        graph_factory=build_graph,
        janitor_interval=None,
    )
    return create_app(manager)


def answer_body(payload: dict) -> dict:
    value = ScriptedAnswerer().answer(payload)
    if "assessment" in payload:
        return value  # 单题 {question_id, option}
    return {"value": value}


class TestWebApp(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(make_app())

    def _create(self, goal: str = "我想提升汇报能力") -> str:
        r = self.client.post("/api/sessions", json={"goal": goal})
        self.assertEqual(r.status_code, 201)
        return r.json()["session_id"]

    def _stream_until(self, path: str, types: set[str], timeout: float = 20.0) -> list[dict]:
        """读 SSE 流直到出现指定类型事件（返回全部已收到事件）；timeout 防挂死。"""
        events: list[dict] = []
        deadline = time.monotonic() + timeout
        with self.client.stream("GET", path) as resp:
            self.assertEqual(resp.status_code, 200)
            for line in resp.iter_lines():
                if time.monotonic() > deadline:
                    raise TimeoutError("SSE stream timeout")
                if not line:
                    continue
                if line.startswith("data:"):
                    ev = json.loads(line[5:].strip())
                    events.append(ev)
                    if ev["type"] in types:
                        return events
        return events

    def _drive_to_done(self, sid: str, timeout: float = 40.0) -> dict:
        """轮询 /state + POST /answer，直到会话 done，返回 final state。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.client.get(f"/api/sessions/{sid}").json()
            if st["status"] == "done":
                return st["final"]
            if st["status"] in ("error", "cancelled"):
                self.fail(f"会话终止: {st['status']}")
            if st["status"] == "waiting" and st["current_payload"]:
                rr = self.client.post(f"/api/sessions/{sid}/answer", json=answer_body(st["current_payload"]))
                self.assertEqual(rr.status_code, 200)
            time.sleep(0.02)
        self.fail("会话应在超时前完成")

    # ---- 主链路 ----

    def test_sse_end_to_end(self) -> None:
        sid = self._create()

        # 首次开流放后台线程：本环境 TestClient 的 stream() 会阻塞到响应体结束，
        # 因此「边读边答」必须在后台读、主线程驱动（run 线程独立消费答案，无死锁）。
        collected: list[dict] = []

        def read_live_stream() -> None:
            with self.client.stream("GET", f"/api/sessions/{sid}/events") as resp:
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    collected.append(json.loads(line[5:].strip()))

        reader = threading.Thread(target=read_live_stream, daemon=True)
        reader.start()

        # 主线程经 /state + POST /answer 驱动到 done（run 线程实时往 SSE 流推事件）
        final = self._drive_to_done(sid)
        self.assertEqual(final["xp"], 100)
        self.assertEqual(final["level"], 3)

        reader.join(timeout=20)
        self.assertFalse(reader.is_alive(), "SSE 流应在会话 done 后关闭")
        self.assertTrue(collected, "后台应实时收到事件")
        # 事件序：首个 interrupt（assessment 推流）→ … → report → done
        types = [e["type"] for e in collected]
        self.assertEqual(types[0], "interrupt")
        self.assertIn("assessment", collected[0]["payload"])
        self.assertIn("report", types)
        self.assertEqual(types[-1], "done")
        self.assertEqual(collected[-1]["status"], "done")
        # id 单调递增、无重复（服务端自增 seq）
        ids = [e["id"] for e in collected]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))

        # 再开流：断线重连重放历史（report + done 可重放，id 去重不重复）
        events = self._stream_until(f"/api/sessions/{sid}/events", {"done"})
        types2 = [e["type"] for e in events]
        self.assertIn("report", types2)
        self.assertEqual(types2[-1], "done")
        self.assertEqual(events[-1]["status"], "done")

    def test_meta(self) -> None:
        r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["domain"], "managing_up")
        self.assertEqual(len(data["dimensions"]), 6)
        self.assertIn("llm_mode", data)
        dim0 = data["dimensions"][0]
        self.assertIn("id", dim0)
        self.assertIn("name", dim0)

    # ---- 错误码 ----

    def test_invalid_answer_returns_400(self) -> None:
        sid = self._create()
        deadline = time.monotonic() + 15.0
        payload = None
        while time.monotonic() < deadline:
            st = self.client.get(f"/api/sessions/{sid}").json()
            if st["status"] == "waiting" and st["current_payload"]:
                payload = st["current_payload"]
                break
            time.sleep(0.02)
        self.assertIn("assessment", payload)

        rr = self.client.post(f"/api/sessions/{sid}/answer", json={"question_id": "x", "option": 0})
        self.assertEqual(rr.status_code, 400)
        # 会话仍在等待、payload 未变
        st = self.client.get(f"/api/sessions/{sid}").json()
        self.assertEqual(st["status"], "waiting")
        self.assertEqual(st["current_payload"], payload)
        self.client.post(f"/api/sessions/{sid}/cancel")

    def test_answer_after_done_returns_409(self) -> None:
        sid = self._create()
        self._drive_to_done(sid)
        rr = self.client.post(f"/api/sessions/{sid}/answer", json={"value": "x"})
        self.assertEqual(rr.status_code, 409)

    def test_unknown_session_404(self) -> None:
        self.assertEqual(self.client.get("/api/sessions/nope").status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/nope/answer", json={}).status_code, 404)
        self.assertEqual(self.client.post("/api/sessions/nope/cancel").status_code, 404)

    def test_cancel_via_http(self) -> None:
        sid = self._create()
        # 等 waiting
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            st = self.client.get(f"/api/sessions/{sid}").json()
            if st["status"] == "waiting" and st["current_payload"]:
                break
            time.sleep(0.02)
        rr = self.client.post(f"/api/sessions/{sid}/cancel")
        self.assertEqual(rr.status_code, 200)

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            st = self.client.get(f"/api/sessions/{sid}").json()
            if st["status"] == "cancelled":
                break
            time.sleep(0.02)
        self.assertEqual(st["status"], "cancelled")
        events = self._stream_until(f"/api/sessions/{sid}/events", {"done"}, timeout=10.0)
        self.assertEqual(events[-1]["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
