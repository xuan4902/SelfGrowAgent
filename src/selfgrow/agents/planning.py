"""闯关路线生成与动态调整（纯函数，确定性）。

生成：按薄弱维度优先排序，每周一关（学 → 练 → 复盘），每周附里程碑/行动清单/关联副本/挑战。
调整：复测后按新雷达重排剩余周，输出调整说明（评审点：计划动态调整）。
"""

from __future__ import annotations

from typing import Any

from selfgrow.agents.bank import pick_scenario, scenario_title_for_id
from selfgrow.competency.models import CompetencyFramework
from selfgrow.competency.radar import top_gaps

# 每维度的知识库检索词（与 data/knowledge/managing_up 语料对齐）
_QUERY_HINTS: dict[str, str] = {
    "goal_alignment": "目标对齐 OKR 优先级确认 目标挂接",
    "report_structure": "向上汇报 结论先行 金字塔原理 结构化表达",
    "expectation_management": "预期管理 澄清标准 验收 偏差提前同步 缓冲",
    "resource_acquisition": "争取资源 ROI 论证 替代方案 五步法",
    "upward_communication": "向上沟通 同步频率 报喜也报忧 风险预警 坏消息",
    "handling_feedback": "反馈 SBI 复盘 改进跟进 冷静接收批评",
}

# 情景副本与维度对应（取不到就用工具回退）
_SCENARIO_FOR_DIM: dict[str, str] = {
    "goal_alignment": "sp_goal_01",
    "report_structure": "sp_report_01",
    "expectation_management": "sp_exp_01",
    "resource_acquisition": "sp_res_01",
    "upward_communication": "sp_comm_01",
    "handling_feedback": "sp_fb_01",
}

# 每维度确定性挑战句（场景库无 pressure.desc 时的兜底）
_CHALLENGES: dict[str, str] = {
    "goal_alignment": "挑战：目标会变、对齐要快——在冲突场景里当场给出取舍依据。",
    "report_structure": "挑战：用 30 秒讲清核心结论，再多一句都算输。",
    "expectation_management": "挑战：把不合理的 deadline 谈成带方案的约定。",
    "resource_acquisition": "挑战：被拒绝一次，也要能用新论证再开口。",
    "upward_communication": "挑战：把坏消息说在前头，还带着补救方案。",
    "handling_feedback": "挑战：被当众点名时不防御，先听懂再改进。",
}


def _week_goal(framework: CompetencyFramework, dim_id: str, current_level: int) -> str:
    dim = framework.get_dimension(dim_id)
    if dim is None:
        return f"掌握「{dim_id}」核心方法"
    path = dim.improvement_path(max(1, min(5, current_level)))
    return f"突破至 L{current_level + 1}：{path}"


def _week_extra(
    framework: CompetencyFramework, dim_id: str, level: int, scenario_id: str
) -> dict[str, Any]:
    """每周内容升级：里程碑（行为锚定）/ 行动清单（rubric 前三）/ 关联副本 / 挑战。全部确定性。"""
    dim = framework.get_dimension(dim_id)
    target = min(5, level + 1)
    anchor = ""
    if dim:
        for lv in dim.levels:
            if lv.level == target:
                anchor = lv.anchor or lv.path or ""
                break
    milestone = f"达成标准：{dim.name if dim else dim_id} 达 L{target}——{anchor}"
    actions = [{"criterion": r.criterion, "desc": r.desc} for r in (dim.rubric[:3] if dim else [])]
    title = scenario_title_for_id(framework.domain, scenario_id) if scenario_id else ""
    scenario_link = f"副本《{title}》" if title else ""
    scene = pick_scenario(framework.domain, dim_id)
    challenge = ((scene.get("pressure") or {}).get("desc", "")) or _CHALLENGES.get(dim_id, "")
    return {
        "milestone": milestone,
        "actions": actions,
        "scenario_link": scenario_link,
        "challenge": challenge,
    }


def _ordering(framework: CompetencyFramework, gaps: list[str], total_weeks: int) -> list[str]:
    """生成维度序列：先铺最薄弱维度，再循环其余维度。"""
    rest = [d.id for d in framework.dimensions if d.id not in gaps]
    seq: list[str] = []
    # 每轮按 gaps 顺序插一关，再补其余
    while len(seq) < total_weeks:
        for g in gaps:
            if len(seq) >= total_weeks:
                break
            seq.append(g)
        for d in rest:
            if len(seq) >= total_weeks:
                break
            seq.append(d)
    return seq[:total_weeks]


def generate_plan(
    framework: CompetencyFramework,
    radar: dict[str, int],
    gaps: list[str] | None = None,
    total_weeks: int = 2,
) -> dict[str, Any]:
    """按雷达与薄弱维度生成闯关路线。"""
    gaps = gaps or top_gaps(framework, radar, k=3)
    seq = _ordering(framework, gaps, total_weeks)

    weeks: list[dict[str, Any]] = []
    for i, dim_id in enumerate(seq, start=1):
        dim = framework.get_dimension(dim_id)
        level = radar.get(dim_id, 1)
        scenario_id = _SCENARIO_FOR_DIM.get(dim_id, "sp_report_01")
        weeks.append(
            {
                "week": i,
                "dimension": dim_id,
                "topic": dim.name if dim else dim_id,
                "goal": _week_goal(framework, dim_id, level),
                "knowledge_query": _QUERY_HINTS.get(dim_id, dim_id),
                "scenario_id": scenario_id,
                **_week_extra(framework, dim_id, level, scenario_id),
            }
        )
    return {"weeks": weeks, "total_weeks": total_weeks, "current_week": 0, "status": "active"}


def adjust_plan(
    framework: CompetencyFramework,
    plan: dict[str, Any],
    new_radar: dict[str, int],
) -> tuple[dict[str, Any], str]:
    """复测后动态调整剩余周：按新薄弱维度重排，返回 (调整后计划, 调整说明)。"""
    done = plan.get("current_week", 0)
    total = plan.get("total_weeks", len(plan.get("weeks", [])))
    remaining = total - done
    if remaining <= 0:
        return plan, "所有关卡已完成，无需调整。"

    new_gaps = top_gaps(framework, new_radar, k=3)
    seq = _ordering(framework, new_gaps, remaining)
    rest_weeks = plan.get("weeks", [])[done:]

    adjusted: list[dict[str, Any]] = plan.get("weeks", [])[:done]
    for i, dim_id in enumerate(seq):
        dim = framework.get_dimension(dim_id)
        level = new_radar.get(dim_id, 1)
        # 维度未变才复用原周语料/场景；换维度必须换成对应语料
        old = rest_weeks[i] if i < len(rest_weeks) else {}
        if old.get("dimension") == dim_id:
            knowledge_query = old.get("knowledge_query") or _QUERY_HINTS.get(dim_id, dim_id)
            scenario_id = old.get("scenario_id") or _SCENARIO_FOR_DIM.get(dim_id, "sp_report_01")
        else:
            knowledge_query = _QUERY_HINTS.get(dim_id, dim_id)
            scenario_id = _SCENARIO_FOR_DIM.get(dim_id, "sp_report_01")
        adjusted.append(
            {
                "week": done + i + 1,
                "dimension": dim_id,
                "topic": dim.name if dim else dim_id,
                "goal": _week_goal(framework, dim_id, level),
                "knowledge_query": knowledge_query,
                "scenario_id": scenario_id,
                **_week_extra(framework, dim_id, level, scenario_id),
            }
        )

    new_plan = dict(plan)
    new_plan["weeks"] = adjusted
    focus = [w["dimension"] for w in adjusted[done:]]
    focus_name = "、".join(
        framework.get_dimension(f).name for f in focus if framework.get_dimension(f)
    )
    adj = (
        f"复测完成！制图师已重排剩余 {remaining} 关：新增重点「{focus_name or '综合能力'}」。"
        f"难度与节奏已按最新表现动态调整，继续出发。"
    )
    return new_plan, adj


def build_mindmap_text(plan: dict[str, Any]) -> str:
    """mermaid mindmap 文本（供文档/演示）。"""
    lines = ["mindmap", "  root((向上管理 · 闯关路线))"]
    for w in plan.get("weeks", []):
        lines.append(f"    W{w['week']}[{w['topic']}]")
    return "\n".join(lines)
