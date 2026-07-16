## Why

当前 `Engine` / `EngineSession` 命名误导：跨轮主控（`session_id` / `project_root` / `pending_interrupt` / `turns`）被命名为 `EngineSession`，但实际是长寿命的「Engine」；单轮状态机（`AsyncGenerator` 跑完一个 `Done`）被命名为 `Engine`，但实际是短寿命的「Runner」。两个都叫「Engine」，读者要在脑子里换算一次。同时 `EngineDeps` 注入到 `Engine` 上，违反「注入到谁身上以谁冠名」的 DI 命名约定。

## What Changes

- **`EngineSession` → `Engine`**（跨轮主控，长寿命）。模块路径 `src/writer/session/engine_session.py` → `src/writer/session/engine.py`。
- **`Engine` → `Runner`**（单轮派发，短寿命）。模块路径 `src/writer/engine/engine.py` → `src/writer/runner/runner.py`。
- **`EngineContext` → `RunnerContext`**。模块路径 `src/writer/engine/context.py` → `src/writer/runner/context.py`。
- **`EngineConfig` → `RunnerConfig`**。模块路径 `src/writer/engine/config.py` → `src/writer/runner/config.py`。
- **`EngineDeps` → `RunnerDeps`**。模块路径 `src/writer/engine/deps.py` → `src/writer/runner/deps.py`。
- **模块包重命名**：`src/writer/engine/` → `src/writer/runner/`（`events.py` 模块路径同步，但事件类名 `TextChunk`/`Done`/`ActionEvent`/`ToolCall`/`ToolResult`/`Interrupt`/`ErrorEvent` 不动）。
- **compat shim 函数重命名**：`src/writer/engine/loop.py::run_engine` → `src/writer/runner/loop.py::run_runner`（命名语义对齐新 `Runner`）。
- **接线流自然化**：CLI bridge 从 `session.run_turn(user_input) → Engine.run(ctx)` 变为 `engine.run_turn(user_input) → Runner.run(ctx)`。
- **不留 compat shim**。e2e 管道、脚本、文档、tests 全部同步重命名。
- **BREAKING**：所有 import `from writer.engine import ...` 必须改为 `from writer.runner import ...`；`from writer.session.engine_session import EngineSession` 改为 `from writer.session.engine import Engine`；CLI bridge 等所有类名引用同步更新。

## Capabilities

### New Capabilities

无。所有相关 capability 已在 `openspec/specs/` 中存在，本次仅做需求文本重写（rename）。

### Modified Capabilities

- **`engine-loop`**：`Engine` → `Runner`、`EngineContext` → `RunnerContext`、`EngineConfig` → `RunnerConfig`、`EngineDeps` → `RunnerDeps`、`run_engine` → `run_runner`、模块路径 `writer.engine.*` → `writer.runner.*`。
- **`engine-session`**：`EngineSession` → `Engine`、`EngineDeps` → `RunnerDeps`、模块路径 `writer.session.engine_session` → `writer.session.engine`。
- **`genre-init`**：`EngineSession` → `Engine`、`EngineDeps` → `RunnerDeps`。
- **`skill-directives`**：`EngineSession` → `Engine`、`EngineDeps` → `RunnerDeps`、`Engine` → `Runner`（dispatch 主体）。
- **`workflow-result`**：`EngineDeps` → `RunnerDeps`、`EngineContext` → `RunnerContext`、模块路径 `src/writer/engine/deps.py` → `src/writer/runner/deps.py`。
- **`prose-llm`**：`EngineDeps` → `RunnerDeps`（单点引用）。
- **`writer-tools`**：`EngineDeps` → `RunnerDeps`（单点引用）。

## Impact

- **直接修改 src 文件**：~10 个 Python 模块（重命名 + 类改名 + 内容更新）
- **删除目录**：`src/writer/engine/`（移至 `src/writer/runner/`）
- **测试修改**：~25 个测试文件（import + 类名引用）
- **CLI 入口**：`src/writer/cli/{main,repl,_init_backend}.py`（`session` → `engine`、`engine.run` → `runner.run`、`run_turn` 等）
- **文档同步**：`CLAUDE.md`、`MEMORY.md`、`docs/技术架构总览.md`、`docs/how/*`、`技术难点与解决方案备忘/*`、`openspec/specs/*/spec.md`（7 个 spec）
- **e2e 管道**：`<project_root>/.writer/skills/*/SKILL.md`、`e2e/.writer/skills/*/SKILL.md` 中引用 `Engine` / `EngineSession` / `EngineDeps` 等的提示语同步
- **非破坏性契约**：所有 capability 的「行为契约」（call_graph / 事件流 / DI 槽位）不变，仅类名、模块路径变更
- **OpenSpec artifacts**：4 个（`proposal.md` / `design.md` / `tasks.md` / 7 个 spec 的 delta 文件）
- **风险**：
  1. import 漏改会触发 `ImportError`；由 mypy + ruff + 全量测试覆盖
  2. e2e pipe / 测试 fixture 中类名引用漏改会触发 `AttributeError`；由 ruff + 483+ 测试覆盖
  3. docs 漏改不影响功能但会让 onboarding 受阻；由 doc grep 自检覆盖