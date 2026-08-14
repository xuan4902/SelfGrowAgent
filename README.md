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

## 二、核心闭环

```
诊断（能力雷达图）→ 规划（闯关路线）→ 周循环{学习 → 对线 → 复盘} ×N
→ 复测（动态调整）→ 毕业战报（量化成长）
```

## 三、快速开始

```bash
# 1. 安装
pip install -e ".[engine]"

# 2. 跑测试（零依赖 Mock 模式，全绿即环境正常）
python -m unittest discover -s tests -v

# 3. 自动模式完整演示（供录 Demo 视频）
python -m selfgrow.cli.main --mode auto

# 4. 交互模式（你实时扮演学习者）
python -m selfgrow.cli.main

# 5. 真模型模式（需配置 ANTHROPIC_API_KEY 后自动切换，或显式指定）
SELFGROW_LLM=claude python -m selfgrow.cli.main
```

## 四、存储与数据

- **向量库**：VectorStore 适配器 —— InMemory（stdlib 中文 bigram 余弦，零依赖兜底）/ Milvus（`SELFGROW_VECTOR_STORE=milvus` 切换）
- **关系库**：SQLite（学习数据）+ 适配器接口预留 PG/MySQL
- **数据合规**：全部自建模拟数据，详见 [docs/data_compliance.md](docs/data_compliance.md)
- **使用边界**：输出为辅助建议，不替代专业教育评价，详见 [docs/boundary_risks.md](docs/boundary_risks.md)

## 五、仓库结构

```
data/           能力框架 / 测评题库 / 情景副本 / 知识语料（自建模拟数据）
src/selfgrow/   competency(框架+雷达) llm(Claude+Mock) rag storage(向量+SQLite)
                agents(LangGraph 五节点+工具注册表) cli(演示入口)
docs/           架构说明 / 数据合规 / 边界与风险
tests/          unittest 全覆盖 + 图端到端 smoke
```
