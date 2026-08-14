"""CLI 入口：自驱成长 Agent 演示与交互。

用法：
  python -m selfgrow.cli.main --mode auto          # 自动演示（录视频用，脚本作答）
  python -m selfgrow.cli.main --mode interactive    # 真人交互（实时扮演学习者）
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

DEFAULT_GOAL = "我想提升向上管理，尤其想学会怎么跟老板汇报"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SelfGrowAgent · 自驱成长 Agent（向上管理）")
    p.add_argument("--mode", choices=["auto", "interactive"], default="auto",
                   help="auto=自动演示；interactive=真人交互")
    p.add_argument("--goal", default=DEFAULT_GOAL, help="学员原始诉求")
    p.add_argument("--learner", default="learner_01", help="学员 ID（也用作续学 thread_id）")
    p.add_argument("--db", default=None, help="SQLite 路径（默认 data/selfgrow.db，:memory: 用内存库）")
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
    else:
        _run_interactive(args)


if __name__ == "__main__":
    main()
