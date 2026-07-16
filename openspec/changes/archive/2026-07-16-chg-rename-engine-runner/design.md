## Context

`writer-agent` 的状态机层当前有两个「Engine」：

- `src/writer/engine/engine.py::Engine` —— 单轮 `AsyncGenerator`，持有 `EngineDeps`（DI 容器）+ `EngineConfig`（per-loop 配置），公开 API `Engine.run(ctx) -> AsyncIterator[events]`。一次轮询构造一次，`Done` 后丢弃。
- `src/writer/session/engine_session.py::EngineSession` —— 跨轮长寿命容器，frozen `session_id` + mutable `project_root` / `project_state` / `pending_interrupt` / `turns` + 一次性构造的 `engine: Engine`。`__post_init__` 装配 `EngineDeps` 后包装 `Engine`。

接线流（per `CLAUDE.md`）：`用户输入 → session.run_turn(user_input) → Engine.run(ctx) → self._deps.route() → AgentAction → ...`

这两个东西都带「Engine」前缀，命名跟角色错位。同时 `EngineDeps` 注入到 `Engine` 上（DI 命名违反「注入到谁身上以谁冠名」）。

参考现有重构惯例（如 `engine.loop.run_engine` 已经是 compat shim 模式、chg-remove-roles / chg-remove-state-machine-enforcement 等 OpenSpec 变更的落地形式）。

## Goals / Non-Goals

**Goals:**

- 命名跟角色对齐：跨轮长寿的 = `Engine`；单轮短命的 = `Runner`
- DI 命名规范化：`RunnerDeps` 注入到 `Runner`，符合「注入到谁身上以谁冠名」
- 模块路径自然化：`writer.engine.*` → `writer.runner.*`（类是 `Runner`，路径是 `writer.runner`，自洽）
- 接线流可读性提升：`engine.run_turn(user_input) → Runner.run(ctx)` 比 `session.run_turn(user_input) → Engine.run(ctx)` 更清晰
- 不留 compat shim，硬改；e2e / 脚本 / 文档 / tests 全部同步

**Non-Goals:**

- 不重写状态机逻辑（行为契约不变）
- 不重写 `events.py`（事件类名 `TextChunk`/`Done`/`ActionEvent`/`ToolCall`/`ToolResult`/`Interrupt`/`ErrorEvent` 不动；模块路径 `writer.engine.events` → `writer.runner.events`）
- 不重写 `tools/` / `routing/` / `workflows/` / `skills/` / `llm/` 子系统
- 不重写 spec 行为契约（仅 rename + 重写 requirement 文本）
- 不引入新依赖
- 不做渐进去名迁移（不留 compat shim）

## Decisions

### D1：硬改，不留 compat shim

**决定**：所有引用一次性全部重命名。`writer.engine.Engine` / `writer.session.EngineSession` / `EngineDeps` 等旧符号在新代码里完全消失。

**替代方案**：
- A. 留 deprecation warning shim（旧名 `from writer.engine import Engine as _Engine; Engine = _Engine` 之类）
- B. 留 re-export 无 warning
- C. 硬改（采用）

**理由**：项目已经在 `engine.loop.run_engine` 上保留了一个 compat shim（per CLAUDE.md），但本次改动属于「命名 + 模块路径」双重重命名，shim 链路过多反而增加认知负担；项目尚无外部 SDK 使用方（per CLAUDE.md "项目状态机" 描述 REPL 是唯一入口），e2e 管道、tests、docs 都是内部资产，一次性硬改的 blast radius 可控；保留 shim 还会让 `writer.engine` 与 `writer.runner` 共存，需要在多个地方重复 export，反而违反「明确命名」原则。

### D2：模块路径 `writer/engine/` → `writer/runner/`（整包重命名）

**决定**：`src/writer/engine/` 整体迁移到 `src/writer/runner/`。`__init__.py` 同步迁移。`events.py` 模块路径跟着改，但模块内的类名不动。

**替代方案**：
- A. 保留 `writer/engine/` 路径，内部只改类名
- B. 整包重命名为 `writer/runner/`（采用）

**理由**：包路径与主导类（`Runner`）保持一致比「路径与历史命名保持一致」更重要。`writer.engine.events` 在改成 `writer.runner.events` 后仍能表达「这是 Runner 的事件模块」，而 `writer.engine.engine`（当前）原本就有自指命名问题，整包迁移顺手消除。

### D3：`writer/session/engine_session.py` → `writer/session/engine.py`（包路径不动）

**决定**：`writer/session/` 包保留，新 `Engine` 类留在包里；只是把 `engine_session.py` 文件改名为 `engine.py`。

**理由**：跨轮长寿容器的语义没变，仍属于「session」范畴；只是类名从 `EngineSession` 缩短为 `Engine`，文件名同步缩短。整包平移到 `writer.engine` 会让 `writer.engine` 与 `writer.runner` 命名空间冲突（如果 `Runner` 类又住 `writer.engine.runner`，就更乱）。`writer/session/engine.py` 让 `from writer.session import Engine` 自然读出「从 session 包导入 Engine」。

### D4：行为契约完全保留，只换名字 + 路径

**决定**：`_engine_loop` / `_run_tool` / `_run_tool_loop` / `_run_workflow` / `_run_agent` / `_run_directive` / `_maybe_run_init_brief_or_block` 等所有私有方法名保持不变；只是承载类从 `Engine` 改成 `Runner`。

**理由**：私有方法名是 implementation detail，不暴露为公共 API。改名会引入更多 churn 而无命名收益。

### D5：specs 内部 spec 名（`engine-loop` / `engine-session`）保留，仅重写 requirement 文本

**决定**：OpenSpec 的 spec 目录名 `engine-loop/` / `engine-session/` 等保持不变；requirement 文本中所有 `Engine` / `EngineSession` / `EngineDeps` 等类名引用改为新名。

**替代方案**：
- A. spec 目录名也改名（`engine-loop/` → `runner-loop/`）
- B. spec 目录名保持，仅改文本（采用）

**理由**：spec 名描述的是「概念」（loop / session / genre-init），概念不变；类名是 spec 内 requirement 文本中的引用，会随实现改。改名 spec 目录涉及 OpenSpec archive / git log / 文档链接等多个外部表面，且后续 `openspec validate --strict` 对目录名有约定（参考 `engine-loop/` 与 `engine-session/` 已存在的 kebab-case 风格），保留目录名降低 churn。

### D6：`writer/session/engine_session.py` 中的 `session_id` 字段语义保持不变

**决定**：新 `Engine` 仍持有 `session_id: UUID`（frozen），`started_at: datetime`（frozen），`project_root: Path | None`（mutable），`project_state: str`（mutable），`pending_interrupt: Interrupt | None`（mutable），`turns: list[TurnRecord]`（mutable）。

**理由**：这是跨轮长寿容器的核心契约，rename 不应改变行为语义。

## Risks / Trade-offs

### R1：Import 漏改导致 `ImportError` 或 `AttributeError`

**风险**：~25 个测试文件 + 多个 src 模块 + CLI 入口 + docs/e2e scripts 都要改类名/模块路径，漏一处就崩。

**缓解**：
- 阶段化提交：先动 src 模块、再动 CLI、再动 tests、最后 docs
- 每阶段跑 `uv run mypy src/writer` + `uv run pytest` 验证
- 用 `git grep "from writer.engine\|EngineSession\|EngineContext\|EngineConfig\|EngineDeps\|run_engine"` 做最后一道防线

### R2：e2e pipe / fixture 中类名引用漏改

**风险**：`.writer/skills/*/SKILL.md` 的 LLM prompt 文本可能引用 `Engine` / `EngineSession` 之类的符号；fixtures 中可能直接 `Engine(...)` 实例化。

**缓解**：
- `git grep "EngineSession\|EngineContext\|EngineConfig\|EngineDeps\|Engine()\|run_engine"` 全文搜索
- e2e 测试通过 stdin pipe 触发覆盖

### R3：docs 漏改不影响功能但 onboarding 受阻

**风险**：`CLAUDE.md`、`MEMORY.md`、`docs/技术架构总览.md`、`docs/how/*`、`技术难点与解决方案备忘/*` 是新成员上手的唯一入口。漏改会让 onboarding 与实际代码脱节。

**缓解**：
- 在 tasks.md 显式列 docs 修改清单（按 grep 自检）
- 完成后用 `git grep "EngineSession\|EngineContext\|EngineConfig\|EngineDeps\|writer.engine\b"` 做全文 grep 自检，残留仅在历史性 docstring 留档（如「Renamed from X」前缀）

### R4：测试 fixture 内部小工具类名同步

**风险**：测试文件中的 `_MiniRecordingChatModel` / `_FakeEngineDeps` / `_RecordingChatModel` / `_deps_with_real_prose` / `_deps_with_prose` 等内部 fixture 会引用旧类名，需同步改。

**缓解**：在 tasks.md 中显式列测试 fixture 改造清单；通过全量测试（483 passing + 6 pre-existing fail）做兜底。

## Migration Plan

阶段化提交（每个阶段一个 commit，可 squash）：

1. **阶段 1**：新增 `writer/runner/` 包的 6 个文件（runner.py / loop.py / deps.py / context.py / config.py / events.py），文件内容是 `writer/engine/` 对应文件的全量复制 + 类名重命名 + 模块路径引用更新
2. **阶段 2**：`writer/session/engine_session.py` → `writer/session/engine.py`，类名 `EngineSession` → `Engine`
3. **阶段 3**：更新所有 src 模块的 import + 类名引用（cli/main.py / cli/repl.py / cli/_init_backend.py / session/__init__.py 等）
4. **阶段 4**：删除 `src/writer/engine/` 目录（仅在阶段 1-3 通过测试后）
5. **阶段 5**：更新所有 tests（~25 个文件）+ conftest.py
6. **阶段 6**：更新 docs（CLAUDE.md / MEMORY.md / docs/技术架构总览.md / docs/how/* / 技术难点与解决方案备忘/*）
7. **阶段 7**：更新 7 个 OpenSpec spec 的 requirement 文本
8. **阶段 8**：`uv run ruff check src tests` + `uv run mypy src/writer` + `uv run pytest` 全过 + grep 自检无残留

回滚策略：阶段化 git revert 即可（每阶段一个 commit）。

## Open Questions

无。本次重命名属于「行为契约不变 + 名字/路径变更」，设计决策点都已闭合。