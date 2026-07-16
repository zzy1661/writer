# tasks: chg-rename-engine-runner

## 1. 创建 `src/writer/runner/` 包

- [x] 1.1 新建 `src/writer/runner/` 目录；复制 `src/writer/engine/events.py` → `src/writer/runner/events.py`（模块内的 `TextChunk` / `Done` / `ActionEvent` / `ToolCall` / `ToolResult` / `Interrupt` / `ErrorEvent` 类名不动，仅修改模块 docstring 引用 `writer.engine` → `writer.runner`）
- [x] 1.2 新建 `src/writer/runner/context.py`：从 `src/writer/engine/context.py` 复制；类 `EngineContext` → `RunnerContext`；模块 docstring 同步
- [x] 1.3 新建 `src/writer/runner/config.py`：从 `src/writer/engine/config.py` 复制；类 `EngineConfig` → `RunnerConfig`；模块 docstring 同步
- [x] 1.4 新建 `src/writer/runner/deps.py`：从 `src/writer/engine/deps.py` 复制；类 `EngineDeps` → `RunnerDeps`；内部 `_DefaultEngineDeps` → `_DefaultRunnerDeps`；`production_deps()` 返回 `RunnerDeps` 实例；模块 docstring 同步
- [x] 1.5 新建 `src/writer/runner/runner.py`：从 `src/writer/engine/engine.py` 复制；类 `Engine` → `Runner`；`replace_deps` / `replace_cfg` 方法签名不变（仅返回类型 `Engine` → `Runner`）；模块 docstring 同步
- [x] 1.6 新建 `src/writer/runner/loop.py`：从 `src/writer/engine/loop.py` 复制；函数 `run_engine` → `run_runner`；`run_runner` 内部 `Runner(deps=deps, cfg=cfg).run(ctx)`；模块 docstring 同步
- [x] 1.7 新建 `src/writer/runner/__init__.py`：从 `src/writer/engine/__init__.py` 复制；导出 `Runner` / `RunnerContext` / `RunnerConfig` / `RunnerDeps` / `run_runner`

## 2. 改 `src/writer/session/`

- [x] 2.1 `src/writer/session/engine_session.py` 文件重命名为 `src/writer/session/engine.py`（`git mv`）
- [x] 2.2 文件内类 `EngineSession` → `Engine`；`self.engine: Engine` 改为 `self.runner: Runner`（指向内部 `Runner` 实例）；`run_turn` 方法不变（仍构造 `RunnerContext` 后委托给 `runner.run(ctx)`）；模块 docstring 同步
- [x] 2.3 `src/writer/session/__init__.py`：导出 `Engine` / `TurnRecord`（替代 `EngineSession` / `TurnRecord`）

## 3. 更新所有 src 模块 import + 类名引用

- [x] 3.1 `src/writer/cli/main.py`：所有 `from writer.session import EngineSession` → `from writer.session import Engine`；`from writer.engine import ...` → `from writer.runner import ...`；类名引用同步；`session.deps` → `engine.deps`；`session.run_turn` → `engine.run_turn`
- [x] 3.2 `src/writer/cli/repl.py`：同上模式
- [x] 3.3 `src/writer/cli/_init_backend.py`：同上模式
- [x] 3.4 `src/writer/workflows/__init__.py`、`write_chapter.py`、`review_chapter.py`、`types.py`：`EngineContext` → `RunnerContext`；`run_engine` → `run_runner`
- [x] 3.5 `src/writer/llm/agent.py`：`EngineContext` → `RunnerContext`；`run_engine` → `run_runner`
- [x] 3.6 `src/writer/skills/protocol.py`：`EngineContext` / `EngineDeps` / `EngineSession` 引用更新
- [x] 3.7 `src/writer/tools/errors.py`：`EngineContext` 引用更新
- [x] 3.8 `src/writer/project/state.py`：如有 `EngineSession` / `EngineDeps` 引用则更新

## 4. 删除旧 `src/writer/engine/` 目录

- [x] 4.1 确认所有 import 已切到 `writer.runner.*`（用 `git grep "from writer.engine"` 自检，确认 src/ + tests/ 零残留）
- [x] 4.2 `git rm -r src/writer/engine/`

## 5. 更新所有测试

- [x] 5.1 `tests/test_engine.py`：所有 `EngineContext` / `EngineConfig` / `EngineDeps` / `Engine` / `run_engine` 引用更新
- [x] 5.2 `tests/test_engine_session.py`：所有 `EngineSession` / `EngineDeps` 引用更新
- [x] 5.3 `tests/test_engine_deps.py`：所有 `EngineDeps` 引用更新；测试 fixture 内 `_DefaultEngineDeps` → `_DefaultRunnerDeps` 等内部命名同步
- [x] 5.4 `tests/test_workflows.py` / `test_workflows_write_chapter.py` / `test_workflows_review_chapter.py`：`EngineContext` / `run_engine` 引用更新
- [x] 5.5 `tests/test_workflow_result.py`：`EngineDeps` / `EngineContext` / `Engine` 引用更新
- [x] 5.6 `tests/test_cli.py`：monkeypatch 目标从 `cli_main.run_engine` → `cli_main.run_runner`；其它类名引用同步
- [x] 5.7 `tests/test_repl_explore.py`、`tests/test_react_agent.py`、`tests/test_directive_dispatch.py`：类名引用同步

## 6. 更新 docs

- [x] 6.1 `CLAUDE.md`：四层架构表格、`EngineSession` / `Engine` / `EngineDeps` / `EngineContext` / `EngineConfig` / `run_engine` 引用全部更新；接线流描述更新；`writer.engine` → `writer.runner`
- [ ] 6.2 `MEMORY.md`：新增「Engine/Runner 命名重组」段记录本次决策；保留旧段作为历史正确锚点（如「引入 Engine 类」段标 Renamed per chg-rename-engine-runner）
- [x] 6.3 `docs/技术架构总览.md`：架构图 + 包职责表 + 接线流描述 + 模块路径全部更新
- [x] 6.4 `docs/how/03-会话与状态机.md`、`04-意图路由层.md`、`08-题材与Agent层.md`、`09-ReAct工具循环.md`、`10-项目workspace脚手架.md`、`11-配置与设置.md`、`12-工作流与审核.md`、`14-测试体系.md`、`15-演进与备忘体系.md`：类名 / 模块路径引用全部更新
- [x] 6.5 `docs/bugs/`：如有引用旧名的 bug 报告，更新类名 / 模块路径
- [x] 6.6 `技术难点与解决方案备忘/01-17`：类名 / 模块路径引用全部更新；保留与「Engine」概念相关的历史叙述（如备忘 16 §"Engine 是无状态 AsyncGenerator" 改为 "Runner 是无状态 AsyncGenerator"）

## 7. OpenSpec artifacts 同步

- [x] 7.1 7 个 spec delta 文件已在本次 change 创建（已完成）：`specs/{engine-loop,engine-session,genre-init,prose-llm,skill-directives,workflow-result,writer-tools}/spec.md`
- [x] 7.2 不动 `openspec/specs/<capability>/spec.md`（这些在 `opsx:apply` 之后由 OpenSpec archive 机制自动同步）

## 8. 验证

- [x] 8.1 `uv run ruff check src tests` clean
- [x] 8.2 `uv run mypy src/writer` clean
- [x] 8.3 `uv run pytest` 全过（基线 483 passing + 6 预存在 fail；本次 change 应保持同等基线）
- [x] 8.4 grep 自检：`git grep -E "EngineSession|EngineContext|EngineConfig|EngineDeps|from writer\.engine\b|writer\.session\.engine_session|run_engine\b" src/ tests/ docs/ CLAUDE.md MEMORY.md` 仅在历史性 docstring（如「Renamed from X」锚点）残留
- [x] 8.5 e2e 管道 smoke test：`printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer` 正常 Done(answered)
- [x] 8.6 `uv run writer doctor` 正常输出表格
- [x] 8.7 `uv run writer new 测试书 --dir /tmp/x` 正常建项目（per 上一个 change dd229cb，genre 已无；本次不依赖）