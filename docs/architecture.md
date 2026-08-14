# SelfGrowAgent 架构说明

> 面向 20–35 岁职场成年人的个性化自驱学习 Agent（首个能力域：向上管理）。
> 作品体现官方 7 项 Agent 能力，采用 LangGraph 多 Agent 编排 + Claude 双模模型 + RAG 知识增强。

## 1. 总体架构

```
┌────────────────────────────────────────────────────────────────┐
│                       CLI 演示层（交互 / auto）                 │
│        python -m selfgrow.cli.main --mode auto|interactive      │
└───────────────────────────────┬────────────────────────────────┘
                                │ run_graph（中断/恢复驱动）
┌───────────────────────────────▼────────────────────────────────┐
│                 LangGraph StateGraph + InMemorySaver            │
│            thread_id = learner_id → 断点续学 / 上下文记忆        │
│                                                                │
│   🔮diagnose → 🗺️plan → 📖learn → ⚔️spar → 📜review → (route)  │
│        └──────── 条件回边：复测 / 继续问 / 未完重打 / 毕业 ──┘  │
└───────────────────────────────┬────────────────────────────────┘
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌──────────────┐       ┌──────────────┐        ┌──────────────┐
│ LLM 双模      │       │ 工具注册表     │        │ 存储层        │
│ Claude(真)    │       │ generate_…   │        │ VectorStore   │
│ Mock(确定性)  │       │ search_know… │        │  InMemory/Milvus│
│ TASK 标签路由 │       │ save_record… │        │ SQLite(学习数据)│
└──────────────┘       └──────────────┘        └──────────────┘
```

## 2. 五角色 Agent 与官方 7 项能力的映射

| 官方能力点 | 实现位置 | 作品中的体现 |
|---|---|---|
| 1. 任务理解 | 🔮 诊断官（`nodes/diagnose.py`） | 模糊诉求 → 规则+LLM 拆解为能力维度子目标 |
| 2. 计划生成 | 🗺️ 规划师（`nodes/plan.py` + `agents/planning.py`） | 按雷达薄弱点生成周闯关路线；复测后动态重排剩余关卡 |
| 3. 多轮交互 | 全图 `interrupt()`/`Command(resume=)` | 测评逐题作答、讲师追问、与 NPC 多回合对线、复盘反思 |
| 4. 工具调用 | 🔮📖⚔️📜（`agents/tools.py`） | 知识检索/测评生成/场景取用/雷达渲染/思维导图/落库，全程留痕 |
| 5. 知识增强 RAG | 📖 讲师（`rag/` 包） | 10 篇自撰语料 → `##` 分块 → bigram 哈希向量 → 余弦 top-k 检索 |
| 6. 上下文记忆 | InMemorySaver（`thread_id=learner_id`）+ SQLite 落库 | 跨中断/跨周会话延续、历史雷达对比、断点续学 |
| 7. 结果验证 | 🔮 复测 + 📜 毕业（`nodes/graduate.py`） | 基线 vs 复测雷达对比 → 量化成长战报 + 仍待修炼维度 |

## 3. LangGraph 图拓扑

```
START → diagnose → plan ─(stage==reassess, 周数已满)→ graduate → END
                      └(else)→ learn ─(继续问)→ learn
                                  ├─(去演练)→ spar ─(未完)→ spar
                                  │             └─(打完)→ review
                                  └─(复盘)→ review ─(中途检查点未复测)→ diagnose(复测)
                                                       ├─(周数未满)→ learn
                                                       └─(复测完成且周数满)→ graduate
```

**动态调整策略**：跑完一半周数（`max(1, total//2)`）即触发复测，制图师按新雷达重排剩余关卡，
避免「最后才复测、无剩余周可调整」的演示缺陷。复测只更新被测维度，保留其它维度已有水平。

### 中断/恢复语义（LangGraph 1.x 关键设计）

- 节点内 `interrupt(payload)` 暂停，外层用 `Command(resume=value)` 恢复。
- **恢复时节点会整体重跑**，因此 `AgentState` 所有列表字段采用 **replace 语义**（无 reducer），
  节点显式合并：`state.get("tools_called", []) + called`，避免重复追加。
- 中断点的部分节点返回值不会提交 checkpoint，能读到的是 interrupt 负载与既有会话状态
  （详见 `tests/test_graph_e2e.py::test_resume_after_interrupt_preserves_context`）。

## 4. LLM 双模设计（`llm/`）

| 模式 | 触发 | 特性 |
|---|---|---|
| Claude | 有 `ANTHROPIC_API_KEY`（或 `SELFGROW_LLM=claude`） | 真实模型：角色人设 + `[TASK: xxx]` 标签 + `CTX:` JSON 上下文 |
| Mock | 无 Key 默认 | 按 TASK 标签路由到确定性模板，同输入同输出，测试/演示可复现 |

`get_llm()` 工厂按 `SELFGROW_LLM` 环境变量与 Key 自动选择；`with_task()`/`with_ctx()`
在 prompt 中注入任务标签与上下文，使双模行为路径一致。

## 5. RAG 知识管线（`rag/`）

1. 语料：`data/knowledge/managing_up/`（10 篇自撰中文 Markdown）
2. 分块：按 `##` 标题切块，每块 200–500 字，附 `{title, section}`
3. 向量化：`BigramHashEmbedder` —— 中文 char-bigram 哈希 256 维 + L2 归一化（stdlib，零依赖）
4. 检索：余弦相似度 top-k，讲师注入 `knowledge_hits` 生成讲解
5. 可替换：Embedder/VectorStore 均为协议接口，可平滑接入真实 embedding + Milvus

## 6. 存储层（`storage/`）

- **向量库** `VectorStore` 协议：`InMemoryVectorStore`（stdlib 兜底）/ `MilvusVectorStore`
  （`SELFGROW_VECTOR_STORE=milvus` 切换，pymilvus 可选依赖）
- **关系库** SQLite（stdlib sqlite3）：`learners / assessments / plans / learning_records /
  spar_sessions / reviews / knowledge_docs` 七表，`repos.py` 提供读写仓库，适配器接口预留 PG/MySQL

## 7. AgentState 关键字段

```
learner_id / goal / messages            # 会话与多轮历史
goal_breakdown / radar / radar_before   # 诊断：拆解 + 雷达 + 成长基线
gaps / stage                            # 薄弱维度 + 流程状态(baseline|reassess)
plan / current_week / adjustment        # 闯关路线 + 进度 + 动态调整说明
knowledge_hits / lesson / user_action   # 学习：RAG 命中 + 讲解 + 用户选择
scenario / spar_transcript / spar_feedback / battle_over   # 演练
review / report / xp / level            # 复盘 + 毕业战报
llm_mode / tools_called                 # 运行元信息 + 工具调用日志(评审证据)
```

## 8. 测试策略

33 个 unittest，全部 mock 模式确定性运行（零 API Key）：

```
python -m unittest discover -s tests -v
```

- `test_competency` / `test_radar`：框架加载、雷达计算、rubric 评分
- `test_mock_llm`：TASK 路由、CTX 注入、确定性（同输入同输出）
- `test_rag` / `test_vector_store` / `test_storage`：检索、向量、SQLite
- `test_graph_e2e`：全链路闭环 + 断点续学 + 动态调整 + on_interrupt 钩子
