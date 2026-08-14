# SelfGrowAgent 项目指南

## 项目定位
面向 20–35 岁职场成年人的个性化自驱学习 Agent（世界人工智能开源大赛 · 教育赛道）。
首个能力域：**向上管理**（6 子能力 × 5 级行为锚定）。
技术栈：LangGraph 1.x 编排 + Claude（anthropic SDK）+ Milvus 适配器 + SQLite。

## 设计原则
1. **双模 LLM**：`llm/base.py` 的 LLMFactory 按环境变量选择 —— 有 ANTHROPIC_API_KEY 用真 Claude，无则用确定性 Mock（按 prompt 中 `[TASK: xxx]` 标签路由预置输出）。所有演示与测试必须能在 Mock 下跑通。
2. **数据层零依赖**：competency / rag / storage 只用 stdlib；langgraph / anthropic 是引擎层依赖。
3. **能力框架驱动**：个性化逻辑以 `data/frameworks/*.json` 为准，改框架不改代码。
4. **工具调用留痕**：所有工具调用追加到 `state["tools_called"]`，作为评审证据。
5. **教学友好**：不给答案给提示、错因分析、同类训练；输出标注「辅助建议，最终判断以你为准」。
6. **数据合规**：只用自建模拟数据；真实数据需授权脱敏；重大结论人工确认。

## 代码约定
- 全中文注释与输出；Windows 编码统一 UTF-8（写文件显式 encoding，CLI 用 sys.stdout.reconfigure）。
- 数据模型用 dataclass + from_dict/to_dict；JSON 文件反序列化后必须校验。
- 测试用 unittest：`python -m unittest discover -s tests -v`。
- 运行 CLI：`python -m selfgrow.cli.main [--mode auto|interactive]`。

## 架构速查
```
START → diagnose → plan → learn → spar → review → route
route: 计划未完→learn(下周) | 计划完未完复测→diagnose(reassess)→plan(adjust)→learn | 复测完→graduate→END
```
- checkpointer=InMemorySaver，thread_id=learner_id → 断点续学
- 节点调用工具由代码决定，LLM 负责内容生成（保证 Mock/真模型行为一致）

## git 约定
每阶段一个 commit（P0 脚手架 → P1 数据层 → P2 LLM+RAG+存储 → P3 图 → P4 CLI → P5 文档），message 前缀：chore/feat/docs/test。
