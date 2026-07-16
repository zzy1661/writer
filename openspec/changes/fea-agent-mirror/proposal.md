## Why

`writer-agent` 当前的"咨询师(consultant)"命名对标的是 Python 类继承 dispatch（`StoryConsultant` / `HistoryConsultant` / `XuanhuanConsultant` / `RomanceConsultant` 4 个类，按 `GENRE` classvar 硬选 prompt 模板）。这与 Claude Code `.claude/agents/` 的 sub-agent 范式（YAML frontmatter `description:` + markdown body，**父 LLM 读 description 决定委派**）语义不同——当前实现里没有"LLM 看到 agent 列表自助调度"这一步。

同时，`.writer/agents/` 目录在 `create_new_workspace`（`src/writer/project/workspace.py:170`）里已经被创建为占位 `.gitkeep`，但**没有任何镜像、扫描、实例化逻辑**——属于"目录命名了对标 Claude Code agents/，但实际管线没接"的悬挂设计。

这次要把"悬挂的 agents 目录"和"consultant 命名"两个独立的问题合并到同一个 change：
- 把 consultant 重命名为 agent（干净 break，no alias）
- 把 4 个内置 agent 用 Claude Code sub-agents YAML frontmatter 格式落 `.md`
- 让 `writer new` 镜像 4 个 agent 到项目的 `.writer/agents/`
- 让 writer 启动时扫 `.writer/agents/` 拿 description 列表给 LLM，LLM 自助调度

最终把"4 个题材变体"从**类继承硬选**变成**LLM 读 description 自由挑**——更贴 Claude Code 范式，也允许未来在项目里新增题材专才 agent 而不需改核心代码。

## What Changes

- **重命名（BREAKING）**：把代码里所有 `consultant` 改名为 `agent`
  - `src/writer/roles/story_consultant.py` → `roles/story_agent.py`
  - 4 个 `*Consultant` 类 → 4 个 `*Agent` 类（`StoryAgent` / `HistoryAgent` / `XuanhuanAgent` / `RomanceAgent`）
  - `CONSULTANT_IDENTITY_*` 常量 → `AGENT_IDENTITY_*`
  - `prompts/consultants.py` → `prompts/agents.py`
  - `EngineDeps.story_consultant` 字段 → `EngineDeps.story_agent`
  - `_GENRE_CONSULTANT` 字典 / `_consultant_for_genre()` helper 删除
  - `agent/__init__.py` 删 `NovelAgent = StoryConsultant` 别名
  - `production_deps(genre=...)` 参数保留 genre 字符串，但内部用 `AgentRegistry` 按 name 索引；改名后 `story_agent=` keyword
- **新增**：4 个内置 agent markdown 文件（Claude Code sub-agents 格式：YAML frontmatter + body）
  - `src/writer/agents/_shipped/{other,历史,言情,玄幻}.md`
  - 每个含 `name` / `description`（给 LLM 看的自然语言） / `genre` / `tools`（可选）/ `body`（system prompt）
  - 对应 4 个内置 Python `*Agent` 类的 `AGENT_IDENTITY_*` 内容
- **新增**：`src/writer/agents/` 包
  - `protocol.py`：`Agent` Protocol（name / description / genre / body / tools_allowlist）
  - `registry.py`：`AgentRegistry`（类似 `DirectiveRegistry`，last-write-wins：项目 `.writer/agents/` 覆盖内置 `_shipped/`，同命令名内置优先抛错 — 与 skills 对齐）
  - `loader.py`：YAML frontmatter 解析 + 项目级 `discover_project_agents(root)` + entry-point 插件 `discover_entry_point_agents()`
  - `builtin_sources.py`：`BUILTIN_AGENT_SOURCES` 元组（sha256 漂移检测，与 `BUILTIN_SKILL_SOURCES` 对称）
  - `_shipped/<name>.md`：4 个内置 .md
- **改造**：`IntentRouter` 协议扩展，把 `AgentRegistry` 注入 router
  - 路由决策表新增 `kind="agent"`（与现有 `command` 并列）
  - `RuleBasedIntentRouter` 不变（命中斜杠 → skill/dispatch）
  - `LlmIntentRouter` 改造：system prompt 同时注入"可用斜杠命令" + "可用 agent descriptions"；LLM 输出多一个 `target_agent` 字段
  - `AgentAction` 增 `target_agent: str | None` + `kind: Literal["command","agent"]` 字段（**BREAKING** shape change）
- **改造**：engine loop 新增 `case "agent"` 分支
  - 走 `EngineDeps.story_agent` 调对应 agent 的 LLM（暂时复用 `_draft_outline_with_llm` 路径）
  - 末尾 yield `Done(answered, payload={"agent": name, ...})`
- **改造**：`production_deps()` + `EngineSession.set_project_root`
  - 加 `agent_registry` 字段（与 `directive_registry` 对称）
  - `set_project_root` 时调用 `AgentRegistry.discover` 重建（项目级 .md 覆盖）
  - `rebind_agent_registry` 与 `rebind_directive_registry` 对称
- **改造**：`_writer_meta_scaffolding` (`src/writer/project/workspace.py:166`) 加 `_seed_agents()`
  - 镜像 4 个内置 `.md` 到 `<project>/.writer/agents/{other,历史,言情,玄幻}.md`
  - 用 `importlib.resources`（与 `_seed_directives` 路径对齐）
  - 仅在 `create_new_workspace` 路径触发；`create_workspace` 低层 API 不镜像
- **测试**：
  - `tests/test_workspace.py` 增加 `test_create_workspace_with_agents_*` 系列（4 个 .md 内容校验）
  - `tests/test_agent_registry.py` 新增（与 `test_skill_loader.py` 平行）
  - `tests/test_intent_router.py` 增 agent dispatch 场景
  - `tests/test_engine_deps.py` 增 `story_agent=` keyword + `agent_registry` 字段
  - `tests/test_engine_loop.py` 增 `kind="agent"` 分支
- **清理**：
  - 删 `_GENRE_CONSULTANT` / `_consultant_for_genre()`
  - 删 `agent/__init__.py` 的 `NovelAgent` 别名
  - 文档：`docs/技术架构细节.md` / `docs/命令与用户流程.md` 同步更新（如果存在 consultant 命名引用）

## Capabilities

### New Capabilities

- **`shipped-agents`**: 项目级 4 个内置 agent 镜像 + YAML frontmatter 契约。定义 `.md` 必填字段（`name` / `description` / `genre`）、mirror 行为（`writer new` 触发，project overrides 内置）、registry last-write-wins 语义。镜像层路径与 `shipped-skills` 对称，但格式不同——shipped-agents 是单 .md（YAML frontmatter 解析），不是 SKILL.md 子目录树。

### Modified Capabilities

- **`intent-routing`**: 当前 spec 定义 `AgentAction` 仅含 `command` / `args` / `action_type` 三元组。改造后 `AgentAction` 增 `kind: Literal["command","agent"]` + `target_agent: str | None`；`LlmIntentRouter` system prompt 注入 agent description 列表（最多 N 个，按 description 截断）；LLM 输出 schema 加 `target_agent` 字段。router 协议本身（仍是 `route() -> AgentAction`）不变，是**输入 + 输出 shape 扩展**。
- **`engine-loop`**: 当前 spec 定义 5 个 `Done.reason` 分支（`answered` / `command_pending` / `tool_completed` / `workflow_pending` / `ask_user` / `aborted`）。改造后 `ActionEvent` 增 `kind="agent"` 派发，命中后通过 `EngineDeps.story_agent` 调对应 agent → 末尾 yield `Done(answered, payload={"agent": target_agent, ...})`（复用现有 `answered` 分支，**不新增** DoneReason）。

## Impact

**影响文件**：
- **新增**：`src/writer/agents/{__init__,protocol,registry,loader,builtin_sources}.py` + `_shipped/{other,历史,言情,玄幻}.md`
- **重命名**：`src/writer/roles/{story,history,xuanhuan,romance}_consultant.py` → `*_agent.py`；`src/writer/prompts/consultants.py` → `agents.py`
- **修改**：`src/writer/engine/{deps,loop,session}.py`、`src/writer/routing/{intent_router,llm_router,rules}.py`、`src/writer/cli/main.py`、`src/writer/project/workspace.py`、`src/writer/agent/__init__.py`（删别名）
- **测试**：~30 处调用点同步改 + 新增 `test_agent_registry.py` 等 3 个新 test 文件
- **spec delta**：`openspec/specs/intent-routing/spec.md` + `openspec/specs/engine-loop/spec.md`（delta 形式）
- **新 spec**：`openspec/specs/shipped-agents/spec.md`

**不动的部分**（架构稳定区）：
- engine 状态机 / LangGraph 状态图 / 4 层架构 + 兼容层（删别名后 `agent/` 包只剩 routing 类的 re-export）
- `SkillRegistry` / `DirectiveRegistry` 基础设施
- `LLMToolLoop` / `safe_path()` 越界防护
- `chapter_summaries.json` 已有 schema
- `EngineContext`（**不加** `agent` 字段，agent 走 `EngineDeps.story_agent` 间接体现，与 genre 注入模式对称）

**迁移路径**：
- **干净 break**：无 deprecation alias。所有 external 引用 `from writer.roles import StoryConsultant` / `from writer.agent import NovelAgent` 立即 break，迁移文档在 `docs/` 同步更新
- **现有项目**：`writer new` 创建的项目无 `.writer/agents/*.md` → 启动时 `AgentRegistry.discover` 走"内置 only"路径，行为与改造前一致（按 genre 选 *Agent）
- **`writer new` 之后的新项目**：第一次 init 时镜像 4 个 .md 到 `.writer/agents/`，用户可立即改 description / body

**风险**：
- **High**：`AgentAction` 增 `kind` + `target_agent` 字段是 breaking — 任何外部消费者（外部脚本 / 测试 fixture）会立即 fail；本项目内部 ~25 处调用点必须同步改
- **Medium**：`LlmIntentRouter` 改 system prompt 注入 agent descriptions，会改变现有 LLM 输出分布；router test fixture 需要补全 `target_agent` 输出
- **Medium**：`EngineSession.set_project_root` 现在要同时重建 directive_registry + agent_registry，复杂度↑；apply 阶段需要补全测试覆盖
- **Low**：YAML frontmatter 解析用 `yaml.safe_load` 还是 `pyyaml`（依赖检查）；当前 `langchain-core` 间接依赖 PyYAML，可以直接用
- **Low**：内置 4 个 agent 内容的质量 — body 当前内容源自现有 `CONSULTANT_IDENTITY_*` 字符串，迁移即可；description 字段是新增内容，需要手工撰写 4 段（apply 阶段验收点）

**非目标**（apply 时务必保持）：
- 不为 agent 增加独立 tool allowlist 强制执行（YAML 写 `tools:` 但本次实现不 enforce，留给未来）
- 不引入 LLM 编排 multi-agent（单 agent 单 LLM call 即可）
- 不动 `EngineContext` 字段（agent 信息走 `EngineDeps.story_agent`）
- 不动 `StoryConsultant.draft_outline()` API shape（仅类名改）
- 不为旧项目提供自动迁移脚本（`writer new` 之前的项目不带 `.writer/agents/`，启动时 fallback 内置）
- 不删除 `agent/` 兼容包（保留 `IntentRouter` / `AgentAction` / `ActionType` re-export；只删 `NovelAgent` / `WriterCommandAgent` 旧名）
