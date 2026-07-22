## Why

`/大纲` (shipped 2026-07-16, per MEMORY.md) 生成全书大纲与章节目录,但 `/创作` LangGraph 图（`write_chapter.py::build_writer_graph`，6 节点）跑单章需要 LLM 多次调用（plan → draft → proofread → review_gate），用户对全书/全卷的"开局收尾一致性"缺乏中间粒度的快速生成工具。

产品文档（`docs/命令与用户流程.md` 阶段二规划）把 `/骨架` 标为占位——「每章开头、结尾」。本 change 是该命令的**PR1 落地**：在已有 `大纲/大纲.md` + `大纲/章节目录.md` 上为每章生成「开头 + 结尾」骨架，落盘到 `骨架/<卷>/第N章.md`，作为 `/创作` 的边界约束输入。

**为什么走 workflow 而非 directive（per `TODO/骨架命令.md` §2 决策）**：

1. 批量生成需要 Supervisor-Worker + 进度跟踪，SKILL.md ReAct 步数/调度不够（与 `/目录` 用 `WorkflowResult` 同款思路）
2. `RunnerDeps.run_workflow` + `WorkflowResult` 已支持 3 状态映射（completed / failed / pending——pending 专用于 needs_rewrite，per `runner/runner.py:392-407`），新增 workflow 零 engine 代码改动
3. PR3 可让 `write_chapter` 消费骨架开/收作为 prep_context canon-block 输入（per `_build_canon_block` 第 133 行元组扩展）

**为什么不立即覆盖"已有骨架"**：避免破坏性命令风险（用户已审过的开/收被无意覆写）。`rewrite` 推 PR2。

## What Changes

- **新增** `src/writer/workflows/skeleton_chapters.py`：`run(ctx, deps) -> WorkflowResult` 入口 + `build_skeleton_graph(checkpointer=...)` LangGraph 图（6 节点：`load_inputs` → `parse_toc` → `init_or_load_progress` → `generate_batch` → `persist_skeleton` → `finalize`，PR1 `init_or_load_progress` 简化为「仅 init, 不读」）；`_set_deps(deps)` / `_get_deps()` 模块级 deps 注入（与 `write_chapter.py:367-396` 同款）
- **新增** `src/writer/workflows/params.py::SkeletonArgs` + `extract_skeleton_args(user_input)`：解析 `mode`（`full` / `volume` / `range`）/ `volume` / `start` / `end`；`rewrite` / `continue` / `view` PR1 **不接受**（仅占位字段，留给 PR1.5 / PR2）
- **新增** `src/writer/workflows/params.py` 单测 6 项：缺参 → `mode=full`；卷名 → `mode=volume, volume="卷一"`；区间 `1.1-1.20` → `mode=range`；单层 `1-20` → `SkillError`；跨卷 `1.1-2.20` → `mode=range, start="1.1", end="2.20"`
- **修改** `src/writer/workflows/__init__.py::WORKFLOWS`：注册 `"skeleton_chapters": skeleton_chapters_run`
- **修改** `src/writer/routing/intent_router.py::RuleBasedIntentRouter.route`：新增 `/骨架` 分支 → `AgentAction(action_type="start_workflow", command="/骨架", role="story_agent", workflow="skeleton_chapters", arguments={"raw": text})`，紧贴 `/创作` / `/审核`（`intent_router.py:101-116`）
- **修改** `src/writer/routing/intent_router.py:130-136` fallback answer 文案：插入 `/骨架`（与 `/大纲` / `/目录` / `/人物` 同款节奏，per MEMORY 2026-07-16 / 2026-07-17）
- **修改** `src/writer/cli/main.py` REPL 帮助文案：阶段二命令表插入 `/骨架`
- **新增** `tests/test_skeleton_chapters.py`（8 项测试）：
  - `test_skeleton_args_parses_*` 5 项（覆盖 PR1 解析路径）
  - `test_skeleton_requires_state_s4`：S3 输入 `failed` + 提示先 `/目录`
  - `test_skeleton_raises_when_deterministic`：per `_plan_chapter_node` 同款 strict raise（per MEMORY 2026-07-14 决策）
  - `test_skeleton_persist_uses_path_write_text_directly`：验证 workflow 内 `Path.write_text` 写 `骨架/<卷>/第N章.md`，**不**经 `safe_write_file`，**不**扩 `DEFAULT_WRITE_WHITELIST`
- **新增** `tests/test_engine.py` 1 项：`test_engine_dispatches_skeleton_workflow` —— `RuleBasedIntentRouter.route("/骨架")` → `AgentAction.workflow == "skeleton_chapters"`；engine 走 `_run_workflow` 路径
- **不动**：
  - `Runner` 类（`runner/runner.py`）—— `_run_workflow` 已支持任意 `WorkflowResult`，新增 workflow 不需要动 Runner
  - `tools/runtime.py::DEFAULT_WRITE_WHITELIST`（per `tools/runtime.py:18-41`，当前不含 `骨架`；PR1 走 workflow 内直写绕过）
  - `routing/llm_router.py`（`CompositeRouter` 主路由已捕获任何 `/` 前缀，LLM fallback 不触发）
  - `prompts/context.py::_build_canon_block`（PR3 才加 `"骨架"`）
  - `cli/repl.py::_warn_deterministic_prose_client`（PR2.5 才扩到 `/骨架`）

## Capabilities

### New Capabilities

- **`skeleton-chapters`**: 全书/指定卷/区间每章开头结尾骨架生成工作流。定义 6 节点 LangGraph（图结构与 `write_chapter.py::build_writer_graph` 对称）、`SkeletonArgs` 参数契约、`OPEN_MAX_CHARS` / `CLOSE_MAX_CHARS` 字数上限、`status="completed"` 携带 `chapter_count` / `mode` / `volume` metrics、`status="failed"` 携带 `partial_chapters` / `progress_path` metrics、deterministic 模式 strict raise 契约、与 `WorkflowResult` 3 状态映射。

### Modified Capabilities

- **`intent-routing`**: 当前 spec（`openspec/specs/intent-routing/spec.md`）定义 `RuleBasedIntentRouter.route` 覆盖 `/字数统计` / `/创作` / `/审核` / 伏笔查询 4 个分支。改造后 `RuleBasedIntentRouter.route` 增 `/骨架` 分支（`start_workflow` action，workflow=`skeleton_chapters`）；fallback answer 文案插入 `/骨架` 一项。**新增**一个 ADDED Requirement，**不动**现有 Requirements。

## Impact

**影响文件**（src ~6 + test ~3）：

- `src/writer/workflows/skeleton_chapters.py`（**新增** ~280 行）：6 节点图 + 4 个 helper + `_set_deps` / `_get_deps` + `_state_to_result`
- `src/writer/workflows/params.py`（**改** +40 行）：`SkeletonArgs` dataclass + `extract_skeleton_args`（独立函数，与 `extract_write_chapter_args` / `extract_review_chapter_args` 同款风格，`workflows/params.py:65-100`）
- `src/writer/workflows/__init__.py`（**改** +1 行）：`WORKFLOWS["skeleton_chapters"] = skeleton_chapters_run`
- `src/writer/routing/intent_router.py`（**改** +5 行）：`/骨架` 分支 + fallback 文案更新
- `src/writer/cli/main.py`（**改** +2 行）：帮助文案
- `tests/test_skeleton_chapters.py`（**新增** ~250 行）：8 测试用例
- `tests/test_engine.py`（**改** +1 测试）：`test_engine_dispatches_skeleton_workflow`
- `tests/test_workflows.py`（**改** +1 测试）：`_DefaultRunnerDeps` 注册 `skeleton_chapters` 后 `production_deps_includes_all_registered_workflows` 断言扩展

**不动的部分**（架构稳定区）：
- `Runner` 类（`runner/runner.py`）+ `_engine_loop` + `_run_workflow`（已完成 3 状态映射）
- `RunnerDeps` Protocol + `_DefaultRunnerDeps` + `production_deps`（无需新字段）
- `WorkflowResult` dataclass（per `workflows/types.py:26-49`）
- `write_chapter` / `review_chapter` 工作流
- 4 层架构（CLI / Runner / Workflows / Tools）+ 兼容层
- `DEFAULT_WRITE_WHITELIST`（per `tools/runtime.py:18-41`）
- AGENT.md 消费路径（`state.py::read_genre_from_agent` / `read_architecture_method_from_agent`，复用既有）

**迁移路径**：
- 无外部用户影响：PR1 仅新增能力，不改现有命令语义
- 现有项目无 `/骨架` 骨架目录 → 首次 `/骨架` 自动创建 `骨架/<卷>/第N章.md`
- 旧 fake `RunnerDeps` stub（如有）：无需改字段；workflow 注册走 `production_deps._workflows`

**风险**：
- **Medium：deterministic 模式 strict raise 可能误伤开发环境**——用户没配 `WRITER_API_KEY` 又跑 `/骨架` 会立即 raise。**Mitigation**：与 `_plan_chapter_node` 同款；REPL 启动预检扩到 `/骨架` 在 PR2.5 落地
- **Low：单章 LLM 调用超时**——MVP 不设超时重试；失败即 `status="failed"` + `partial_chapters`。**Mitigation**：PR2 加 `max_chapters_per_turn` 预算
- **Low：中文目录 `骨架/<卷>/` 跨平台兼容性**——已有 `草稿/` / `大纲/` / `人物/` / `人物/主要人物.md` 同款中文目录验证 OK（per `project/workspace.py`）；新加 `骨架/` 风险同
- **Low：双层章节 ID `1.1-2.20` 解析边界**——区间跨卷时卷·章顺序字典序 vs 数值序差异（`1.10 > 1.2` 字典序 vs `1.10 > 1.2` 数值序）。**Mitigation**：MVP 仅支持「同卷内」区间（`1.1-1.20`），跨卷区间 PR2 再补

## Open Questions (PR1 范围内已决)

1. **`/骨架 view` 与 `partial` 走 PR1.5 / PR2** —— PR1 仅支持 `mode=full` / `mode=volume` / `mode=range` 三态，不实现 `view`（仅 chunks 不写盘）与 `partial`（基于进度的续跑）。
2. **`rewrite` 语义走 PR2** —— PR1 已有骨架时 `failed` 提示「已存在骨架，请用 `/骨架 rewrite`」；rewrite 实装推 PR2。
3. **`continue` 语义走 PR2** —— 进度文件 `骨架/进度.json` 在 PR2 落地（per `TODO/骨架命令.md` §5）。PR1 中断即丢；用户在下次 `/骨架` 重跑全量。
4. **跨卷区间解析** —— PR1 仅支持「同卷内」区间（`1.1-1.20`），跨卷（`1.1-2.20`）语法 PR1 接受但解析为「同首卷到末卷的章节子集」，具体语义 PR2 再细化
5. **`OPEN_MAX_CHARS=400` / `CLOSE_MAX_CHARS=300` 按题材微调** —— MVP 固定，按 `arch-optimizer M3` 节奏 PR2+ 引入 settings.kv 题材感知阈值