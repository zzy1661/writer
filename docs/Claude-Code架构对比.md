# 架构对比 — writer-agent vs Claude Code

**Date**: 2026-07-06
**Status**: 一次性分析,非活跃维护文档(若 Claude-Code 架构演进需重跑)
**作者**: arch-optimizer (基于 [Claude-Code-Source-Study](https://...) 项目源码解析)

---

## 概述

本对比基于本地参考项目 `~/Desktop/sources/Claude-Code-Source-Study/docs/` 的 34 章源码深度解析(总 43 篇 Markdown,2.7 MB),抽取其中 11 个可复用架构模式、12 个关键设计决策、9 个扩展点,与 writer-agent 的四层架构做横向 gap 分析。

**核心结论**:我们对齐了 Claude Code 的 6 个核心模式(Protocol-as-slot / AsyncGenerator 循环 / DI 边界 / Done 事件流 / Tool 命名 kwarg / Markdown-as-config),但**缺失 3 个对未来扩展性关键的能力**:Hooks 协议 / state.transition 状态机 / Sub-agent 隔离。本文档是这些差距的优先化路线图。

---

## 对比方法论

| 维度 | Claude Code 做法 | writer-agent 做法 | 数据来源 |
| --- | --- | --- | --- |
| 循环核心 | `query()` AsyncGenerator + `while(true) state.transition` 7+ continue 站点 | `run_engine` AsyncIterator[Event] + `match action.action_type` 单层 dispatch | [05-QueryEngine与对话主循环.md](~/Desktop/sources/Claude-Code-Source-Study/docs/05) |
| DI 边界 | `QueryDeps` 4 个口子(`callModel`/`microcompact`/`autocompact`/`uuid`) | `EngineDeps` 5 字段 + 3 方法(router / story_consultant / tool_registry / tool_runtime + route / run_workflow / rebind_tool_runtime) | [05](#) / `src/writer/engine/deps.py` |
| 路由 | `RuleBasedRouter` + `LlmRouter` 同一 Protocol 下;`CompositeRouter` rule-first + LLM fallback | `RuleBasedIntentRouter` + `LlmIntentRouter` + `CompositeRouter`(本会话 M5/M6 已对齐 production_deps 接受 `primary_router` kwarg) | [15](#) / `src/writer/routing/` |
| 扩展点 | 27 个 Hook 事件 + Markdown frontmatter 协议同构(Skill/Agent/Command/OutputStyle)+ Plugin manifest | 仅 SKILL.md frontmatter;`writer/hooks/` 未实装;`writer/commands/` / `writer/agents/` / `writer/output_styles/` 空缺 | [20-Hooks系统.md](~/Desktop/sources/Claude-Code-Source-Study/docs/20) / [21](#) |
| 配置 | 5+1 层优先级(user/project/local/policy/managed)+ TRUSTED_SETTING_SOURCES + SAFE_ENV_VARS | 单一 Pydantic BaseSettings | [03-配置体系与企业MDM.md](~/Desktop/sources/Claude-Code-Source-Study/docs/03) |
| 工具注册 | 三层漏斗(编译期 DCE / 模块加载期 env / 运行时 isEnabled)+ deny 规则 | `ToolRegistry` 名字索引;无运行时启用/禁用 | [10-工具协议-注册与-ToolSearch.md](~/Desktop/sources/Claude-Code-Source-Study/docs/10) |
| 错误恢复 | 7 层(withRetry / FallbackTriggeredError / 413 三级恢复 / MaxOutputTokens 两阶段 / Stop hook 阻塞 / withhold-recover / microcompact) | `except ToolError` + `except Exception` 两层;无 max_output 升级;无 413 恢复 | [05](#) |

---

## 关键差距总览(TL;DR)

按严重度排序,**越靠前越该立项**:

| # | 差距 | Claude Code 做法 | 我们的现状 | 严重度 | 影响 |
| --- | --- | --- | --- | --- | --- |
| 1 | **Hooks 系统缺失** | 27 生命周期事件 + 三层 Event/Matcher/Hook + exit code 语义 | 0 个事件点,Plugin/Agent 协作无扩展接口 | 🔴 Major | 阻塞 Plugin / Sub-agent / 预写校验 |
| 2 | **state.transition 显式状态机** | `while(true) + state.transition`,7+ continue 站点 | `try/match/yield`,错误恢复靠 try/except | 🔴 Major | 阻塞上下文压缩 / max_tokens 升级 / Sub-agent 续转 |
| 3 | **Sub-agent 隔离 + Fork vs Fresh** | 默认全隔离 + opt-in 共享;fork 复用 prompt cache | 没有 sub-agent;`workflows/{write,review}_chapter.py` 还是 stub | 🔴 Major | 阻塞多角色并行(编剧/校对/审核) |
| 4 | **Markdown frontmatter 协议同构** | Skill/Agent/Command/OutputStyle 共用一套加载逻辑 | SKILL.md 对齐了,其他都没对齐 | 🟠 Major | 影响未来 Plugin 系统可发现性 |
| 5 | **多层配置(5+1 优先级链)** | user/project/policy/managed + TRUSTED_SETTING_SOURCES | 单层 Pydantic Settings | 🟠 Major | 影响未来企业 MDM / Plugin 市场 |
| 6 | **Tool 注册表运行时过滤** | 三层漏斗 + deny 规则 + isEnabled | 只有名字索引,运行时启用/禁用无 | 🟡 Minor | 影响 Plugin 粒度的工具控制 |
| 7 | **极简 Store(subscribe/unsubscribe)** | 35 行 getState/setState/subscribe | 没有 reactive Store,EngineSession 是 mutable dataclass | 🟡 Minor | 影响未来 IDE / Web UI 实时渲染 |
| 8 | **Migration-as-Code** | 11 个独立幂等函数,文件名即语义 | 没有迁移框架 | ⚪ Backlog | 影响模型升级 / schema 演进 |
| 9 | **CLI 启动快路径(编译期 DCE)** | cli.tsx 13 条 fast-path 在动态 import 之前 | 全部 eager import | ⚪ Backlog | 影响冷启动体感(我们 < 1s,收益低) |
| 10 | **EngineDeps 端口开始膨胀** | QueryDeps 只 4 个口子 | 我们 5 字段 + 3 方法 | 🟡 Minor | 信号:是时候抽象下一层 |

---

## 🔴 三大 Major 差距详解

### 1. Hooks 系统(架构模式 #20)

**Claude Code 做法**:
- 27 个事件分 6 大类(工具 / 会话 / 权限 / Agent / 上下文 / 环境)
- 三层配置 `Event → Matcher → Hook`;Matcher 三种模式(精确 / 多值 / 正则)
- 4 种 Hook 类型 discriminated union:`command`(spawn shell) / `prompt`(Haiku + json_schema) / `agent`(多轮验证) / `http`(POST 外部,SSRF 防护)
- Shell 退出码语义化:`0`=成功,`2`=阻塞性(语义因事件而异:PreToolUse 阻止工具 / Stop 让模型继续 / UserPromptSubmit 擦除原始 prompt),其他=非阻塞
- JSON 输出协议:`continue` / `suppressOutput` / `stopReason` / `decision` / `updatedInput` / `additionalContext`
- `PreToolUse.updatedInput` 让 Hook 能改写 AI 的工具调用
- Stop hook 不是"会话结束钩子"而是"会话愿不愿意结束的决策钩子"
- Fast Path 优化(内部 callback 跳过 telemetry 70% 提速)

**我们的现状**:`writer/skills/__init__.py:9` 仅 `__all__: list[str] = []` 占位,没有任何事件 hook。

**为什么是 Major**:未来 Plugin 系统、Sub-agent 协作、长任务中断、pre-commit 校验、敏感章节拦截——**全部依赖 Hooks**。没有 Hooks,Plugin 写不出,Sub-agent 串不起来,连"写作前检查敏感词"这种基础需求都做不了。

**建议做法**(优先级 2,见末尾行动矩阵):
- 新建 `writer/hooks/` 子包,定义 `HookEvent` Literal(挑本项目必要的:`PreToolUse` / `PostToolUse` / `PreWorkflow` / `PostWorkflow` / `Stop` / `SessionStart` / `SessionEnd`)
- 三层配置:`~/.writer/settings.json`(user)+ `./.writer/settings.json`(project)+ managed policy
- 先实现最关键的 `Stop` hook(让 Sub-agent 决定是否结束)与 `PreToolUse` hook(敏感 Tool 拦截)
- 复用现有 `Tools.security_constraints` 模式而不是发明新 DSL

### 2. state.transition 显式状态机(架构模式 #5 query loop)

**Claude Code 做法**:
- `while(true)` + `state.transition` 显式状态机
- 7+ 个 continue 站点:`collapse_drain_retry` / `reactive_compact_retry` / `max_output_tokens_escalate` / `stop_hook_blocking` / `token_budget_continuation` / `next_turn`
- 每个 continue 站点写一份**新 state**,但保留 `transition.reason` 给下一轮判断
- 错误恢复 7 层:`withRetry`(前台/后台区分重试 / 529 三连 fallback / persistent retry 5 分钟退避 + 30s 心跳)→ `FallbackTriggeredError`(剥离 thinking 签名)→ 413 三级恢复(drain → reactive compact → surface)→ MaxOutputTokens 两阶段(8k→64k 升级 + 3 轮 "no apology" 续写)
- 消息预处理管线按成本递增:`snip → microcompact → context collapse → autocompact`
- `withhold-recover` 模式:可恢复错误不立即 yield,等流结束尝试恢复

**我们的现状**:`engine/loop.py` 用 `match action.action_type` 单层 dispatch + 顶层 `try/except`。错误恢复只有 `except ToolError` + `except Exception` 两层。

**为什么是 Major**:当前只支持"成功 → Done"或"异常 → aborted"两条路径。一旦未来需要:
- 上下文压缩重试(413 → drain → reactive compact → surface)
- max_output_tokens 升级(8k → 64k + 3 轮续写)
- Stop hook 阻塞(hook 说"再想想"就把反馈塞成 user message 继续 turn)
- token_budget_continuation(预算耗尽时降级到低质量模式继续)

——都需要 `state.transition` 机制。当前架构会让这些功能被迫改 `_engine_loop` 主循环,违反"engine 包严格 5 文件布局,新增能力只通过 `EngineDeps` 扩展"原则(见 [备忘 16 §408](技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md))。

**建议做法**(优先级 1):
- 在 `_engine_loop` 引入新一代 `EngineState`(注意:**不是**之前 m4 删除的那个老 EngineState —— 老的是空 mutable dataclass,新的是 frozen transition 标记)
- 形态参考:
  ```python
  @dataclass(frozen=True)
  class EngineTransition:
      """Why the previous iteration asked to continue (read by next iteration)."""
      reason: Literal["ok", "tool_error", "ctx_overflow", "stop_blocked", "next_turn"]
      payload: dict[str, Any] = field(default_factory=dict)

  @dataclass(frozen=True)
  class EngineLoopState:
      ctx: EngineContext
      transition: EngineTransition  # not Optional
      tool_calls: int = 0
      compacted_segments: int = 0
  ```
- 注意:`transition.reason` 必须 frozen,否则会被下一轮意外修改导致状态污染

### 3. Sub-agent 隔离 + Fork vs Fresh(架构模式 #6 + #14)

**Claude Code 做法**:
- `createSubagentContext()` 默认全隔离 + opt-in 共享
- 默认 `setAppState` 是 no-op,但 `setAppStateForTasks` 必须穿透根 Store 防 PPID=1 僵尸进程
- `runAgent()` 是 6 阶段 AsyncGenerator:① 模型解析多级 fallback → ② Fresh vs Fork 两种消息构建 → ③ omitClaudeMd 每周省 5-15 Gtok → ④ createSubagentContext 默认全隔离 + opt-in 共享 → ⑤ recordSidechainTranscript 增量落盘支持崩溃恢复 → ⑥ finally 释放一切(killShellTasksForAgent)
- Fork Subagent 用 `isInForkChild()` 消息扫描 + `querySource` 持久化双机制防递归 fork
- 三条护 cache 守则:① 丢掉闭包 `forkContextMessages`(否则 cache key 漂移)② 用 `canUseTool` callback 而非 `tools:[]` 拒绝工具(否则 cache 失效)③ 不要设 `maxOutputTokens`(破坏 thinking config cache key)
- 工具过滤三层漏斗(全局禁止 → 异步白名单 → Agent 定义级)
- MCP 工具 `mcp__` 前缀无条件穿透

**我们的现状**:`workflows/write_chapter.py` 和 `review_chapter.py` 是 stub,只 yield 字符串提示文案(本会话 m27 修复后改了文案但实质未变)。没有 Sub-agent 调度、没有 prompt cache、没有 sidechain transcript、没有 fork vs fresh 双模式。

**为什么是 Major**:长篇小说写作本质就是**多角色协作**(编剧 / 校对 / 历史 / 审核),目前 stub 不能并发、不能复用 prompt cache、不能崩溃恢复。这是项目从"CLI demo"走向"能写完整小说"的核心能力。

**建议做法**:
- 把 `_DefaultEngineDeps.run_workflow` 升级为 `WorkflowStarter.start(name, ctx, *, fresh=True)` AsyncGenerator
- 引入 `SubagentContext` dataclass 隔离所有 per-call 状态
- 第一次实装就用 LangGraph(LangGraph 自带 fork / checkpoint / message persistence),跳过自研
- 参考 Claude Code 的 `omitClaudeMd` 机制做 Sub-agent prompt 裁剪(节省 token)

---

## 🟡 Minor 差距详解

### 4. Markdown frontmatter 协议同构(架构模式 #21)

**Claude Code 做法**:`Skill / Agent / Command / OutputStyle` 共用一套加载逻辑(`loadMarkdownFilesForSubdir` 并行加载 → 按优先级去重 → memoize + clear 失效)。文件名当默认 key,frontmatter 覆盖元数据。**协议同构是核心胜利**——所有扩展点都是".claude/ 子目录里放个 markdown 就生效"。

**我们的现状**:`SKILL.md` 用 markdown frontmatter,但 `writer/commands/` / `writer/agents/` / `writer/output_styles/` 都没有。

**建议做法**:先实现 `writer/skills/loader.py` 共享加载器,SKILL.md / future Command / future Agent 都跑同一份加载逻辑。文件名当默认 key,frontmatter 覆盖元数据。

### 5. 多层配置(5+1 优先级链)

**Claude Code 做法**:5+1 层有序数组定义优先级(user / project / local / policy / managed),标量覆盖 + 数组拼接去重,`TRUSTED_SETTING_SOURCES` 白名单,`SAFE_ENV_VARS`,删除重建 1700ms grace period。

**我们的现状**:`writer/config/settings.py` 单一 Pydantic BaseSettings,无多源。

**建议做法**:等需要时再做。当前 `.env` 单层够用,但未来 Plugin 市场 / 企业 MDM 部署需要多层。

### 6. Tool 注册表运行时过滤

**Claude Code 做法**:三层漏斗(单一 `getAll*()` 入口 + 编译期 DCE + 模块加载期 env + 运行时 `isEnabled()`),deny 规则过滤叠加,按名称排序保证 Prompt Cache 稳定性。

**我们的现状**:`writer/tools/registry.py` 只有名字索引,无运行时启用/禁用。

**建议做法**:加 `ToolRegistry.list(enabled_only=True)` + `ToolRegistry.disable(name)`,为未来 Plugin 系统的"用户禁用某 Tool"留接口。

---

## ✅ 已对齐的部分(8 项)

| Claude Code 模式 | 我们的实现 | 评价 |
| --- | --- | --- |
| **Protocol-as-slot** | `IntentRouter` Protocol + `RuleBasedIntentRouter` / `LlmIntentRouter` / `CompositeRouter` | ✅ 完美对齐(本会话 M1-M6 修复后甚至更好) |
| **AsyncGenerator 循环核心** | `run_engine` AsyncIterator[Event] | ✅ 对齐 |
| **DI 边界** | `EngineDeps` Protocol + `_DefaultEngineDeps` + `production_deps()` | ✅ 对齐(M6 后 Protocol-only stub 也工作,见 `test_session_set_project_root_with_protocol_only_deps`) |
| **Done 分支事件流** | 7 个 `DoneReason`(本会话 M4 修复后 ErrorEvent 加 traceback 字段) | ✅ 对齐 |
| **Tool 命名 kwarg 协议** | builtin Tools 全部 `*, path: str` 模式 | ✅ 对齐(CLAUDE.md 备忘 13 明确要求) |
| **structured output** | `AgentAction` Pydantic BaseModel + `model_config={"frozen": True}` | ✅ 对齐(甚至比 dataclass 更适合 LLM structured output) |
| **Markdown-as-config** | SKILL.md frontmatter 协议 | ✅ 部分对齐 |
| **复合 router(rule-first + LLM fallback)** | `CompositeRouter(primary=..., fallback=...)` | ✅ 对齐(M5 修复后 `production_deps` 接受 `primary_router` kwarg,见 `test_production_deps_respects_explicit_primary_router_*`) |

---

## ❌ 不需要借鉴的(领域差异)

| Claude Code 模式 | 我们为何不借鉴 |
| --- | --- |
| **Bun + 编译期 DCE / `feature()`** | 我们用 uv + Python,没有 Bun 的 `feature()` 编译期门控;运行时 DCE 收益有限 |
| **Ink + Yoga 终端 UI** | 我们用 prompt_toolkit,REPL 已够用 |
| **MCP server 双向暴露** | 除非未来要被外部程序(VSCode 插件等)调用,本项目无此需求 |
| **Bridge IPC(跨设备 resume)** | 小说写作无"手机接管电脑 session"的场景 |
| **完整的权限系统(deny > ask > allow + 熔断器)** | 写小说不是执行 shell,权限风险面完全不同 |
| **Sub-second 启动优化** | 我们的启动 < 1s(uv managed venv),无需 DCE |

---

## 行动建议

### 优先级 1:`state.transition` 状态机(Medium effort, High impact)

**理由**:当前 `engine/loop.py` 是单层 match + try/except,未来要做上下文压缩重试 / max_tokens 升级 / Sub-agent 续转时**必然要改**。现在引入干净的状态机比之后 refactor 便宜。

**第一步**:在 `engine/loop.py` 引入 `EngineTransition` + `EngineLoopState`(frozen),把所有 `yield Done` 的判断从"一次 yield 即终"改为"state.transition 决定是否继续"。

### 优先级 2:Hooks 协议骨架(Mini-MDE effort, H impact)

**理由**:未来 80% 的扩展能力(Plugin、Sub-agent、pre-tool 校验、Stop hook)都依赖 Hooks。先把 `writer/hooks/` 骨架搭好(事件 Literal + 加载器 + 一个示范 hook),未来实装成本陡降。

**第一步**:新建 `src/writer/hooks/{__init__,events,registry}.py`,定义 7 个事件 + matcher + 一个 `command` 类型 hook 的最小实装(参考 Claude Code 的 `[20]` 章节)。给一个示范 hook:`PreToolUse(safe_write_file)` 自动备份被写入的文件。

### 优先级 3:Sub-agent + LangGraph(High effort, High impact)

**理由**:多角色并行(编剧/校对/审核)是项目从"CLI demo"走向"能写完整小说"的核心。LangGraph 自带 fork / checkpoint / message persistence,直接用避免重造轮子。

**第一步**:把 `_DefaultEngineDeps.run_workflow` 升级为 `WorkflowStarter.start(name, ctx, *, fresh=True)` AsyncGenerator,引入 LangGraph `StateGraph` 实现 `write_chapter` 的 Plan-Execute-Review 三节点。**这次实装会自然把 Hooks 串起来**。

### 不做

- **Sub-second 启动优化**:启动 < 1s,收益不抵成本
- **MCP server 暴露**:除非有外部调用方需求
- **Bridge IPC 跨设备**:无场景
- **完整权限系统**:风险面不同,无需 deny > ask > allow 链

---

## 参考资料

### 主要来源

- `~/Desktop/sources/Claude-Code-Source-Study/docs/00-目录与阅读指引.md` — 全书导读 + 架构图谱
- `~/Desktop/sources/Claude-Code-Source-Study/docs/01-项目全景与四种入口形态.md` — CLI / REPL / SDK / Headless 四种入口
- `~/Desktop/sources/Claude-Code-Source-Study/docs/05-QueryEngine与对话主循环.md` — 对话主循环
- `~/Desktop/sources/Claude-Code-Source-Study/docs/14-Agent系统与SubAgent调用.md` — Agent 系统
- `~/Desktop/sources/Claude-Code-Source-Study/docs/15-内置Agent设计模式.md` — 内置 Agent 模式
- `~/Desktop/sources/Claude-Code-Source-Study/docs/20-Hooks系统.md` — Hooks 系统
- `~/Desktop/sources/Claude-Code-Source-Study/docs/21-Skill-Plugin-OutputStyle三扩展点.md` — 三大扩展机制
- `~/Desktop/sources/Claude-Code-Source-Study/docs/34-架构模式总结.md` — 11 个可复用模式总结

### 项目内参考

- `CLAUDE.md` — 项目架构总览与设计约束
- `技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md` — 本项目 Agent 选型与 Engine 5 文件布局约束
- `tmp/architecture-reports/2026-07-05-initial-roadmap.md` — 本项目架构 review 初始报告(arch-optimizer 产物)
- `tmp/architecture-reports/2026-07-05-followup-after-fixes.md` — 修复后复跑报告

### 状态

- **arch-optimizer 落盘约定**:报告必须写入 `tmp/architecture-reports/YYYY-MM-DD-<slug>.md`(gitignored scratch space,详见 `.gitignore:19`),不可写 `docs/` 或其他 tracked 路径。
- **本文档例外**:本次对比由用户显式请求写入 `docs/`(非 agent 自动行为)。