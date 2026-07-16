## Context

当前状态(2026-07-05,前一次 change `add-llm-and-complete-engine-loop` 落地后):

- `src/writer/cli/main.py` 的 `run_repl()` 是 `while True` 循环,每次 `_read_line()` + `handle_repl_input()`。
- `handle_repl_input()` 把非框架命令(除 `/退出` `/帮助` `/状态`)转发到 `_run_engine(text, console)`。
- `_run_engine()` 每 turn 都新建 `EngineContext(session_id=str(uuid4()))` 和 `production_deps()`,导致:
  - session_id 每 turn 一个新 uuid,跨 turn 无连续性。
  - `EngineDeps` 每 turn 重建(`ToolRegistry` / `ToolRuntime` / `LlmIntentRouter` 全部重实例化)。
  - engine 的 `Interrupt` 事件 console.print 后就被丢弃,用户输入也不接续。
  - 没有 turn 历史,无法回看或注入未来 LLM context。
- `EngineSession` 在备忘 16 §"Engine 是无状态 AsyncGenerator" 第 374 行被显式预留: "会话级状态(对话历史、checkpoint、session 内存)属于 `EngineSession`(per 17 预留),不在 engine 内部。"
- 前次 change 完成了 `engine-loop` / `intent-routing` / `llm-provider` 三个 capability 的 spec,主 specs 已同步。本次加新 capability `engine-session`。
- 已有 spec `engine-loop` 提到 EngineContext 是 immutable 输入,frozen=True;本次不变它,只让 session 在外面持有跨 turn 状态。

约束:

- 不动 `EngineDeps` Protocol(`@runtime_checkable`,扩展只能加字段)。
- 不动 Engine Loop(无 `engine/` 改动)。
- 不引入持久化层(JSON/SQLite),跨进程不恢复。
- 不接 `ProjectState` S0-S5 推导(明确 out of scope,留给未来 change)。

干系人:

- REPL driver (`cli/main.py`): 是 EngineSession 的唯一拥有者;跨 turn 把 session 传下去。
- Engine Loop / LLM Router: 不感知 EngineSession,只看到每个 turn 的 `EngineContext`。
- 测试: 需要 mock session 创建,或注入 fake deps。

## Goals / Non-Goals

**Goals:**

- 落地 `EngineSession`:frozen identity (session_id + started_at)+ mutable state container。
- `run_repl()` 启动时建一个 session,跨所有 turn 复用。
- `session.deps` 一次性构造;`project_root` 变更时按需 rebuild `tool_runtime`(因为 `ToolRuntime` 持有 `project_root`)。
- `pending_interrupt` 在 Interrupt 事件触发时存入,在 Done 事件触发时清空。
- 下一轮 user_input 自动拼接 pending prompt,形成可观测的回路。
- `turns: list[TurnRecord]` append-only,只记录 user_input + done_reason + timestamp + turn_index。
- `project_state` 暂时保留字符串占位("S0"),但字段名稳定,留给未来接 `detect_state(root)`。
- 公共表面最小化:`from writer.session import EngineSession, TurnRecord`。

**Non-Goals:**

- 不接 ProjectState S0-S5 推导(留待独立 change)。
- 不持久化 session 到磁盘(跨进程不恢复)。
- 不让 EngineSession 影响 EngineContext 字段(EngineContext 仍是 per-turn frozen input)。
- 不实现 LangGraph checkpoint / Interrupt resume(per 14 范围)。
- 不让对话历史注入 LLM context(等 LLM 化 StoryConsultant 时单独决策)。
- 不改 `EngineDeps` Protocol 表面。
- 不重写 REPL 命令解析逻辑(`/init` `/大纲` `/退出` 等命令的语义不变,只是走 EngineSession 时 session_id 一致)。

## Decisions

### D1: `EngineSession` 用 dataclass(frozen=False,带属性控制)

**选择**: `EngineSession` 是 `@dataclass`(非 frozen),字段如下:

```python
@dataclass
class EngineSession:
    session_id: UUID = field(default_factory=uuid4)        # frozen
    started_at: datetime = field(default_factory=...)      # frozen
    project_root: Path | None = None                       # mutable
    project_state: str = "S0"                              # mutable (placeholder)
    deps: EngineDeps = field(default_factory=production_deps)  # mutable (tool_runtime swap)
    turns: list[TurnRecord] = field(default_factory=list)  # mutable (append-only)
    pending_interrupt: Interrupt | None = None             # mutable
```

frozen 与否分两组:`session_id` / `started_at` 通过"约定不修改"实现(测试断言);其他字段按需更新。

**理由**: 比"全 frozen + replace()"轻量;append-only turns 用 `list` 而非 `tuple` 自然;`_asdict()` 仍可序列化调试输出。

**备选**: 用 `pydantic.BaseModel` + `model_config = {"frozen": True}` + 显式 `model_copy(update=...)`。更严格但实现冗长,与项目里"dataclass 主、pydantic 只在边界"的惯例不一致。

### D2: deps 在构造时一次,tool_runtime 按需 rebuild

**选择**: `EngineSession.__post_init__` 调用 `production_deps()` 一次,存进 `self.deps`。`set_project_root(new_root: Path | None)` 方法:

1. 若 `new_root == self.project_root`: no-op。
2. 否则:更新 `self.project_root`;构造新的 `ToolRuntime(project_root=new_root)`;构造新的 `_DefaultEngineDeps` dataclass 复用 `self.deps.router` / `self.deps.story_consultant` / `self.deps.tool_registry`(这些与 project_root 无关),只换 `tool_runtime`;赋回 `self.deps`。

**理由**: 避免每 turn 重建 LLM client / ToolRegistry 等昂贵对象,只换 `ToolRuntime` (持有 project_root,影响后续 tool 调用)。

**备选 A**: 每 turn 重建 deps,只缓存 router。最简单但失去 EngineSession 的价值。
**备选 B**: 让 EngineSession 持有独立 `tool_runtime` 字段,deps 始终不变。Engine Loop 调用时拼 `EngineDepsWithRuntime(deps, session.tool_runtime)`。改动 Engine Loop,违反"不动 engine/"约束。
**备选 C**: 让 `ToolRuntime` 在 S0 / Sx 切换时改用 sentinel。项目目前已经在 `production_deps()` 里把 `project_root=None` 转 sentinel;沿用现有逻辑,`EngineSession.set_project_root(None)` 等价"切回 S0 sentinel"。

最终选 D2 + C 的组合:`set_project_root` 触发 `_DefaultEngineDeps` dataclass 重构造(走 `production_deps(project_root=...)` 路径),其余字段复用。

### D3: Pending Interrupt 拼接策略

**选择**: `_compose_pending_input(original: str, pending: Interrupt) -> str` 返回:

```python
return f"[pending] {pending.prompt}\n[answer] {original}"
```

`_run_engine()` 在每 turn 开头检查 `session.pending_interrupt`,非空则把这个串作为新的 `ctx.user_input`。

**理由**:

- LLM 路由器(LlmIntentRouter)看到 `[pending] ... [answer] ...` 这种带结构标记的输入,自然语言模型大概率会把它们当作上下文;RuleBasedIntentRouter 因为开头是 `[pending]` 不以 `/` 开头且不在 framework keywords,会落到 `answer_directly` 模板(可以接受——pending prompt 已经在 user 眼前,LLM 路径才是主要消费方)。
- 标记格式可见,REPL debug 时一眼看出是 pending + answer。
- 不引入额外的 prompt engineering(不动 COMMAND_AGENT_PROMPT)。

**备选 A**: 不拼接,只让 router "知道"有 pending(passing `has_pending_interrupt=True` flag 进 LLM prompt)。需要改 COMMAND_AGENT_PROMPT,违反"不动 routing"约束。
**备选 B**: 用 LangGraph `interrupt()` 机制(per 14)。需要 Engine Loop 引入 LangGraph dependency,且 LangGraph checkpoint 配 REPL 很重。out of scope。

### D4: TurnRecord 字段集

**选择**: `TurnRecord` 持有 `(turn_index, user_input, done_reason, timestamp)`。

**理由**: 不存事件流(events 太大);不存 router 决定(action_type)——done_reason 已经隐含了路由结果。timestamp 留给未来分析对话节奏。

**备选**: 加 `action_type` 显式记录路由结果。当前 done_reason 已足够(answered → answer_directly / workflow_pending → start_workflow / etc.)。

### D5: 测试 mock 入口

**选择**: `EngineSession(deps=mock_deps, ...)` 支持注入 fake deps,无需 patch `production_deps`。`tests/test_engine_session.py` 直接构造 session 测状态变化;`tests/test_cli.py` 通过 `EngineSession` 构造 fake session 测 REPL。

**理由**: 与既有"构造时注入 Protocol 实现"模式一致,不引入 monkeypatch 副作用。

**备选**: monkeypatch `production_deps`。会污染其他测试,且需清除 `lru_cache`。

## Risks / Trade-offs

- **[memory growth]**: `turns` 列表只增不减,长会话可能累积数千条 → MVP 不引入上限,future change 可加 `MAX_TURNS = 1000` + trim 策略。
- **[pending_interrupt 误拼]**: 用户输入 "查 F003" 时若有 pending,会被拼成 "[pending] 你想修改哪一段？\n[answer] 查 F003"。LLM 大概率把这两段一起理解,但不能 100% 保证。→ 加测试覆盖: 拼好后 router 收到的是合并字符串;依赖 LLM 的健壮性。
- **[deps replace 不被 Protocol 感知]**: `EngineDeps` 是 Protocol,dataclass 实例替换后 Protocol 检查仍然通过(`isinstance(deps, EngineDeps)`)。但若有测试 mock 了 `_DefaultEngineDeps` 的内部方法,换 deps 后会失效。→ 测试用 Protocol-level 断言,不依赖 `_DefaultEngineDeps` 具体类型。
- **[BREAKING `_run_engine` 签名]**: 内部签名从 `(text, console)` → `(text, session)`,cli 模块外部无调用方,但 git log 会看到 noise。→ 后续 PR 描述里说明。
- **[对话历史未消费]**: turns 字段已记录但没有消费方(不回显、不注入 LLM)。MVP 接受这个 "未使用即记账" 状态,等 StoryConsultant LLM 化时再消费。
- **[REPL test fixture 需要 session-aware]**: `tests/test_cli.py` 既有测试不传 session(直接调 `_run_engine(text, console)`)。重构后 `_run_engine` 签名变了。→ 在 cli 内部建一个 default session `EngineSession()`,保留旧 `_run_engine(text)` 单参版本用于测试(走 session 默认构造),不让所有现有测试同时改。

## Migration Plan

无版本迁移需要(项目尚未发布)。部署 = 合并到 main。

回滚 = revert commit。`EngineSession` 是新增包,移除不影响既有 Engine Loop。

## Open Questions

- **Q1**: `EngineSession` 是否应该在 session_id 已存在的注入场景下,允许外部传入 deps(测试场景)?当前设计已经支持(默认 factory 是 `production_deps`,可被覆盖)。本次落实。
- **Q2**: `_compose_pending_input` 是否要支持 `pending.options` (Interrupt.event 字段 `options: list[str] | None`)的多选场景? 当前只对 text prompt 拼接,options 不进入字符串。LLM 看 prompt 字符串即可推理。MVP 不变。
- **Q3**: 用户输入 `/退出` / `/帮助` / `/状态` 这些"框架命令"是否走 engine session?当前设计: 不走,REPL handle_repl_input() 直接拦截;只有非框架命令才走 `_run_engine(text, session)`。turns 里不记录 framework command。MVP 接受(framework command 不算对话 turn)。
- **Q4**: `EngineSession` 后续是否要支持"分叉"(从某个 turn 重启)?不在本次范围。