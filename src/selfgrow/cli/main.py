"""CLI 入口：自驱成长 Agent 演示与交互。

用法：
  python -m selfgrow.cli.main --mode auto           # 自动演示（录视频用，脚本作答）
  python -m selfgrow.cli.main --mode interactive     # 真人交互（实时扮演学习者）
  python -m selfgrow.cli.main --mode voice           # 语音对话（ASR 输入 + TTS 朗读）
  python -m selfgrow.cli.main --mode voice --tts off # 只听/说，不朗读（纯语音输入）
  python -m selfgrow.cli.main --mode auto --goal "我想提升汇报能力" --learner lx_01
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from selfgrow.agents.graph import build_graph
from selfgrow.agents.runner import InteractorAnswerer, ScriptedAnswerer, run_graph
from selfgrow.agents.runtime import default_runtime
from selfgrow.agents.state import new_initial_state
from selfgrow.cli.render import prompt_for, render_battle_report, render_payload
from selfgrow.competency.loader import load_framework
from selfgrow.storage.db import Database
from selfgrow.paths import DB_PATH, ensure_data_dirs
from selfgrow.voice.asr import WhisperASR
from selfgrow.voice.mic import SounddeviceMic
from selfgrow.voice.session import VoiceSession
from selfgrow.voice.tts import AutoTTS, NullTTS

DEFAULT_GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SelfGrowAgent · 自驱成长 Agent（向上管理）")
    p.add_argument("--mode", choices=["auto", "interactive", "voice"], default="auto",
                   help="auto=自动演示；interactive=真人交互；voice=语音对话")
    p.add_argument("--goal", default=DEFAULT_GOAL, help="学员原始诉求（voice 模式作兜底默认）")
    p.add_argument("--learner", default="learner_01", help="学员 ID（也用作续学 thread_id）")
    p.add_argument("--db", default=None, help="SQLite 路径（默认 data/selfgrow.db，:memory: 用内存库）")
    p.add_argument("--tts", choices=["on", "off"], default="on",
                   help="voice 模式是否朗读（off=纯语音输入，界面静音）")
    return p.parse_args()


def _build(args: argparse.Namespace) -> tuple[Any, Any, dict[str, Any], Any]:
    db_path = args.db if args.db is not None else str(DB_PATH)
    db = Database(path=":memory:" if db_path == ":memory:" else db_path)
    rt = default_runtime(db=db)
    framework = rt.framework
    graph = build_graph(runtime=rt)
    init = new_initial_state(args.learner, args.goal)
    return graph, rt, init, framework


def _run_auto(args: argparse.Namespace) -> dict[str, Any]:
    graph, rt, init, framework = _build(args)
    print(f"🤖 运行模式：auto  ·  模型：{rt.llm.mode}  ·  学员：{args.learner}")
    print(f"🎯 诉求：{args.goal}\n")

    def tour(payload: dict[str, Any]) -> None:
        render_payload(payload)

    final = run_graph(
        graph, init,
        thread_id=args.learner,
        answerer=ScriptedAnswerer(),
        on_interrupt=tour,
    )
    render_battle_report(final, framework)
    return final


def _run_interactive(args: argparse.Namespace) -> dict[str, Any]:
    graph, rt, init, framework = _build(args)
    print(f"🤖 运行模式：interactive  ·  模型：{rt.llm.mode}  ·  学员：{args.learner}\n")
    print("🧭 你将扮演学习者：作答测评 → 选择学习动作 → 与 NPC 对线 → 复盘反思。")
    print("   输入 q 可随时退出。\n")

    answerer = InteractorAnswerer(lambda payload: prompt_for(payload, framework))
    try:
        final = run_graph(graph, init, thread_id=args.learner, answerer=answerer)
    except KeyboardInterrupt:
        print("\n👋 已退出。数据已按当前进度保存，重跑可续学。")
        return {}
    render_battle_report(final, framework)
    return final


def _build_voice_session(args: argparse.Namespace) -> VoiceSession:
    tts = NullTTS() if args.tts == "off" else AutoTTS()
    return VoiceSession(SounddeviceMic(), WhisperASR(), tts)


def _run_voice(args: argparse.Namespace) -> dict[str, Any]:
    """语音对话模式：目标语音收集 → 全流程语音作答 → 战报朗读。

    无麦克风时回落 interactive；全程保留文字输出（评审/录屏字幕友好）。
    """
    session = _build_voice_session(args)
    if not session.is_available():
        print("⚠️ 未检测到可用麦克风，已回落文字交互模式（--mode interactive）。")
        return _run_interactive(args)

    graph, rt, _init, framework = _build(args)
    print(f"🤖 运行模式：voice  ·  模型：{rt.llm.mode}  ·  TTS：{session.tts_name}  ·  学员：{args.learner}")
    print("🧭 对话式学习已开启：听到「叮」后对着麦克风说话；")
    print("   角色会朗读（讲解/对线/复盘/战报），每步仍有回车确认兜底；q+回车 可随时退出。\n")

    # 1) 语音收集目标诉求（识别为空则用 --goal 兜底）
    session.say("你好，我是你的成长教练。用一句话告诉我，你最想提升哪方面的能力？")
    goal = session.listen_goal(args.goal)
    init = new_initial_state(args.learner, goal)
    print(f"🎯 已明确诉求：{goal}\n")

    def tour(payload: dict[str, Any]) -> None:
        render_payload(payload)  # 屏幕展示结构化内容（选项列表等）

    def narrate(delta: list[dict[str, str]]) -> None:
        for m in delta:  # 朗读角色叙述（计划/讲解/对线/反馈/战报）
            session.say(m.get("content", ""))

    def _answer(payload: dict[str, Any]) -> Any:
        if "assessment" in payload:
            return _voice_assessment(session, payload["assessment"])
        if "learn" in payload:
            return session.listen_action(payload["learn"].get("options", []))
        if "spar" in payload:
            return session.listen_free_text("你的回应：")
        if "review" in payload:
            return session.listen_free_text("复盘反思：")
        return "好的，继续。"

    try:
        final = run_graph(
            graph, init,
            thread_id=args.learner,
            answerer=InteractorAnswerer(_answer),
            on_interrupt=tour,
            on_message=narrate,
        )
    except KeyboardInterrupt:
        print("\n👋 已退出。数据已按当前进度保存，重跑可续学。")
        return {}

    render_battle_report(final, framework)
    # 战报朗读摘要
    summary = final.get("report", {}).get("summary", "")
    if summary:
        session.say(f"恭喜通关！{summary}")
    return final


def _voice_assessment(session: VoiceSession, inner: dict[str, Any]) -> dict[str, Any]:
    """测评单题语音作答：朗读题干 → 听语音 → 命中选项则确认。"""
    q = inner.get("question", {})
    index = inner.get("index", 0) + 1
    return {"question_id": q["id"], "option": session.listen_option(q, index=index)}


def main() -> None:
    # Windows 控制台 UTF-8（全中文界面；stdin 统一，保证中文输入与界面一致）
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ensure_data_dirs()

    args = _parse_args()
    if args.mode == "auto":
        _run_auto(args)
    elif args.mode == "voice":
        _run_voice(args)
    else:
        _run_interactive(args)


if __name__ == "__main__":
    main()
