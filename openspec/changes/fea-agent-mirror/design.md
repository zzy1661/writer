## Context

`writer-agent` 当前的"咨询师"体系位于 `src/writer/roles/`：

- `StoryConsultant`（兜底，GENRE="other"）+ 3 个题材子类（`HistoryConsultant` / `XuanhuanConsultant` / `RomanceConsultant`）
- 每个类一个 `_draft_outline_with_llm()` 方法，**唯一的差别是 `GENRE` classvar 和对应的 `ChatPromptTemplate`**
- `production_deps(genre=...)` 按 `_GENRE_CONSULTANT` 字典硬选 → `_consultant_for_genre()` 工厂
- `EngineDeps.story_consultant` 单一字段承载"当前题材的咨询师"

`prompts/identity.py` 定义 4 句系统身份句（"你是…编剧顾问"），`prompts/consultants.py` 用 `ChatPromptTemplate` 拼装；`prompts/registry.py` 用 `PromptKey(role, genre)` 二维索引。

`prompts/router.py::COMMAND_AGENT_TEMPLATE` 是**路由 LLM** 的 system prompt，**与 4 个题材咨询师无关**——它是 router 自己用的；当前 `LlmIntentRouter` 只把"可用斜杠命令 + 状态机"塞给 LLM 让它分类。

`.writer/agents/` 目录在 `src/writer/project/workspace.py:170` 创建为 `.gitkeep` 占位，但**没有任何镜像、扫描、实例化逻辑**——属于"目录命名对标 Claude Code，实际管线未接"。

约束：
- `writer new` 的"镜像内置 + 项目可改"路径已经有 precedent：`writer.skills._shipped/<cmd>/SKILL.md` → `<project>/.writer/skills/<cmd>/SKILL.md`（per `chg-markdown-skills`）
- `SkillRegistry` 的 last-write-wins + `BUILTIN_SKILL_SOURCES` 元组 + sha256 漂移检测已经在 `chg-project-skills` 里固化
- `EngineContext` 当前不带 genre/agent 字段（per `fea-genre-aware-init` 决定）—— 题材信息通过 `EngineDeps.story_consultant` 间接体现
- 4 层架构 + 兼容层稳定，不动

Stakeholders：
- 用户：想用更直观的 agent 命名 + 像 Claude Code 一样 LLM 调度
- 项目：避免 consultant / agent 双名长期共存造成认知负担
- 未来扩展：增加新题材 / 自定义题材专才不需要改核心代码

## Goals / Non-Goals

**Goals:**
- 把 `consultant` 全部命名为 `agent`（干净 break，no alias），让语义对齐 Claude Code sub-agents
- 实现 4 个内置 agent 的 Claude Code 格式 markdown（YAML frontmatter + body），让 `writer new` 镜像到项目的 `.writer/agents/`
- 实现 `AgentRegistry`：启动时扫 `.writer/agents/`，last-write-wins（项目覆盖内置）
- 升级 `IntentRouter`：让 `LlmIntentRouter` 看到 agent descriptions 后由 LLM 自助选 agent
- 新增 `kind="agent"` 派发分支到 engine loop，复用现有 `answered` DoneReason
- 保持 `EngineContext` 不变（不引入 agent 字段），与 genre 注入模式对称
- 提供与 `shipped-skills` 平行的 `shipped-agents` 能力契约

**Non-Goals:**
- 不为 agent 强制执行 tool allowlist（YAML `tools:` 字段本次只 parse 不 enforce，留给未来 multi-agent orchestration）
- 不引入 LLM 编排 multi-agent（每个 agent 仍是单 LLM call）
- 不动 `EngineContext`（agent 信息走 `EngineDeps.story_agent`）
- 不动 `SkillRegistry` / `DirectiveRegistry` / skill 相关的任何代码
- 不为旧项目提供自动迁移脚本（`writer new` 之前的项目启动时 fallback 内置）
- 不删 `writer/agent/` 兼容包（保留 `IntentRouter` / `AgentAction` re-export，只删 `NovelAgent` 旧名）
- 不引入新的 LLM provider / 不动 `LLMToolLoop`
- 不改 `production_deps()` 现有参数 shape（保留 `genre=` / 新增内部 `agent_registry` 字段）

## Decisions

### 1. 干净 break vs 保留 alias

**决定：干净 break，删所有 consultant 别名。**

依据：
- 用户明确选择"干净重命名"（不再保留 deprecated alias）
- `agent/__init__.py:34` 的 `NovelAgent = StoryConsultant` 是历史包袱，删了反而更干净
- `WriterCommandAgent = RuleBasedIntentRouter` 是另一段历史——本次只删 consultant 相关 alias，routing alias 保留（不影响用户感知）
- 干净 break 让"consultant"字符串在 grep 结果里 0 命中，codebase 状态单一

**替代方案**：保留 `StoryConsultant` 为 `StoryAgent` 的 deprecated alias + warning log。**否决**：用户主动选择 break，引入 alias 反而增加维护负担。

### 2. Agent 文件格式：YAML frontmatter + body

**决定**：每 agent 一个 `.md`，顶部 YAML frontmatter + 底部 markdown body。

```markdown
---
name: history
description: |
  历史题材编剧。专长把虚构人物嵌入真实朝代与历史事件...
  适合处理「朝代背景」「年表顺序」「史实考证」类任务。
genre: 历史
tools: chapter_locate
---

# 历史编剧 Agent

你是长篇中文网文「历史题材」的编剧顾问...
```

依据：
- 完全对齐 Claude Code `.claude/agents/architecture-optimizer.md` 格式
- `description:` 是 LLM 调度决策的关键字段——必须自然语言、说明"何时该用我"
- `genre:` 保留是为了 prompt lookup（`PromptKey(role="outline", genre=...)`）；**不是 dispatch 决策字段**
- `tools:` 本次只 parse 不 enforce；预留未来 multi-agent tool 隔离
- 用 markdown（不是 YAML 全文）的好处：body 可写多行 system prompt，YAML 解析不会卡格式

**替代方案 A**：纯 markdown body，无 frontmatter。**否决**：失去 LLM dispatch 的语义基础（必须 description 才能让 LLM 选）。
**替代方案 B**：每 agent 一个子目录（含 SKILL.md + references/）。**否决**：与 SKILL/directive 路径重复；agent 是"独立单元"不是"工作流脚本集"。

### 3. AgentRegistry 覆盖语义：last-write-wins

**决定**：项目 `<root>/.writer/agents/<name>.md` 覆盖内置 `_shipped/<name>.md`，**重复 name 抛 `AgentRegistryError`**（项目 vs 项目、内置 vs 内置重名都抛）。

依据：
- 与 `SkillRegistry` 完全一致（per `chg-project-skills` 决定）
- 重复 name 是配置错误，应该 fail loud
- 与 skill 不同：skill 是 `command` 维度（一个命令对应一个 skill），agent 是 `name` 维度（一个 name 一个 agent）

**替代方案**：内置优先，项目只能"扩展"不能"覆盖"。**否决**：用户改 description 还想立即生效，需要覆盖语义。

### 4. IntentRouter 改造：agents 嵌入 router 状态

**决定**：`IntentRouter.route()` 协议不变（仍是 `route(user_input, project_state) -> AgentAction`），但实现层（`LlmIntentRouter`）的 system prompt 同时注入：
- 可用斜杠命令列表（与现有相同）
- 可用 agent descriptions（每条 ≤ 200 字符截断，总数 ≤ 16 防 prompt 爆炸）
- 当前项目状态（`project_state`）

LLM 输出 schema 增 `target_agent: str | None` 字段：
- 若 LLM 选 slash → `kind="command"`, `command="/..."`, `target_agent=None`
- 若 LLM 选 agent → `kind="agent"`, `command=None`, `target_agent="history"`
- `RuleBasedIntentRouter` 不变（仅命中 slash → command）

依据：
- 沿用 router 协议（`route() -> AgentAction`）保持 engine 集成面不变
- `LlmIntentRouter` 已经用 LLM 决策——让它"看到 agent 列表"是自然扩展
- `RuleBasedIntentRouter` 不动：用户能"用斜杠精确触发"的能力保留
- description 截断 + 上限防 LLM context 爆炸

**替代方案 A**：另开一个 `AgentRouter` 独立组件。**否决**：与 router 协议冗余，组件数↑1 维护面↑。
**替代方案 B**：让 LLM 完全控制 dispatch（去掉 slash 列表只看 agent descriptions）。**否决**：slash 列表是用户精确触发的路径，删了破坏可预测性。

### 5. AgentAction shape 扩展：kind 字段

**决定**：`AgentAction`（Pydantic BaseModel, frozen）增 2 字段：

```python
class AgentAction(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_type: ActionType
    command: str | None
    args: str
    target_agent: str | None = None      # NEW
    kind: Literal["command", "agent"] = "command"  # NEW, default preserves back-compat
```

依据：
- `kind` 默认 `"command"` 让现有所有调用点 zero-diff（`AgentAction(command="/大纲", args="...")` 仍合法）
- 真正新增的 `target_agent` 是 nullable，不传就是 None
- `kind="agent"` 是新 code path；engine loop 新增 `case "agent"` 分支

**替代方案**：用单一 `command: str` 字段，agent name 走 `/` 前缀（如 `/history`）。**否决**：与 slash 命名空间冲突；语义模糊（`/history` 是 skill 还是 agent？）。

### 6. Engine loop 新增 case "agent"

**决定**：在 `_engine_loop` 的 dispatch match 上加 `case "agent"`：

```python
case "agent":
    agent_name = action.target_agent
    agent = deps.agent_registry.get(agent_name)  # raise if missing
    consultant = deps.story_agent
    async for chunk in _run_consultant_with_agent(consultant, agent, ctx, deps):
        yield chunk
    yield Done(reason="answered", payload={"agent": agent_name, ...})
```

依据：
- 复用现有 `answered` DoneReason（不新增 DoneReason，避免膨胀 enum）
- 复用 `EngineDeps.story_agent`（暂时所有 agent 共用一个 LLM call 路径 + 不同 system prompt）
- 末尾 payload 加 `agent` 字段让 CLI 渲染时能提示"由 history agent 回答"

**替代方案**：新增 `DoneReason="agent_answered"`。**否决**：与 `answered` 语义重复；现有 CLI 渲染分支会变复杂。

### 7. 镜像机制：importlib.resources + BUILTIN_AGENT_SOURCES

**决定**：完全镜像 `_seed_directives`（per `chg-markdown-skills`）的路径：
- `src/writer/agents/_shipped/<name>.md` 4 个内置 .md
- `BUILTIN_AGENT_SOURCES: tuple[tuple[str, str, str, str, str], ...]` 元组定义 `(name, mirror_filename, source_module, source_sha256, ...)`
- `_writer_meta_scaffolding` 加 `_seed_agents()` 调用，镜像到 `<project>/.writer/agents/<mirror_filename>`
- 用 `importlib.resources.files("writer.agents._shipped")` 拿打包后的路径
- 漂移检测：apply 阶段运行时 sha256 不匹配 → log warning

依据：
- 现有 precedent 已经在 `_seed_directives` 里落地，复制 pattern 比创新 pattern 风险小
- `BUILTIN_SKILL_SOURCES` 已经用同 pattern，可以参考

**替代方案**：用 entry_points 让 agent 通过 pip 插件分发。**否决**：与"项目级 .md 覆盖"语义不符；插件分发是 skill 路径。

### 8. EngineContext 不加 agent 字段

**决定**：`EngineContext` 维持现状（无 `agent` / `agents` 字段）；agent 信息通过 `EngineDeps.story_agent` 间接体现。

依据：
- 与 `fea-genre-aware-init` 的 genre 不进 EngineContext 对称
- engine loop 调 `deps.story_agent` 已经能拿到当前 agent 实例
- 加 EngineContext 字段会让 `prep_context()` 多一个 token 输出，无必要

### 9. Genre 参数保留

**决定**：`production_deps(genre=...)` 保留 genre keyword 参数（向后兼容），但内部**不再**用 genre 选 agent class——agent 选哪个由 LLM 决定。genre 字符串仍然传给 `StoryAgent` 内部，让 `PromptKey(role="outline", genre=...)` lookup 拿到对应的 ChatPromptTemplate。

依据：
- LLM 选的 `target_agent` 决定走哪个 *Agent 类（每个类一个 GENRE classvar）
- genre 字符串传给 *Agent 的 `__init__`，让它查对应 prompt
- 现有 `AGENT.md` 里的 `题材:` 行继续被 `EngineSession.refresh_project_genre` 读

**替代方案**：完全去掉 genre 参数，让 LLM 选 agent 后 agent 自己读 project state。**否决**：需要 LLM 多一轮查状态；genre 直传更便宜。

### 10. 测试策略

**决定**：
- `tests/test_workspace.py` 新增 `test_create_workspace_with_agents_*`（4 个文件存在 + 内容含 `description:` + body 非空）
- `tests/test_agent_registry.py` 新增（与 `test_skill_loader.py` 平行）：YAML 解析、last-write-wins、空目录、漂移检测
- `tests/test_intent_router.py` 增 agent dispatch 场景（mock LLM 返 `target_agent="history"` → ActionEvent kind="agent"）
- `tests/test_engine_deps.py` 增 `story_agent=` keyword + `agent_registry` 字段
- `tests/test_engine_loop.py` 增 `case "agent"` 分支

依据：
- 与 chg-project-skills 的测试分层对齐
- LLM dispatch 测试用 fake ChatModel 注入（per `MEMORY.md` 已知模式）

## Risks / Trade-offs

[`AgentAction` 增 `kind` + `target_agent` 字段是 breaking] → **Mitigation**：本项目所有 internal 调用点 ~25 处在 Phase A 同步改；外部 consumer（如果有）必须按 migration guide 改；clean break 是用户主动选择，无 deprecation window。

[`LlmIntentRouter` 改 system prompt 注入 agent descriptions 改变 LLM 输出分布] → **Mitigation**：router test fixture 补全 `target_agent` 字段；现有 router test 重写断言（不要只 expect 旧 shape）；apply 阶段先跑 `test_intent_router.py` 看 regression。

[`EngineSession.set_project_root` 复杂度↑（同时重建 directive_registry + agent_registry）] → **Mitigation**：apply 阶段补测试覆盖 `set_project_root` 序列；`EngineDeps.rebind_agent_registry` 协议与 `rebind_directive_registry` 对称（同一 pattern）；pre-conditions 不变。

[YAML 解析用 PyYAML / `yaml.safe_load` 增加间接依赖] → **Mitigation**：`langchain-core` 间接依赖 PyYAML（per `uv.lock` 当前），不用新增 dep；用 `yaml.safe_load` 不允许任意 Python 对象。

[4 个内置 agent 的 description / body 文本质量] → **Mitigation**：apply 阶段 4 个 .md 是手工撰写任务（不是 generate）；写完后用 `test_agent_registry.py` 校验 frontmatter 完整、body 非空、description 长度合理（50-300 字符）。

[mirror .md 时如果 `importlib.resources` 不可用会 silent fail] → **Mitigation**：复用 `_seed_directives` 的 try/except pattern（`Cannot locate shipped directives package: ...; directive seeding skipped`），写日志不阻断 REPL 启动。

[agent `tools:` 字段 parse 但不 enforce — 未来用户可能误以为已经在隔离 tool] → **Mitigation**：在 `shipped-agents` spec 里明确写"`tools` 字段本次为预留，apply 阶段不 enforce"；4 个内置 .md 不写 `tools:`（避免给用户错误印象）；README 加 warning。

## Migration Plan

**部署步骤**（apply 阶段顺序执行，详见 `tasks.md`）：

1. 创建 `src/writer/agents/` 包骨架（`__init__.py` + `protocol.py` + `registry.py` + `loader.py` + `builtin_sources.py` + `_shipped/` 4 个 .md）
2. 写 `Agent` Protocol + `AgentRegistry` + YAML 解析
3. 写 4 个内置 agent `.md`（YAML frontmatter + body）
4. 写 `_seed_agents()` 镜像函数 + 在 `_writer_meta_scaffolding` 接入
5. 改 `EngineDeps` 协议（增 `agent_registry` + `story_agent` 字段 + `rebind_agent_registry` 方法）
6. 改 `_DefaultEngineDeps` 实现（dataclass 字段 + 方法）
7. 改 `production_deps(genre=...)` 接受 `agent_registry=` 注入（默认 `built_agent_registry()`）
8. 改 `AgentAction`（Pydantic 增 `kind` + `target_agent`）
9. 改 `LlmIntentRouter` system prompt 注入 agent descriptions + 解析 `target_agent`
10. 改 `RuleBasedIntentRouter` 不动（命中 slash 走 command）
11. 改 `_engine_loop` 增 `case "agent"` 分支
12. **重命名阶段**（干净 break）：
    - `roles/story_consultant.py` → `roles/story_agent.py`（4 个文件全改）
    - `CONSULTANT_IDENTITY_*` → `AGENT_IDENTITY_*`
    - `prompts/consultants.py` → `prompts/agents.py`
    - `EngineDeps.story_consultant` → `story_agent`
    - `_consultant_for_genre` → `_agent_for_genre`（内部 helper 改名）
    - `_GENRE_CONSULTANT` → `_GENRE_AGENT`（内部常量改名）
    - 删 `agent/__init__.py:34` 的 `NovelAgent = StoryConsultant` 别名
13. 改 `EngineSession.set_project_root` 重建 agent_registry
14. 改所有调用点（~30 处 `from writer.roles import StoryConsultant` 等）+ 同步测试
15. 写 3 个新 test 文件（`test_agent_registry.py` / `test_intent_router.py` 增 / `test_engine_loop.py` 增）
16. 写 spec delta（`intent-routing` / `engine-loop`）
17. 写新 spec（`shipped-agents`）
18. 跑 `uv run ruff check src tests && uv run mypy src/writer && uv run pytest` 全绿
19. 跑 e2e：`printf "/历史 一个穿越到唐朝的程序员\n" | .venv/bin/writer` 验证 LLM dispatch agent

**回滚策略**：`git revert` 整个 commit。rename 是纯文本替换 + 删 alias，无数据迁移；rollback 后 codebase 等同于改造前。

**兼容窗口**：无。本 change 是 breaking，按 OpenSpec 流程 archive 时通过 `openspec sync` 同步到 main specs。

## Open Questions

1. **`AgentRegistry.get(name)` 找不到时 raise 什么 exception？** — 倾向新增 `AgentRegistryError(ValueError)`（与 `SkillRegistryError` 对称），engine loop 收到后 yield `ErrorEvent` + `Done(aborted)`。apply 阶段确认。

2. **`LlmIntentRouter` 注入 agent descriptions 时是 top-level 列表还是分组（per-genre）？** — 倾向 flat 列表（更简单，LLM 自己按 description 匹配），但要给 description 截断上限防 context 爆炸。apply 阶段定具体截断阈值（建议 200 字符 / 上限 16 个 agent）。

3. **`writer new` 创建项目时如果用户传了 `--genre 历史`，是否只镜像 `agents/历史.md` 还是全 4 个？** — 倾向全 4 个（用户后续能切题材；当前 active genre 走 LLM 选 agent，与镜像的 4 个文件解耦）。apply 阶段确认。

4. **内置 4 个 agent .md 内的 `description` 字段写多详细？** — 倾向"一段自然语言 + 列举 3-5 个具体适用场景 + 一行 '不适合 X'"，约 100-200 字符。apply 阶段 4 段手工撰写（不是 LLM generate）。

5. **未来 multi-agent 时 `tools:` 字段 enforce 的实现策略？** — 留 Open Question，未来 change 处理。本次 spec 明确"parse but not enforce"，不预留具体 enforcement 路径。
