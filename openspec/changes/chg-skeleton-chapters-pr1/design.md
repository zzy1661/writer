## Context

`/大纲` (shipped 2026-07-16) 把全书大纲与章节目录落盘到 `大纲/大纲.md` + `大纲/章节目录.md`。`/创作` LangGraph 图（6 节点）跑单章需要多次 LLM 调用（plan → draft → proofread → review_gate），用户对全书/全卷的"开局收尾一致性"缺乏中间粒度工具。

本 change（PR1）落地产品文档阶段二的 `/骨架` 占位：「每章开头、结尾」骨架生成工作流，输出 `骨架/<卷>/第N章.md` 作为 PR3 `/创作` prep_context 的边界约束输入。

`TODO/骨架命令.md`（2026-07-17 修订版）已通过审核：3 处与现行 Runner 契约冲突 + 6 处路径引用过时 + 测试矩阵不全已逐条修正。本 design 按修正后方案实装。

## Goals / Non-Goals

**Goals（PR1 范围）：**
- 新增 `src/writer/workflows/skeleton_chapters.py` 6 节点 LangGraph：`load_inputs → parse_toc → init_or_load_progress → generate_batch → persist_skeleton → finalize`
- 新增 `SkeletonArgs` + `extract_skeleton_args` 参数解析（仅 `full` / `volume` / `range` 三态，不接受 `view` / `continue` / `rewrite`）
- 新增 `RuleBasedIntentRouter.route` `/骨架` 分支 + fallback 文案
- workflow 内 `Path.write_text` 直写 `骨架/<卷>/第N章.md`（与 `write_chapter._persist_outputs_node` 同款），**不**经 `safe_write_file`，**不**扩 `DEFAULT_WRITE_WHITELIST`
- deterministic 模式 strict raise（与 `_plan_chapter_node` 同款契约，per MEMORY 2026-07-14）
- `WorkflowResult` 3 状态映射对齐（completed / failed / pending 单义 needs_rewrite）
- AGENT.md 双行消费复用 `state.py::read_genre_from_agent` + `read_architecture_method_from_agent`（per MEMORY 2026-07-16）
- 8 项新测试 + 1 项 engine dispatch 测试

**Non-Goals（PR1 范围外，留 PR1.5 / PR2 / PR3）：**
- `view` 短路（PR1.5）
- `continue` 续跑 + `进度.json` 进度文件（PR2）
- `rewrite` 覆盖（PR2）
- `max_chapters_per_turn` 预算（PR2）
- CLI 启动 deterministic 警告扩 `/骨架`（PR2.5）
- `_build_canon_block` 元组追加 `"骨架"`（PR3）
- `write_chapter` 消费骨架开/收（PR3）
- 按题材微调字数上限（PR2+）

## Decisions

### 1. 走 workflow 而非 directive

**决定**：`/骨架` 派发到 `start_workflow` / `workflow="skeleton_chapters"`，由 `RunnerDeps.run_workflow` → `WORKFLOWS["skeleton_chapters"]` → `skeleton_chapters_run(ctx, deps)` 走 LangGraph 图。

**理由**：
1. 批量生成需要 Supervisor-Worker + 进度跟踪（per `TODO/骨架命令.md` §3 编排选型）
2. `WorkflowResult` 已支持 3 状态映射（per `runner/runner.py::_run_workflow` + `workflows/types.py:22`），新增 workflow 零 engine 代码改动
3. PR3 接缝清晰：`prompts/context.py::_build_canon_block` 第 133 行 `for relative in ("大纲", "人物")` 元组追加 `"骨架"`，自动让 `_draft_chapter_node` system prompt 注入开/收约束

**替代方案 A：SKILL.md directive + LLM tool loop** —— 否决。LLM tool loop 是单步 ReAct；批量 100 章骨架生成需要外部 Supervisor 调度、批大小控制、跨章 prev_closing 串递，SKILL.md ReAct 步数/调度不够。

**替代方案 B：合并到 `/创作` 单图** —— 否决。`/创作` 是单章细粒度生成（plan + draft + proofread + review_gate），`/骨架` 是全书粗粒度批量生成，二者节奏不同。混图会失去 PR3 的「canon-block 自动消费」接缝。

### 2. 6 节点 LangGraph 图结构

**决定**（per `TODO/骨架命令.md` §6）：

```text
load_inputs → parse_toc → init_or_load_progress → generate_batch → persist_skeleton → finalize
```

PR1 `init_or_load_progress` 简化为「仅 init, 不读」——读 `进度.json` 与 `continue` 续跑推 PR2。

**理由**：
- 与 `write_chapter.py::build_writer_graph` 风格对称（6 节点 vs 6 节点；同样 `_set_deps` 模块级 deps 注入）
- `generate_batch` 是循环节点（StateGraph 自环或外层 for+cursor），批内串行（prev_closing 串递），批间 PR1 串行（per `TODO/骨架命令.md` §10）
- `finalize` 写 `骨架/索引.md` + 构造 `WorkflowResult`

**替代方案 A：5 节点（合并 init_or_load_progress 到 load_inputs）** —— 否决。`load_inputs` 是只读（读 AGENT / 大纲 / 目录）；`init_or_load_progress` 是写 `进度.json`（PR2）。两者 I/O 性质不同，混合会让 PR2 改动触及 `load_inputs` 单元测试。

**替代方案 A'：7 节点（拆 `persist_skeleton` 为 `write_chapter_file` + `update_progress`）** —— 否决。`write_chapter_file` 与 `update_progress` 是同一「单章完成」事件的两个副作用，合并为单节点 PR2 续跑逻辑更简单（continue 时跳过整节点）。

### 3. workflow 内 `Path.write_text` 直写，不扩白名单

**决定**（per `TODO/骨架命令.md` §5 + §8）：

```python
# skeleton_chapters.py::_persist_skeleton_node
chapter_path = project_root / "骨架" / volume / f"第{seq:03d}章.md"
chapter_path.parent.mkdir(parents=True, exist_ok=True)
chapter_path.write_text(rendered, encoding="utf-8")
```

**理由**：
- 与 `write_chapter._persist_outputs_node:323-326` 同款（`manuscript_dir = project_root / "草稿"; ... chapter_path.write_text(draft, encoding="utf-8")`）
- `DEFAULT_WRITE_WHITELIST`（per `tools/runtime.py:18-41`）当前不含 `骨架`，扩白名单需审计跨模块影响面
- PR1 走 workflow 内直写，**不**经 `ToolRuntime.safe_path()`，避免引入新的白名单授权边界

**替代方案 A：扩 `DEFAULT_WRITE_WHITELIST` 加 `"骨架"`** —— 否决。扩白名单影响所有 builtin tool（`safe_write_file` / `safe_edit_file`），需要审计下游所有调用点。workflow 内直写 blast radius 限于 `skeleton_chapters` 单文件。

**替代方案 B：用 `Path.write_text` 但加 `safe_path()` 兜底** —— 否决。`safe_path()` 设计给 tool runtime 调用方使用；workflow 内已知 project_root 范围，不需要越界检查。

### 4. deterministic 模式 strict raise

**决定**（per `TODO/骨架命令.md` §4 + §7 + 与 `_plan_chapter_node` 对齐，per MEMORY 2026-07-14）：

```python
# skeleton_chapters.py::_call_generate_open_close
if prose_client is None or getattr(prose_client, "name", "") == "deterministic":
    raise RuntimeError("skeleton_chapter 需要真实 LLM；请设置 WRITER_API_KEY 环境变量后重启")
```

**理由**：与 `write_chapter.py::_call_plan_chapter:428-432` 同款；不接受「deterministic 时退化为模板」混合策略。CLI 启动预检 `repl.py::_warn_deterministic_prose_client` 在 PR2.5 扩到 `/骨架`。

**替代方案 A：deterministic 时退化模板** —— 否决。会让生成的"骨架"全是模板文本，对 PR3 `/创作` 消费毫无意义。

### 5. AGENT.md 双行消费复用既有 reader

**决定**（per `TODO/骨架命令.md` §7）：

```python
from writer.project.state import read_genre_from_agent, read_architecture_method_from_agent
genre = read_genre_from_agent(agent_md)  # "玄幻" / "言情" / ...
method = read_architecture_method_from_agent(agent_md)  # "雪花法" / "三幕结构" / ...
```

**理由**：per MEMORY 2026-07-16 决策，`/大纲` 与 `/目录` 都复用这对 reader；`/骨架` 同款，零新加 helper。

**替代方案 A：新加 `read_skeleton_meta_from_agent`** —— 否决。重复抽象，blast radius 大。

### 6. `WorkflowResult` 部分完成用 `status="failed"` + `metrics["partial_chapters"]`

**决定**（per `TODO/骨架命令.md` §6 + §11）：

PR1 中断场景有限（deterministic raise / 无目录 / 无大纲 / S3 / 已有骨架），均映射到 `status="failed"`。PR2 引入 `进度.json` 后，中断保留「已写 N 章」状态用：

```python
return WorkflowResult(
    status="failed",
    chunks=(f"[workflow] skeleton_chapters 中断; 已完成 {n}/total 章",),
    artifacts={"progress_path": Path(progress_path)},
    metrics={"partial_chapters": n, "mode": args.mode, "volume": args.volume or ""},
)
```

**理由**：`runner/runner.py:392-407` 把 `status="pending"` **专用于** `needs_rewrite` 信号（per `runner/events.py:24` 注释：`workflow_pending` 已从 `DoneReason` 删除）。滥用会让 REPL 误判为「需要重写」。

**替代方案 A：扩 `status` 加 `"partial"` 枚举** —— 否决。`WorkflowStatus` Literal 改动是 breaking change，影响 `_run_workflow` 全部 3 分支映射；用 `metrics["partial_chapters"]` 表达更轻量。

**替代方案 B：用 `status="pending"` + `metrics["decision"]="interrupted"`** —— 否决。`pending` 单义不可破；未来若需「自然中断」与「真失败」区分，应扩 `decision` enum 不动 `status`。

### 7. 章节 ID 双层 + 同卷区间

**决定**（per `TODO/骨架命令.md` §2 + §9）：

- `chapter_id` 用双层 `1.1` / `1.2` / `2.1` 形式（与既有 `WriteChapterArgs.chapter_id="1.1"` 对齐，per `workflows/params.py:32`）
- 区间解析仅支持「同卷内」：`1.1-1.20` → `mode=range, start="1.1", end="1.20"`
- 跨卷 `1.1-2.20` PR1 接受但解析为「start 卷 到 end 卷的章节子集」（per `TODO/骨架命令.md` §9 注释），具体语义 PR2 再细化
- 单层 `1-20` **不接受** → `extract_skeleton_args` raise `SkillError("无效章节范围: 应为 X.Y-X.Z 形式")`

**理由**：与既有 `chapter_id` 约定对齐；不引入新编号方案。

### 8. `_set_deps(deps)` / `_get_deps()` 模块级 deps 注入

**决定**：与 `write_chapter.py:367-396` 同款。

```python
# skeleton_chapters.py
_WORKFLOW_DEPS: RunnerDeps | None = None

def _set_deps(deps: RunnerDeps) -> None:
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = deps

def _get_deps() -> RunnerDeps:
    if _WORKFLOW_DEPS is None:
        raise RuntimeError("skeleton_chapters node called without _set_deps")
    return _WORKFLOW_DEPS

def run(ctx: RunnerContext, deps: RunnerDeps) -> WorkflowResult:
    _set_deps(deps)
    try:
        # graph invoke
        ...
    finally:
        _reset_deps()
```

**理由**：LangGraph 节点是接受 `state` 返回部分状态的裸函数；模块级 context 是 LangGraph 官方 run-scoped state 模式。

## Risks / Trade-offs

[Medium: deterministic 模式 strict raise 可能误伤开发环境]
→ **Mitigation**:
(1) PR1 在 `test_skeleton_raises_when_deterministic` 守住契约；
(2) PR2.5 在 `repl.py::_warn_deterministic_prose_client` 同步扩到 `/骨架`；
(3) 错误消息明确「请设置 WRITER_API_KEY」+ 指向文档

[Low: 单章 LLM 调用超时]
→ **Mitigation**:
(1) PR1 不设超时（与 `write_chapter._draft_chapter_node` 一致，后者也无限时）；
(2) PR2 加 `max_chapters_per_turn` 预算（per `TODO/骨架命令.md` §10）；
(3) 失败即 `status="failed"` + `partial_chapters`，REPL 显示已写数量

[Low: 中文目录 `骨架/<卷>/` 跨平台兼容性]
→ **Mitigation**:
(1) 与既有 `草稿/` / `大纲/` / `人物/` / `人物/主要人物.md` 同款中文目录验证 OK（per `project/workspace.py`）；
(2) PR1 测试覆盖 Linux/macOS（CI 仅 macOS，per MEMORY.md「验证基线」）

[Low: 双层章节 ID `1.10 > 1.2` 字典序 vs 数值序]
→ **Mitigation**:
(1) PR1 仅支持「同卷内」区间，章节数 ≤ 30 时字典序 = 数值序；
(2) PR2 引入「数值序区间解析」+ 章节 ID 排序 helper

[Low: LLM 单章 prompt 包含 prev_closing 串递可能让 token 超限]
→ **Mitigation**:
(1) PR1 上章结尾截前 500 字符；
(2) PR2 引入「卷级摘要代替逐章结尾」机制（per `TODO/骨架命令.md` §10 批间并行注释）

## Migration Plan

**部署步骤**（apply 阶段按 tasks.md 顺序）：
1. 写 `SkeletonArgs` + `extract_skeleton_args`（params.py + 6 项测试）
2. 写 `skeleton_chapters.py` 6 节点图 + 4 个 helper + `_state_to_result`
3. 注册到 `workflows/__init__.py::WORKFLOWS`
4. 改 `routing/intent_router.py::RuleBasedIntentRouter.route` 加 `/骨架` 分支 + fallback 文案
5. 改 `cli/main.py` 帮助文案
6. 写 `tests/test_skeleton_chapters.py` 8 项 + `tests/test_engine.py` 1 项
7. validate + 留 PR1.5 / PR2 / PR3 follow-up

**回滚策略**：`git revert` 整个 commit。新增文件（`skeleton_chapters.py` / `test_skeleton_chapters.py`）随 revert 删除；修改文件（`params.py` / `__init__.py` / `intent_router.py` / `cli/main.py`）回滚到 PR1 前状态。无破坏性：PR1 仅新增能力，不改现有命令语义。

**兼容窗口**：无 main spec 改动（`intent-routing` 走 ADDED Requirement，骨架生成新 capability 不冲撞）。

## Open Questions

无 — 5 个 PR1 范围内 open questions 已在 proposal.md「Open Questions (PR1 范围内已决)」段确认。后续 PR（PR1.5 / PR2 / PR2.5 / PR3）单独走新 OpenSpec change。