"""Web 会话层：把 LangGraph 多轮 interrupt 桥接到 HTTP/SSE。

关键设计（三个坑，必须遵守）：
1. **sqlite 跨线程**：`Database()` 默认 check_same_thread=True，runtime/graph 必须在
   会话 run 线程内构建（SessionManager 只持有 runtime_factory/graph_factory 工厂）。
2. **双答串位**：submit_answer 在 _submit_lock 内「先置 running 并清 current_payload
   再入 inbox」，否则并发第二个 POST 的值会被当作下一条答案消费。
3. **current_payload 竞态**：在 on_interrupt 回调里与 interrupt 事件同点赋值
   current_payload，保证事件到达时 payload 已就绪（而非放 QueueAnswerer）。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import run_graph
from selfgrow.agents.runtime import Runtime, default_runtime
from selfgrow.agents.state import new_initial_state

DEFAULT_GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"

# 会话状态机取值
_STARTING = "starting"
_RUNNING = "running"
_WAITING = "waiting"
_DONE = "done"
_CANCELLED = "cancelled"
_ERROR = "error"

# ---- 异常（app.py 映射为 HTTP 状态码） ----

class SessionNotFoundError(KeyError):
    """会话不存在 → 404。"""


class SessionLimitError(RuntimeError):
    """并发会话达上限 → 503。"""


class AnswerValidationError(ValueError):
    """答案不符合当前中断负载的契约 → 400。"""


class SessionBusyError(RuntimeError):
    """会话不在等待作答态（双答/已收下一条）→ 409。"""


class SessionCancelled(RuntimeError):
    """会话被取消，release run 线程。"""


# ---- 答案校验 ----

_LEARN_CHOICES = ("继续问", "去演练", "复盘")


def validate_answer(payload: dict[str, Any], body: dict[str, Any]) -> Any:
    """按当前中断负载类型校验并归一化恢复值。

    - assessment → {"answers": [{question_id, option(0基)}]}，须覆盖全部题、题集合全等
    - learn     → 字符串，必须 ∈ {继续问, 去演练, 复盘}
    - spar/review → 字符串（自由文本，可为空字符串）
    """
    if "assessment" in payload:
        inner = payload["assessment"]
        questions = inner.get("questions", [])
        qids = {q["id"] for q in questions}
        answers = body.get("answers")
        if not isinstance(answers, list) or not answers:
            raise AnswerValidationError("测评答案不能为空")
        got = {a["question_id"] for a in answers if isinstance(a, dict)}
        if got != qids:
            raise AnswerValidationError(
                f"测评答案须覆盖全部 {len(qids)} 题（缺失/多余/未知题目）"
            )
        normalized = []
        for a in answers:
            q = next((x for x in questions if x["id"] == a["question_id"]), None)
            opt = a.get("option")
            if not isinstance(opt, int) or isinstance(opt, bool) or not (0 <= opt < len(q["options"])):
                raise AnswerValidationError(f"题目 {a['question_id']} 选项越界（须 0..{len(q['options'])-1}）")
            normalized.append({"question_id": a["question_id"], "option": opt})
        return {"answers": normalized}
    if "learn" in payload:
        value = body.get("value")
        if value not in _LEARN_CHOICES:
            raise AnswerValidationError(f"学习动作为须其一：{'/'.join(_LEARN_CHOICES)}")
        return value
    if "spar" in payload or "review" in payload:
        value = body.get("value")
        if not isinstance(value, str):
            raise AnswerValidationError("演练/复盘需要一段自由文本")
        return value
    raise AnswerValidationError(f"无法识别的中断负载：{sorted(payload.keys())}")


# ---- SSE 事件 ----

def _sse(event: dict[str, Any]) -> str:
    """单帧 SSE：id + event + data(json, 不转义中文) + 空行。"""
    return (
        f"id: {event['id']}\n"
        f"event: {event['type']}\n"
        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    )


# ---- 会话 ----

@dataclass
class Session:
    """单个学习会话。run 线程跑图，inbox 收恢复值，events 出事件流。"""

    id: str
    goal: str
    learner_id: str
    status: str = _STARTING
    final: Optional[dict[str, Any]] = None
    current_payload: Optional[dict[str, Any]] = None
    waiting_since: float = 0.0
    created_at: float = 0.0

    inbox: "queue.Queue[Any]" = field(default_factory=queue.Queue)
    events: "queue.Queue[dict[str, Any]]" = field(default_factory=queue.Queue)
    history: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    done_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None

    _seq: int = 0
    _submit_lock: threading.Lock = field(default_factory=threading.Lock)
    _hist_lock: threading.Lock = field(default_factory=threading.Lock)
    _manager: Optional["SessionManager"] = None
    _llm_mode: str = "mock"

    def _emit(self, etype: str, **fields: Any) -> None:
        with self._hist_lock:
            self._seq += 1
            event = {"id": self._seq, "type": etype, **fields}
            self.history.append(event)
        self.events.put(event)

    # ---- run 线程 ----

    def _run(self) -> None:
        """在会话线程内构建 runtime/graph 并驱动 run_graph（sqlite 线程安全）。"""
        rt: Runtime | None = None
        try:
            rt = self._manager.runtime_factory() if self._manager else default_runtime()
            graph = self._manager.graph_factory(rt) if self._manager else build_graph(rt)
            self._llm_mode = getattr(rt.llm, "mode", "mock")
            init = new_initial_state(self.learner_id, self.goal)
            answerer = QueueAnswerer(self)

            def on_interrupt(payload: dict[str, Any]) -> None:
                # 关键：在事件入队的同时赋值 current_payload，杜绝竞态
                self.current_payload = payload
                self.status = _WAITING
                self.waiting_since = time.monotonic()
                self._emit("interrupt", payload=payload)

            def on_message(delta: list[dict[str, str]]) -> None:
                self._emit("message", delta=delta)

            final = run_graph(
                graph, init, thread_id=self.learner_id,
                answerer=answerer,
                on_interrupt=on_interrupt,
                on_message=on_message,
            )
            self.final = final
            self.status = _DONE
            self._emit("report", final=final)
        except SessionCancelled:
            self.status = _CANCELLED
        except Exception as exc:  # 图内错误 → 事件流报错，不让线程死
            self.status = _ERROR
            self._emit("error", message=str(exc))
        finally:
            self._emit("done", status=self.status)
            self.done_event.set()
            if rt is not None:
                try:
                    rt.db.close()
                except Exception:
                    pass

    # ---- HTTP 侧接口 ----

    def submit_answer(self, body: dict[str, Any]) -> None:
        """校验并投递一条答案。非 waiting 态抛 409；校验失败抛 400。"""
        with self._submit_lock:
            if self.status != _WAITING or self.current_payload is None:
                raise SessionBusyError("会话当前不在等待作答状态（可能已在处理上一条答案）")
            value = validate_answer(self.current_payload, body)
            # 先置 running + 清 payload，再入 inbox（防双答串位）
            self.status = _RUNNING
            self.current_payload = None
            self.inbox.put(value)

    def cancel(self) -> None:
        self.cancel_event.set()

    def state_dict(self) -> dict[str, Any]:
        with self._hist_lock:
            history = list(self.history)
        return {
            "session_id": self.id,
            "goal": self.goal,
            "status": self.status,
            "current_payload": self.current_payload,
            "history": history,
            "final": self.final,
            "llm_mode": self._llm_mode,
        }

    async def iterate(self, request: Any):
        """SSE 生成器：先重放 history（断线重连零丢失），再读 live 队列。

        - `id` 去重：重放与 live 之间的事件以 id 为界，不重复不遗漏
        - 空闲 >10s 发 `: keep-alive` 心跳（nginx/proxy 保活）
        - 客户端断开即退出；收到 done/error 后关闭
        """
        with self._hist_lock:
            snapshot = list(self.history)
        seen = {ev["id"] for ev in snapshot}
        for ev in snapshot:
            yield _sse(ev)
        last_beat = time.monotonic()
        try:
            while True:
                if self.done_event.is_set() and self.events.empty():
                    break
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    if await request.is_disconnected():
                        break
                    if time.monotonic() - last_beat >= 10:
                        yield ": keep-alive\n\n"
                        last_beat = time.monotonic()
                    await asyncio.sleep(0.05)
                    continue
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                last_beat = time.monotonic()
                yield _sse(ev)
                if ev["type"] in ("done", "error"):
                    break
        except asyncio.CancelledError:
            raise


class QueueAnswerer:
    """run_graph 的 Answerer：从会话 inbox 取恢复值；取消时抛异常释放线程。"""

    def __init__(self, session: Session):
        self._s = session

    def answer(self, payload: dict[str, Any]) -> Any:
        while not self._s.cancel_event.is_set():
            try:
                return self._s.inbox.get(timeout=0.5)
            except queue.Empty:
                continue
        raise SessionCancelled()


class SessionManager:
    """会话注册表 + 并发上限 + 后台清理。测试可注入内存工厂与关闭 janitor。"""

    def __init__(
        self,
        *,
        runtime_factory: Optional[Callable[[], Runtime]] = None,
        graph_factory: Optional[Callable[[Runtime], Any]] = None,
        max_sessions: int = 8,
        max_age: float = 3600.0,
        max_stored: int = 64,
        idle_timeout: float = 1800.0,
        janitor_interval: Optional[float] = 60.0,
    ):
        self.runtime_factory = runtime_factory or default_runtime
        self.graph_factory = graph_factory or build_graph
        self.max_sessions = max_sessions
        self.max_age = max_age
        self.max_stored = max_stored
        self.idle_timeout = idle_timeout
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        if janitor_interval:
            self._janitor_interval = janitor_interval
            threading.Thread(
                target=self._janitor, daemon=True, name="sga-janitor"
            ).start()

    # ---- CRUD ----

    def create(self, goal: str) -> Session:
        with self._lock:
            self._evict_locked()
            active = sum(
                1 for s in self._sessions.values()
                if s.status in (_STARTING, _RUNNING, _WAITING)
            )
            if active >= self.max_sessions:
                raise SessionLimitError(f"并发会话已达上限 {self.max_sessions}")
            sid = uuid.uuid4().hex[:12]
            now = time.monotonic()
            s = Session(id=sid, goal=goal or DEFAULT_GOAL, learner_id=sid,
                        created_at=now, waiting_since=now)
            self._sessions[sid] = s
            s._manager = self
        s.thread = threading.Thread(target=s._run, name=f"sga-session-{sid}", daemon=True)
        s.thread.start()
        return s

    def get(self, sid: str) -> Session:
        s = self._sessions.get(sid)
        if s is None:
            raise SessionNotFoundError(sid)
        return s

    def cancel(self, sid: str) -> bool:
        self.get(sid).cancel()
        return True

    # ---- 清理 ----

    def _evict_locked(self) -> None:
        now = time.monotonic()
        stale = [
            sid for sid, s in self._sessions.items()
            if s.status == _DONE and now - s.created_at > self.max_age
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
        if len(self._sessions) > self.max_stored:
            # 超量时优先淘汰最老的已结束会话
            done = sorted(
                (s for s in self._sessions.values() if s.status == _DONE),
                key=lambda s: s.created_at,
            )
            for s in done[: len(self._sessions) - self.max_stored]:
                self._sessions.pop(s.id, None)

    def _janitor(self) -> None:
        while True:
            time.sleep(self._janitor_interval)
            with self._lock:
                now = time.monotonic()
                for sid, s in list(self._sessions.items()):
                    if s.status == _WAITING and now - s.waiting_since > self.idle_timeout:
                        s.cancel_event.set()  # 闲置超时 → 强制取消
                    if s.status in (_DONE, _CANCELLED, _ERROR) and \
                            now - s.created_at > self.max_age:
                        self._sessions.pop(sid, None)
