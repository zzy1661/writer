# writer-agent 未修复 Bug 索引

> 一次性记录 2026-07-09 系统性 code-review 发现的 5 个未修复 bug。每篇按统一 8 节模板描述"现象—根因—影响—修复—验证—回归—风险",供后续 OpenSpec change proposal 直接引用。

## 元信息

| 项 | 值 |
|---|---|
| 创建日期 | 2026-07-09 |
| 关联基线 | 339 测试全过 + ruff clean + mypy clean |
| 关联 OpenSpec | (待 `openspec/changes/*` 提案落地) |
| 维护者约定 | 命名沿用 `技术难点与解决方案备忘/01-17` 编号体系;中文文档,与 `docs/` 现有风格一致 |
| 文档目的 | bug 修复前的工程共识沉淀 + OpenSpec 提案前置材料 + 测试盲区追溯 |

## 一句话定位

5 个 bug 在测试盲区下漏检 — **测试通过率(339/339)+ lint clean ≠ 无 bug**。本目录沉淀盲区分析的元数据,让"为什么 baseline 漏检"在文档里可追溯。

## 主索引表

| # | 标题 | 严重程度 | 状态 | 主要根因位置 | 修复复杂度 | 测试盲区 | 文档 |
|---|---|---|---|---|---|---|---|
| 1 | `tool_loop` 不重建,LLM 工具调用指向旧根目录 | 🔴 Blocker | 待修 | `src/writer/session/engine_session.py:136` | 中(Protocol 扩展 + 工厂注入) | 测试 `set_project_root` 后只断言 `tool_runtime`,从未断言 `tool_loop` | [01](./01-tool-loop-not-rebound.md) |
| 2 | `_initial_messages` 完全忽略 `AgentAction.answer`,directive body 不进 LLM | 🟠 Major | 待修 | `src/writer/llm/agent.py:281-292` | 中(system prompt 重写 + 双来源注入) | 测试断言 `_system_prompt()` 固定文本,从未断言 directive / agent body 是否拼入 | [02](./02-action-answer-ignored-by-tool-loop.md) |
| 3 | `review_chapter` 几乎永远走 deterministic,API key 配了也无效 | 🟠 Major | 待修 | `src/writer/workflows/review_chapter.py:265-288` | 低(单文件 fallback 路径调整) | 测试 `review_llm` 注入有覆盖,但不覆盖 production 默认路径(`deps.review_llm=None`) | [03](./03-review-chapter-always-deterministic.md) |
| 4 | 写入白名单字面值(`.writer/cache`)与匹配规则(`rel.parts[0]`)不一致 | 🟠 Major | 待修 | `src/writer/tools/builtin/file_tools.py:101-119` + `runtime.py:18-29` | 低(单函数实现替换) | 测试 fixture 全用顶层目录(`manuscript/...`),从不构造 `.writer/cache/x.md` | [04](./04-whitelist-vs-first-segment.md) |
| 5 | 工作流用 module-global 注入 deps,并发场景串线 | 🟠 Major | 待修 | `src/writer/workflows/write_chapter.py:372-402` + `review_chapter.py:81-101` | 高(LangGraph 节点签名 + 工厂 + 闭包注入) | 测试串行 `run()`,从不 `asyncio.gather` 两个 workflow | [05](./05-workflow-module-globals.md) |

## 优先级修复顺序

**4 → 3 → 1 → 2 → 5**(理由如下):

1. **先修 Bug 4 (quick win)**:单文件单函数实现替换,15 行内可完成,无 Protocol 扩展、无签名改造。修完直接覆盖 `.writer/cache` 写入场景,后续 bug 测试 fixture 也需要这条路径。
2. **再修 Bug 3 (复用现有 fallback)**:单文件一处 if 调整,可复用 `write_chapter._resolve_review_llm` (`src/writer/workflows/write_chapter.py:494-509`) 的 fallback 模式。改动小但效果显著(用户 API key 配了就能用 LLM 审核)。
3. **然后修 Bug 1 (Blocker,Protocol 改动可控)**:为 `EngineDeps` Protocol 加 `rebind_tool_loop` 方法,镜像现有 `rebind_tool_runtime` 模式。涉及 1 个 Protocol + 1 个 dataclass + 1 个 session 方法,模式已现成。
4. **接着修 Bug 2 (system prompt 重写)**:`_initial_messages` 重写为双来源(directive + agent)系统提示,需要新增 `directive_registry.get()` + `agent_registry.get()` 字段读取,但 loop.py 调用点不变。
5. **最后修 Bug 5 (LangGraph 改造)**:需要改造 `build_writer_graph` / `build_reviewer_graph` 接受 `deps` 参数,改 `add_node` 闭包注入,风险面最大(节点函数签名变化 + LangGraph 序列化兼容)。可放在最后以便前面 4 个修复产生的 fixture / 测试模式作为参考。

## 关联基线表

| 项 | 当前值 | 修复后保持 |
|---|---|---|
| 测试总数 | 339 | ≥ 339(每篇 §7 都有 NEW + MODIFY + e2e) |
| ruff | clean | clean |
| mypy | clean | clean |
| 已删 SKILL.md | `/续写` `/改` (per 2026-07-09 chg-remove-roles) | 保持已删 |
| shipped SKILL.md | 2 (`/大纲` `/目录`) | 保持 2 |
| builtin Tool 数 | 9 (file + analysis + locate + foreshadow) | 保持 9(Bug 4 仅改 `_check_whitelist` 实现,不增减 Tool) |
| `EngineDeps` Protocol 字段 | router / agent_registry / tool_registry / tool_runtime / directive_registry / tool_loop / prose_client / review_llm | Bug 1 新增 `rebind_tool_loop()` 方法;字段不变 |
| `_WORKFLOW_DEPS` / `_REVIEW_DEPS` 模块级变量 | 存在(写死的 module global) | Bug 5 修后移除 |

## 与其他文档的关系

- **架构图 / 命令流** → `docs/技术架构总览.md`(高层架构 + LangGraph 状态图)
- **历史决策备忘** → `技术难点与解决方案备忘/01-17/*.md`(选型理由 + 不做什么清单)
- **RAG 历史** → `docs/技术架构细节.md`(已归档,被 `技术架构总览.md` 取代)
- **OpenSpec 历史** → `openspec/changes/archive/*/`(已 apply 的变更,可参考任务拆分粒度)

## 命名 / 引用约定

- 代码引用:`src/writer/llm/agent.py:281-292` 反引号 + 行号区间
- 跨文档链接:`[Bug 3](./03-review-chapter-always-deterministic.md)` 短 slug,相对路径 + `./`
- 备忘引用:`备忘 07-工具注册与文件权限安全.md` 沿用 MEMORY.md 简称
- 代码块:` ```python ` 标签 + `# fix proposal` 注释
- 数据流图:ASCII box-arrow 风格,统一 `✓` / `✗` / `←` / `→` 符号,无 ANSI 颜色
- 测试用例表:类型列固定三选一 `NEW / MODIFY / DELETE`,末行必有 `e2e`

## 修复门槛

每篇 §7 末行要求手动验证:`uv run pytest` 全过 + `uv run ruff check src tests` clean + `uv run mypy src/writer` clean。

## 不在本次文档范围

- ❌ 实际修复代码编写(文档描述方案,实现另起 OpenSpec change)
- ❌ 创建 OpenSpec change proposal(后续 `/opsx:propose` 走流程)
- ❌ 修改 `openspec/specs/*` 的 delta(只在每篇 §8 风险与遗留里 cross-ref)
- ❌ 文档英文翻译(保持中文)