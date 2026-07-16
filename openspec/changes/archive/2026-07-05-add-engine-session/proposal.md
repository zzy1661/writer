## Why

`writer.engine.run_engine` 是 stateless AsyncGenerator(备忘 16 §"Engine 是无状态 AsyncGenerator"),但当前 REPL(`src/writer/cli/main.py`)每行输入都重建 `EngineContext`、`session_id=str(uuid4())`、`production_deps()`,导致:

- **身份断裂**: 同一次 REPL 进程的两次输入拿到不同的 session_id,跨 turn 无连续性。
- **deps 反复重建**: 每 turn 都新建 `ToolRegistry` / `ToolRuntime`,即使 `project_root` 没变。
- **ask_user 回路未闭合**: engine 发出 `Interrupt` 事件后,REPL 只 console.print,没存进任何状态,下一次用户输入也不知道上次问过什么。
- **对话历史丢失**: turns 没有累积记录,无法回看或注入未来 LLM context。

备忘 16 第 374 行明确留了这个口: "会话级状态(对话历史、checkpoint、session 内存)属于 `EngineSession`(per 17 预留),不在 engine 内部。" 现在落实。

## What Changes

- 新增 `src/writer/session/` 包:
  - `engine_session.py` — `EngineSession` dataclass(frozen identity + mutable state container) + `TurnRecord`
  - `__init__.py` — re-export `EngineSession` / `TurnRecord`
- 新增 `TurnRecord` dataclass: `turn_index` / `user_input` / `done_reason` / `timestamp`
- 修改 `src/writer/cli/main.py`:
  - `run_repl()` 在循环外创建一次 `EngineSession`,所有 turn 共享
  - `_run_engine(text, session)`:
    - 用 `session.session_id` 构造 `EngineContext`(不再 per-turn uuid)
    - 若 `session.pending_interrupt` 非空,把 pending prompt 拼到 ctx.user_input 头部
    - 每 turn `run_engine(ctx, session.deps)`,事件流里:
      - `Interrupt` 事件 → 存进 `session.pending_interrupt`
      - `Done` 事件 → append `TurnRecord`,清空 `pending_interrupt`
  - 新增 `_compose_pending_input(original: str, pending: Interrupt) -> str` 辅助函数
- 新增 `tests/test_engine_session.py`(8 测试)+ 扩展 `tests/test_cli.py`(3 测试)
- **BREAKING**: `handle_repl_input(line)` 签名不变,但内部从"无状态 per-turn 重建"变为"session-scoped";若外部代码直接调用 `_run_engine(text, console)`,需更新为 `_run_engine(text, session)`。

## Capabilities

### New Capabilities

- `engine-session`: 跨 turn 的会话状态容器。覆盖: 会话身份(frozen session_id)、会话内可变状态(project_root / project_state 占位 / pending_interrupt / turns)、deps 生命周期(构造时一次,project_root 变才换 tool_runtime)、Interrupt 回路(pending → 拼接 → 下一轮)、turn 记录(append-only)。

### Modified Capabilities

无。本次不修改任何已有 spec。`engine-loop` spec 提到的 EngineContext 字段不变;`EngineDeps` Protocol 不变;`DoneReason` 不变。

## Impact

- **新增文件**: `src/writer/session/__init__.py`、`src/writer/session/engine_session.py`、`tests/test_engine_session.py`
- **修改文件**: `src/writer/cli/main.py`(`run_repl` + `_run_engine` 重构以接收 session)
- **测试**: 既有 64 个测试全部不动;新增 11 个(8 session + 3 REPL 集成)
- **公共表面**: `from writer.session import EngineSession, TurnRecord`
- **不动**: `engine/`、`routing/`、tool 层、workflow stub、`EngineDeps` Protocol、`EngineContext` dataclass 字段
- **依赖**: 无新依赖
- **BREAKING**: 内部签名变化,`_run_engine(text, console)` → `_run_engine(text, session)`;外部若直接调用需同步更新。本次无外部调用方。