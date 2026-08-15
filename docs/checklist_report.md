# 附录 C：Demo 验证清单核对报告

**项目**：SelfGrowAgent —— 面向成年人的个性化自驱学习 Agent
**参赛**：世界人工智能开源大赛 · GOAI 无界应用（AI + 教育，4.3.4 个性化学习规划 Agent / 职业教育 Agent）
**核对日期**：2026-08-15
**结论速览**：6 项检查项 —— **5 项完成 ✅，1 项部分完成 ⚠️**（⑥ 路演材料，缺演示视频与现场展示，详见下）

---

## ① 可从零开始运行 Demo —— ✅ 完成

**检查要求**：提供环境、依赖、配置和启动方式。

| 项 | 说明 |
|---|---|
| 环境 / 依赖 | `pip install -e ".[engine]"`（LangGraph + anthropic SDK）；`pip install -e ".[web]"` 追加 FastAPI |
| 配置 | 双模 LLM：有 `ANTHROPIC_API_KEY` 用真 Claude；无则自动降级确定性 Mock（零依赖，离线可跑） |
| 启动方式 | CLI：`python -m selfgrow.cli.main --mode auto`（自动演示）/ `--mode interactive`（真人交互）；Web：`python -m selfgrow.web.app` → http://127.0.0.1:8000 |
| 自检 | `python -m unittest discover -s tests` → **95 用例全绿（约 4s）** |

**证据**：[README.md §四「快速开始」](README.md)，含 CLI 参数表（`--mode/--goal/--learner/--db`）。

---

## ② 至少有一个完整任务链路 —— ✅ 完成

**检查要求**：展示输入、处理、工具调用、结果交付和验证。

| 环节 | 本作品表现 |
|---|---|
| 输入 | 学员诉求「我想提升向上管理，尤其想学会怎么跟老板汇报」 |
| 处理 | LangGraph 五角色节点：诊断 → 规划 → 学习 → 对线 → 复盘 → 复测 → 毕业；`interrupt()`/`Command(resume=)` 多轮交互 |
| 工具调用 | `generate_question×13`（逐题出题）/ `generate_scenario×2`（动态场景）/ `search_knowledge×2`（RAG 检索）/ `save_record×11`（落库）/ `build_mindmap×1`（思维导图），全程留痕 |
| 结果交付 | 通关战报 + 成长雷达 + 闯关路线（XP 100 / 等级 L3） |
| 验证 | 基线 vs 复测雷达对比 →「已提升 3 项 / 仍待修炼 1 项」；95 用例端到端全绿 |

**证据**：[docs/artifacts/demo_auto_run.txt](docs/artifacts/demo_auto_run.txt)（212 行实跑日志）、[tests/test_graph_e2e.py](tests/test_graph_e2e.py)。

---

## ③ 样例数据与权限说明清楚 —— ✅ 完成

**检查要求**：说明数据来源、授权、脱敏和适用边界。

| 项 | 说明 |
|---|---|
| 数据来源 | **全部自建模拟数据**：能力框架 / 测评题库 / 情景副本 / 知识语料基于公开方法论（金字塔原理、STAR、SBI、预期管理等）原创编写，无任何真实学生、教师或机构数据 |
| 授权 | 不采集身份信息；`learner_id` 由用户自拟；自动演示模式不产生真实行为数据 |
| 脱敏 | 提供真实数据接入的去标识化 / 脱敏 / 匿名化技术清单，及合规评审清单（需通过评审方可启用） |
| 适用边界 | 当前版本不接入真实数据；输出为辅助学习建议，不替代正式测评与专业咨询 |

**证据**：[docs/data_compliance.md](docs/data_compliance.md)、[docs/boundary_risks.md](docs/boundary_risks.md)。

---

## ④ 失败与异常分支可解释 —— ✅ 完成

**检查要求**：说明调用失败、信息不足、高风险判断时的处理方式。

| 分支 | 处理方式 |
|---|---|
| 调用失败 | LLM 返回非法 JSON → `try/except` 回退确定性题库 / 场景库（[tools.py:78-84](src/selfgrow/agents/tools.py#L78-L84)、[:144-150](src/selfgrow/agents/tools.py#L144-L150)），双模行为一致、循环永不卡死 |
| 信息不足 | 讲师人设「答不上来就明说」；教学原则「给提示不给答案」——错因分析、同类训练 |
| 高风险判断 | 人工确认机制：测评作答 / 学习动作 / 对线回应 / 复盘反思均由学习者亲自决策；关键结论人工确认 |
| 网络依赖 | 真模型调用失败自动落回确定性 Mock，演示与测试不中断 |

**证据**：[docs/boundary_risks.md](docs/boundary_risks.md)（§3 人工确认机制、§4 风险与缓解）、[src/selfgrow/agents/tools.py](src/selfgrow/agents/tools.py)。

---

## ⑤ 输出结果可追溯 —— ✅ 完成

**检查要求**：提供依据来源、日志、截图或评测证据。

| 证据类型 | 本作品 |
|---|---|
| 依据来源 | RAG 知识检索留痕（`knowledge_hits`）、测评标准答案与解析 |
| 日志 | `state["tools_called"]` 评审证据；[docs/artifacts/demo_auto_run.txt](docs/artifacts/demo_auto_run.txt) 完整实跑日志 |
| 截图 | [docs/artifacts/web_vn_assessment.png](docs/artifacts/web_vn_assessment.png)（测评单题 VN 场景）、[web_vn_hud.png](docs/artifacts/web_vn_hud.png)（HUD/旅程点）、[web_vn_boss.png](docs/artifacts/web_vn_boss.png)（BOSS 副本） |
| 评测证据 | 95 用例全绿；基线 vs 复测雷达量化对比；思维导图产物（`data/artifacts/*.mmd`） |

---

## ⑥ 路演材料与 Demo 一致 —— ⚠️ 部分完成

**检查要求**：PPT、视频、仓库、说明文档和现场展示互相对应。

| 材料 | 状态 |
|---|---|
| 仓库 / 说明文档 | ✅ 已同步当前 Demo：README / [demo_report.md](docs/demo_report.md) / [architecture.md](docs/architecture.md) 均对齐「AI 逐题自适应测评 + 动态场景引擎 + VN 前端 + 95 用例」 |
| 实跑证据 | ✅ [docs/artifacts/demo_auto_run.txt](docs/artifacts/demo_auto_run.txt) + 3 张 VN 截图入库 |
| PPT | ⚠️ 不在仓库内，由参赛路演材料另行制作 |
| 演示视频 | ⚠️ 待录制（`python -m selfgrow.cli.main --mode auto` 确定性输出，适合录屏） |
| 现场展示 | ⚠️ 以 Web VN 界面（http://127.0.0.1:8000）为准 |

---

## 结论与待办

**已满足（✅）**：可从零开始运行 / 完整任务链路 / 样例数据与权限 / 失败异常分支 / 输出可追溯。
**待完善（⚠️）**：第 ⑥ 项「路演材料与 Demo 一致」——文档与证据已同步，尚缺**演示视频**与**现场展示**（PPT 由参赛材料另行制作）。

待办清单：

- [ ] 录制演示视频（`--mode auto` 自动模式，全程离线 Mock 可跑）
- [ ] 现场以 Web VN 界面演示（启动 `python -m selfgrow.web.app`）
- [ ] 制作参赛路演 PPT，与本文档、Demo、证据一一对应

> 本报告为参赛验收的核对说明，证据全部来自仓库内自建模拟数据与实测日志，无真实数据。
