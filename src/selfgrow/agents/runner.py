"""图执行驱动：处理 interrupt 暂停/恢复，把多轮交互与 CLI/自动演示解耦。

answerer 收到 interrupt payload，返回恢复值（用户作答/选择/回应/复盘文本）。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from langgraph.types import Command


class Answerer(Protocol):
    def answer(self, payload: dict[str, Any]) -> Any: ...


class ScriptedAnswerer:
    """自动演示用：按 payload 类型返回脚本化恢复值（确定性）。"""

    # 作答策略：指定维度答对，其余答错（造出清晰的薄弱点）
    STRONG_DIMS = {"goal_alignment", "report_structure"}

    def answer(self, payload: dict[str, Any]) -> Any:
        if "assessment" in payload:
            return self._assessment(payload["assessment"])
        if "learn" in payload:
            return "去演练"
        if "spar" in payload:
            return "结论先行：项目会延期约 3 天，影响上线里程碑。我建议砍掉非核心功能保交付，需要您确认优先级和加一名开发支持。"
        if "review" in payload:
            return "这次我发现关键问题在于我没提前同步风险；下周我会在风险出现时就预警，并带上补救方案。"
        return "好的，继续。"

    @staticmethod
    def _assessment(inner: dict[str, Any]) -> dict[str, Any]:
        # 复测：经过两周学习已掌握 → 全部答对；基线：指定维度答对，其余答错
        is_reassess = "复测" in (inner.get("stage_label") or "")
        answers = []
        for q in inner.get("questions", []):
            if is_reassess or q["dimension"] in ScriptedAnswerer.STRONG_DIMS:
                opt = q["correct"]
            else:
                opt = (q["correct"] + 1) % len(q["options"])
            answers.append({"question_id": q["id"], "option": opt})
        return {"answers": answers}


class InteractorAnswerer:
    """交互模式：把每个 interrupt 转发给用户回调，收集真实输入。"""

    def __init__(self, prompt: Callable[[dict[str, Any]], Any]):
        self._prompt = prompt

    def answer(self, payload: dict[str, Any]) -> Any:
        return self._prompt(payload)


def run_graph(
    graph: Any,
    initial_state: dict[str, Any],
    thread_id: str,
    answerer: Answerer,
) -> dict[str, Any]:
    """把图跑到完成（处理所有 interrupt），返回最终 state。"""
    config = {"configurable": {"thread_id": thread_id}}
    first = True
    payload: dict[str, Any] | None = None

    while True:
        if first:
            stream = graph.stream(initial_state, config=config)
            first = False
        else:
            stream = graph.stream(Command(resume=answerer.answer(payload)), config=config)
        for _ in stream:
            pass  # 推进到暂停点或结束

        snap = graph.get_state(config)
        if not snap.next:
            break
        # 取第一个中断负载（多中断并发场景取首个）
        pending = snap.tasks[0]
        payload = pending.interrupts[0].value

    return graph.get_state(config).values
