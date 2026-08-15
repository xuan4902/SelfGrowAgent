"""CLI 渲染层：角色卡横幅 / 中断负载呈现 / 通关战报。

设计：渲染与收集分离——render 打印给用户，prompt 收集输入（interactive 模式用）；
auto 模式复用 render 做实时讲解，输入由 ScriptedAnswerer 接管。
"""

from __future__ import annotations

from typing import Any

from selfgrow.agents.roles import get_role
from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.radar import render_ascii_radar

SEP = "─" * 64


def _dim_name(framework: CompetencyFramework | None, dim_id: str) -> str:
    if framework is None:
        return dim_id
    dim = framework.get_dimension(dim_id)
    return dim.name if dim else dim_id


def role_banner(role_id: str) -> str:
    return get_role(role_id).banner()


# ---- 中断负载呈现（auto 讲解 / interactive 共用） ----

def render_assessment(inner: dict[str, Any]) -> None:
    print(SEP)
    idx = inner.get("index", 0) + 1
    total = inner.get("total", 1)
    print(f"🔮 测评 · {inner.get('stage_label', '基线测评')} 第 {idx}/{total} 题")
    narration = inner.get("narration", "")
    if narration:
        print(f"  {narration}")
    q = inner.get("question", {})
    if q:
        print(f"  {q.get('scenario', '')}")
        for oi, opt in enumerate(q.get("options", []), start=1):
            print(f"     ({oi}) {opt}")


def render_learn(inner: dict[str, Any]) -> None:
    print(SEP)
    print(f"📖 第 {inner.get('week')} 关「{inner.get('dimension_name')}」讲解")
    print(inner.get("lesson", ""))
    print(f"  下一步：{ ' / '.join(inner.get('options', [])) }")


def render_spar(inner: dict[str, Any]) -> None:
    print(SEP)
    print(f"⚔️ 副本《{inner.get('scene_title', '')}》 回合 {inner.get('user_turns', 0) + 1}/{inner.get('max_turns', 2)}")
    if inner.get("scene_goal"):
        print(f"  目标：{inner['scene_goal']}")
    boss = inner.get("boss", {}) or {}
    if boss.get("role"):
        print(f"  BOSS：{boss.get('role', '')}（{boss.get('style', '')}）· {boss.get('persona', '')}")
    if inner.get("environment"):
        print(f"  环境：{inner['environment']}")
    pressure = inner.get("pressure") or {}
    if pressure.get("desc"):
        print(f"  压力：{'█' * inner.get('pressure_now', 0)}{'░' * (5 - inner.get('pressure_now', 0))} {pressure['desc']}")
    if inner.get("stakes"):
        print(f"  利害：{inner['stakes']}")
    print(f"  NPC：{inner.get('npc_line', '')}")


def render_review(inner: dict[str, Any]) -> None:
    print(SEP)
    print(f"📜 第 {inner.get('week')} 关复盘（{inner.get('dimension_name', '')}）")
    print(inner.get("guide", ""))


def render_payload(payload: dict[str, Any]) -> None:
    """auto 模式：讲解当前中断点，让观众看到每一步。"""
    if "assessment" in payload:
        render_assessment(payload["assessment"])
    elif "learn" in payload:
        render_learn(payload["learn"])
    elif "spar" in payload:
        render_spar(payload["spar"])
    elif "review" in payload:
        render_review(payload["review"])


# ---- interactive 输入收集 ----

def _ask_option(prompt: str, options: list[str], default: str = "") -> str:
    while True:
        raw = input(prompt).strip() or default
        if raw in options:
            return raw
        for i, opt in enumerate(options, start=1):
            if raw == str(i) or raw == str(i) + ".":
                return opt
        print(f"  请输入 { ' / '.join(options) }")


def collect_assessment(inner: dict[str, Any], framework: CompetencyFramework | None) -> dict[str, Any]:
    render_assessment(inner)
    q = inner.get("question", {})
    n = len(q.get("options", []))
    while True:
        raw = input(f"  你的选择（回车=第 1 项，1-{n}）：").strip()
        if not raw:
            return {"question_id": q["id"], "option": 0}  # 空回车默认选第 1 项（防死循环/自动模式）
        if raw.isdigit() and 1 <= int(raw) <= n:
            return {"question_id": q["id"], "option": int(raw) - 1}
        print("  请输入有效选项序号")


def collect_learn(inner: dict[str, Any]) -> str:
    render_learn(inner)
    return _ask_option("  选择下一步（回车=去演练）：", inner.get("options", []), default="去演练")


def collect_spar(inner: dict[str, Any]) -> str:
    render_spar(inner)
    return input("  你的回应：").strip()


def collect_review(inner: dict[str, Any]) -> str:
    render_review(inner)
    return input("  写下你的复盘反思（回车跳过）：").strip()


def prompt_for(payload: dict[str, Any], framework: CompetencyFramework | None = None) -> Any:
    """interactive 模式：把中断负载渲染成提示并收集真实输入。"""
    if "assessment" in payload:
        return collect_assessment(payload["assessment"], framework)
    if "learn" in payload:
        return collect_learn(payload["learn"])
    if "spar" in payload:
        return collect_spar(payload["spar"])
    if "review" in payload:
        return collect_review(payload["review"])
    return input("继续？").strip()


# ---- 通关战报 ----

def render_battle_report(final: dict[str, Any], framework: CompetencyFramework) -> None:
    report = final.get("report", {})
    before = report.get("radar_before", {})
    after = report.get("radar_after", final.get("radar", {}))

    print("\n" + "=" * 64)
    print("🎓  通关战报 · SelfGrowAgent")
    print("=" * 64)
    print(f"学员诉求：{report.get('goal', final.get('goal', ''))}")
    print(f"最终战果：XP {report.get('xp', 0)}  ·  等级 L{report.get('level', 1)}  ·  "
          f"工具调用 {len(final.get('tools_called', []))} 次")

    print("\n— 能力雷达 · 成长对比 —")
    print("【入关时】")
    print(render_ascii_radar(framework, before))
    print("【通关后】")
    print(render_ascii_radar(framework, after))

    improved = report.get("improved", [])
    remaining = report.get("remaining_gaps", [])
    print("\n— 成长维度 —")
    if improved:
        print("✅ 已提升：" + "、".join(improved))
    else:
        print("（复测与基线持平）")
    if remaining:
        print("🔸 仍待修炼：" + "、".join(remaining) + "（建议开启下一轮副本）")

    # 演练反馈亮点（结果验证）
    fb = final.get("spar_feedback")
    if fb:
        print("\n— 陪练反馈（演练评分） —")
        print(f"  综合等级：L{fb.get('overall_level', 1)} / 5")
        mistakes = fb.get("mistakes", [])
        if mistakes:
            print("  待磨刀：" + "；".join(mistakes[:2]))
        suggestions = fb.get("suggestions", [])
        if suggestions:
            print("  已掌握：" + "；".join(suggestions[:1]))

    summary = report.get("summary", "")
    if summary:
        print("\n📜 史官结语")
        print(summary)

    # 闯关路线
    plan = final.get("plan", {})
    if plan.get("weeks"):
        print("\n— 闯关路线（本周期） —")
        for w in plan["weeks"]:
            mark = "✔" if w["week"] <= final.get("current_week", 0) else "▷"
            print(f"  {mark} W{w['week']} {w['topic']} → {w['goal']}")

    # 五角色参与
    roles = sorted({m["role"] for m in final.get("messages", [])})
    if roles:
        print("\n— 五角色协作 —")
        print("  " + "  ".join(role_banner(r) for r in roles))

    # 工具调用留痕
    tools = final.get("tools_called", [])
    if tools:
        counts: dict[str, int] = {}
        for t in tools:
            counts[t["name"]] = counts.get(t["name"], 0) + 1
        print("\n— 工具调用留痕（评审证据） —")
        print("  " + "、".join(f"{name}×{n}" for name, n in sorted(counts.items())))

    print("\n— 边界声明 —")
    print("本结果为辅助学习建议，不替代正式测评、学校/机构评价或专业心理咨询。")
    print("全部数据为自建模拟数据，不涉及真实个人信息；如需接入真实学习者数据，请先完成合规评审。")
    print("=" * 64)
