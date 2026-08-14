"""确定性 Mock LLM：按 [TASK:xxx] 标签 + CTX 注入数据路由到预置模板。

无随机数、无网络，同输入必得同输出，保证演示与测试可复现。
"""

from __future__ import annotations

import json
from typing import Any

from selfgrow.llm.base import CTX_MARKER, extract_task


class MockLLM:
    mode = "mock"

    def complete(self, system: str, user: str) -> str:
        task = extract_task(user) or "chat"
        ctx = self._parse_ctx(user)
        handler = getattr(self, f"task_{task}", None)
        if handler is None:
            return self.task_chat(ctx, system)
        return handler(ctx, system)

    @staticmethod
    def _parse_ctx(user: str) -> dict[str, Any]:
        for line in user.splitlines():
            if line.startswith(CTX_MARKER):
                try:
                    return json.loads(line[len(CTX_MARKER):].strip())
                except json.JSONDecodeError:
                    return {}
        return {}

    # ---- 各任务模板（全部确定性，只读 ctx） ----

    def task_chat(self, ctx: dict, system: str) -> str:
        return "（示例回复）收到！我们可以继续探讨这个话题。你可以输入：继续 / 去演练 / 复盘 / 结束。"

    def task_goal_breakdown(self, ctx: dict, system: str) -> str:
        domain = ctx.get("domain_name", "向上管理")
        subs = "、".join(ctx.get("sub_goals", ["对齐目标", "结构化汇报", "管理期待"]))
        return (
            f"本座把你的诉求盘明白了——你想要的本质是提升「{domain}」。\n"
            f"拆解为 3 条可修炼的细分目标：{subs}。\n"
            f"先做一次情景占卜（3 分钟测评），本座就能看出你的天赋属性与短板所在。"
        )

    def task_plan_narrate(self, ctx: dict, system: str) -> str:
        weeks = ctx.get("weeks", 8)
        first = ctx.get("first_dimension_name", "目标对齐")
        return (
            f"路线图已绘制完成！前方共 {weeks} 座关卡，第一关从你最薄弱的「{first}」开始。\n"
            f"每一关都是：拜师学艺（学方法）→ 副本对战（练实战）→ 史官复盘（沉淀技能）。\n"
            f"难度会随你的表现动态调整，绝不搞一刀切。"
        )

    def task_lesson(self, ctx: dict, system: str) -> str:
        dim_name = ctx.get("dimension_name", "目标对齐")
        hits = ctx.get("knowledge_hits", [])
        points = "；".join(hits[:2]) if hits else "先讲核心原则，再给一个可落地的练习"
        return (
            f"好，这周我们修炼「{dim_name}」。为师从知识库翻出了干货：{points}。\n"
            f"先记住一句话原则，然后我们进副本实战。准备好了就说『去演练』。"
        )

    def task_spar_npc(self, ctx: dict, system: str) -> str:
        lines = ctx.get("mock_lines", [])
        idx = int(ctx.get("turn", 0))
        if not lines:
            return "（NPC 等待你的回应）"
        return lines[idx % len(lines)]

    def task_spar_feedback(self, ctx: dict, system: str) -> str:
        level = ctx.get("overall_level", 3)
        mistakes = ctx.get("mistakes", ["表达可以更聚焦"])
        suggestions = ctx.get("suggestions", ["结论先行"])
        m = "；".join(mistakes[:2])
        s = "；".join(suggestions[:2])
        return (
            f"打完收功！这局评分 L{level}。\n"
            f"短板：{m}。\n"
            f"磨刀建议：{s}。休息一下，随时可以再来一局同类副本，或让史官复盘。"
        )

    def task_review(self, ctx: dict, system: str) -> str:
        dim_name = ctx.get("dimension_name", "这一关")
        return (
            f"战斗结束了，跟史官走一遍复盘：\n"
            f"① 这一关「{dim_name}」你经历了什么？\n"
            f"② 你注意到自己哪些反应和想法？\n"
            f"③ 能提炼出一条什么原则？\n"
            f"④ 下周在工作中，你会怎么用它？"
        )

    def task_report(self, ctx: dict, system: str) -> str:
        xp = ctx.get("xp_gained", 100)
        level = ctx.get("level", 1)
        dims = ctx.get("improved", [])
        return (
            f"📜 通关战报已归档：本阶段成长 {xp} XP，等级提升至 L{level}。\n"
            f"主要提升：{('、'.join(dims)) if dims else '向上管理综合能力'}。\n"
            f"已沉淀进你的专属技能库。祝下个副本旗开得胜！"
        )
