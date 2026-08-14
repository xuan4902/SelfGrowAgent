# SelfGrowAgent — 面向成年人的个性化自驱学习 Agent

> 把「我想学 X」转化为「可诊断、有计划、有练习、有反馈、能坚持」的能力成长闭环。

**参赛赛道**：世界人工智能开源大赛 · GOAI 无界应用（AI + 教育，4.3.4 个性化学习规划 Agent / 职业教育 Agent）
**技术路线**：Python + LangGraph 多 Agent 编排 + Claude 模型（双模：无 API Key 自动降级确定性 Mock）
**首个能力域**：向上管理（6 项子能力 × 5 级行为锚定）

---

## 一、五个角色化 Agent

| 角色 | 职责 | 对应官方能力点 |
|---|---|---|
| 🔮 占卜师・诊断官 | 拆解模糊诉求、情景测评、定位短板 | 任务理解、结果验证 |
| 🗺️ 制图师・规划师 | 定制闯关路线、动态调整难度 | 计划生成 |
| 📖 讲师・知识官 | RAG 知识库讲解、记住你的上下文 | 知识增强、上下文记忆 |
| ⚔️ 陪练武士・陪练官 | 沉浸式副本对线、多轮互动、即时反馈 | 多轮交互、结果验证 |
| 📜 史官・复盘官 | 成长数据、通关战报、技能沉淀 | 上下文记忆、结果验证 |

**工具调用**（知识库检索 / 测评生成 / 雷达渲染 / 思维导图 / 数据落库）贯穿全流程，
每次调用记录进会话日志，作为 Agent 能力的可验证证据。

## 二、官方 7 项 Agent 能力的体现

| 官方能力点 | 作品实现 |
|---|---|
| ① 任务理解 | 🔮 把「我想更会来事」拆解成 6 项子能力目标 |
| ② 计划生成 | 🗺️ 按薄弱点生成周闯关路线；**复测后动态重排剩余关卡** |
| ③ 多轮交互 | `interrupt()`/`Command(resume=)`：逐题作答、讲师追问、NPC 多回合对线、复盘 |
| ④ 工具调用 | 知识检索/测评生成/场景取用/雷达渲染/思维导图/落库，全程留痕（评审证据） |
| ⑤ 知识增强 RAG | 📖 10 篇自撰语料分块向量化，检索 top-k 注入讲解 |
| ⑥ 上下文记忆 | LangGraph checkpointer（thread_id=learner_id）断点续学 + SQLite 历史雷达对比 |
| ⑦ 结果验证 | 基线 vs 复测雷达对比 → 量化成长战报 + 「仍待修炼」提示 |

## 三、核心闭环

```
诊断（能力雷达图）→ 规划（闯关路线）→ 周循环{学习 → 对线 → 复盘} ×N
→ 中途复测（动态调整）→ 毕业战报（量化成长）
```

## 四、快速开始

```bash
# 1. 安装（engine 组：langgraph + anthropic SDK）
pip install -e ".[engine]"

# 2. 跑测试（零依赖 Mock 模式，44 用例全绿即环境正常）
python -m unittest discover -s tests -v

# 3. 自动模式完整演示（供录 Demo 视频，脚本作答跑完整闭环）
python -m selfgrow.cli.main --mode auto

# 4. 交互模式（你实时扮演学习者：作答测评 → 选学习动作 → 与 NPC 对线 → 复盘）
python -m selfgrow.cli.main --mode interactive

# 5. Web 图形界面（浏览器走完整闭环：测评单选 → 三按钮 → 对线 → 复盘 → 战报+雷达）
pip install -e ".[web]"
python -m selfgrow.web.app          # 打开 http://127.0.0.1:8000（安装后也可用 selfgrow-web）

# 6. 真模型模式（配置 ANTHROPIC_API_KEY 后自动切换，或显式指定）
SELFGROW_LLM=claude python -m selfgrow.cli.main
```

### CLI 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--mode` | `auto` | `auto` 自动演示 / `interactive` 真人交互 |
| `--goal` | 向上管理演示诉求 | 学员原始诉求 |
| `--learner` | `learner_01` | 学员 ID（同时是续学 thread_id） |
| `--db` | `data/selfgrow.db` | SQLite 路径（`:memory:` 用内存库） |

## 五、动态调整演示（核心亮点）

跑完一半周数即触发**复测**：占卜师聚焦薄弱维度重新测评 → 制图师按新雷达重排剩余关卡。
示例：基线雷达显示「管理期待/争取资源/向上沟通」最弱，第一周学「管理期待」；
复测后「应对反馈」被识别为新的最短板 → 制图师把剩余 1 关**重排为「应对反馈」**。

## 六、存储与数据

- **向量库**：VectorStore 适配器 —— InMemory（stdlib 中文 bigram 余弦，零依赖兜底）/ Milvus（`SELFGROW_VECTOR_STORE=milvus` 切换）
- **关系库**：SQLite（学习数据）+ 适配器接口预留 PG/MySQL
- **架构说明**：[docs/architecture.md](docs/architecture.md)（图拓扑 / 状态设计 / 能力映射）
- **数据合规**：全部自建模拟数据，详见 [docs/data_compliance.md](docs/data_compliance.md)
- **使用边界**：输出为辅助建议，不替代专业教育评价，详见 [docs/boundary_risks.md](docs/boundary_risks.md)

## 七、仓库结构

```
data/           能力框架 / 测评题库 / 情景副本 / 知识语料（自建模拟数据）
src/selfgrow/   competency(框架+雷达) llm(Claude+Mock) rag storage(向量+SQLite)
                agents(LangGraph 五节点+工具注册表) cli(演示入口) web(FastAPI+SSE 图形界面)
docs/           架构说明 / 数据合规 / 边界与风险 / 汇报演示
tests/          unittest 全覆盖 + 图端到端 smoke + Web 会话/HTTP 端到端
```

## 八、工程化里程碑（git log）

```
017183d P4: CLI 演示层（交互 + auto 自动演示 + 通关战报）
039bbcc P3: LangGraph 五角色多 Agent 编排（诊断/规划/学习/演练/复盘/毕业）
7460645 P2: LLM 双模(Claude/Mock) + RAG 知识库 + 存储层(向量+SQLite)
776d375 P1: 数据层 + competency 包（雷达/rubric）
84e1ee0 P0: 项目脚手架
```
