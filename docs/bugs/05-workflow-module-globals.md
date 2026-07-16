# Bug 05: 工作流用 module-global 注入 deps,并发场景串线

## 元信息

| 严重程度 | 🟠 Major |
|---|---|
| 状态 | 待修 |
| 发现日期 | 2026-07-09 |
| 关联文件 | `src/writer/workflows/write_chapter.py:87-127`、`src/writer/workflows/write_chapter.py:372-402`、`src/writer/workflows/review_chapter.py:81-137`、LangGraph `StateGraph.add_node` 文档 |
| 测试盲区 | 测试串行 `run()`,从不 `asyncio.gather` 两个 workflow;从未断言模块级 `_WORKFLOW_DEPS` / `_REVIEW_DEPS` 不存在 |

## 1. 现象(Symptom)

### 可复现步骤(理论推演 + 代码审查)

1. REPL 进程内有两个项目 `proj_a` / `proj_b`,各自有独立 `Engine`(虽然当前 REPL 只支持单 session,但 Engine 抽象允许多实例 — 留给未来的多 tab / multi-agent 设计)
2. 用户并行触发 `/创作 proj_a/1.1` + `/审核 proj_b/1.1`(假设并发)
3. `write_chapter.run(ctx_a, deps_a)` 与 `review_chapter.run(ctx_b, deps_b)` 各自调用 `_set_deps(...)` 写入**模块级**全局
4. **竞态**:`_WORKFLOW_DEPS = deps_a` 与 `_REVIEW_DEPS = deps_b` 同时执行,但因为是不同模块(`write_chapter._WORKFLOW_DEPS` vs `review_chapter._REVIEW_DEPS`),互相不冲突 — **这里其实没有串线**(每个模块自己的全局)
5. ❌ **真正的 bug**:`write_chapter.run()` 在 `graph.invoke` 期间 `finally: _reset_deps()` 把 `_WORKFLOW_DEPS = None`。**如果**两个 `write_chapter.run()` 并发,且在 graph 内部某节点 `await asyncio.sleep(0)` 让出执行权:
   - `run_a` 调用 `_set_deps(deps_a)` → `_WORKFLOW_DEPS = deps_a`
   - `run_a` 进入 `graph.invoke` → 节点 `_draft_chapter_node(state)` 调用 `_get_deps()` 返回 `deps_a` ✓
   - 让出执行权给 `run_b`
   - `run_b` 调用 `_set_deps(deps_b)` → `_WORKFLOW_DEPS = deps_b` ✗
   - 让出执行权回 `run_a`
   - `run_a` 节点继续 → 调 `_get_deps()` 返回 `deps_b` ✗ **(串线!)**
6. 用户看到:proj_a 的章节内容写到 proj_b 的 manuscript/ 下,或者 `foreshadow_search` 查到 proj_b 的伏笔列表

### 代码引用

```python
# src/writer/workflows/write_chapter.py:87-127 (run + module global)
_WORKFLOW_DEPS: RunnerDeps | None = None

def _set_deps(deps: RunnerDeps) -> None:
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = deps

def _reset_deps() -> None:
    global _WORKFLOW_DEPS
    _WORKFLOW_DEPS = None

def run(ctx: RunnerContext, deps: RunnerDeps) -> WorkflowResult:
    ...
    _set_deps(deps)   # ← 模块全局写入
    try:
        graph = build_writer_graph(checkpointer=checkpointer)
        ...
        final_state = graph.invoke(initial_state, config=config)
    finally:
        _reset_deps()   # ← 不管中途如何,finally 都重置
    return _state_to_result(final_state, chapter_id=args.chapter_id)

# src/writer/workflows/write_chapter.py:372-402 (模块级绑定 + 节点 _get_deps)
_WORKFLOW_DEPS: RunnerDeps | None = None
def _get_deps() -> RunnerDeps:
    if _WORKFLOW_DEPS is None:
        raise RuntimeError("write_chapter node called without _set_deps; ...")
    return _WORKFLOW_DEPS

# 节点函数:
def _draft_chapter_node(state: WriterState) -> WriterState:
    ...
    # 这里 _call_prose_client 内 _get_deps() 拿的是模块全局
    draft = _call_prose_client(...)

def _review_gate_node(state: WriterState) -> WriterState:
    deps = _get_deps()   # ← 模块全局,可能跟外层 run() 的 deps 不一致
    ...
```

```python
# src/writer/workflows/review_chapter.py:81-137 (同样的 pattern)
_REVIEW_DEPS: RunnerDeps | None = None
def _set_deps(deps): ...
def _reset_deps(): ...
def run(ctx, deps):
    _set_deps(deps)
    try:
        graph = build_reviewer_graph()
        ...
        final_state = graph.invoke(...)
    finally:
        _reset_deps()
```

### 旁证:为什么 LangGraph 节点签名接受 `state` 即可

LangGraph `StateGraph.add_node(name, fn)` 要求 `fn` 接受 `state` 参数(默认),这是 LangGraph 的硬约束(per LangGraph 文档)。**解决方法是用闭包或 partial 把 deps 绑进去** — 但当前代码选择"绕开签名,用 module global"。

## 2. 根因(Root Cause)

LangGraph 节点函数签名是 `(state) -> state`,不能接额外参数(否则 LangGraph 调用 `fn(state)` 会传错)。代码用了"trick": 用模块全局 `_WORKFLOW_DEPS` 在 `run()` 开始时 set、结束时 reset,节点内部 `_get_deps()` 读全局。

这个 trick 的前提:**同一时刻只有一个 `run()` 调用栈**,即串行执行。一旦并发,模块全局在 await 让出点被另一个 `run()` 覆盖,后续节点读到错误 deps。

### 数据流图

```
协程 A (run_a, ctx_a, deps_a):           协程 B (run_b, ctx_b, deps_b):
    _set_deps(deps_a)                          │
    global = deps_a                            │
    graph.invoke(state_a)                      │
        ↓                                      │
    节点 _draft_chapter_node(state_a)          │
        draft = _call_prose_client(...)        │
        _get_deps() → deps_a ✓                │
        [await 让出]  ←──────────────────┐     │
                                          │     │
                                          │     _set_deps(deps_b)
                                          │     global = deps_b ✗
                                          │     graph.invoke(state_b)
                                          │         ↓
                                          │     节点 _draft_chapter_node(state_b)
                                          │         draft = _call_prose_client(...)
                                          │         _get_deps() → deps_b ✓
                                          │         [await 让出]  ←────┐
                                          │                            │
    [恢复]                                   │                            │
    _call_prose_client 继续                  │                            │
    _get_deps() → deps_b ✗ ←─ 串线!        │                            │
    prose_client.generate_text(deps_b 内部配置)│                            │
        ↓                                                                      │
    写到 deps_b 的项目根 ✗                                                   │
```

## 3. 影响范围(Blast Radius)

| 受影响表面 | 触发条件 | 严重性 | 当前绕过方式 |
|---|---|---|---|
| `write_chapter` 并发执行两个 run | 用户/未来多 agent 设计并发跑 `/创作` | 🔴 高(章节写到错误项目根) | 当前 REPL 串行,理论 bug 未触发 |
| `review_chapter` 并发执行两个 run | 用户/未来 multi-agent 跑 `/审核` | 🔴 高(审核读了错误项目的伏笔) | 同上 |
| `write_chapter` 与 `review_chapter` 各自独立 | 模块全局分属不同模块,不冲突 | — | — |
| 单次串行调用 | `await` 不让出 → 全局不被覆盖 | — (正常工作) | 当前所有测试 |
| `Engine` 单实例 + 串行 REPL | 当前部署形式 | — (无 bug 触发条件) | — |
| `_WORKFLOW_DEPS` 未设置时节点被调 | 测试不调 `run()` 直接 `graph.invoke(state)` | 中(`RuntimeError`,不是数据损坏) | 测试必须 `_set_deps()` 后再 invoke |

**注**:此 bug 与"是否有并发调用"严格绑定。当前 REPL 是单协程串行(每次 `await run_runner()` 走完才接下一个用户输入),所以**当前生产路径下未触发**。但 Engine 的多实例设计、未来的 multi-tab / multi-agent 扩展一定会触发。

## 4. 修复方案(Fix)

### 方案 A(★ 主推):`build_writer_graph` / `build_reviewer_graph` 接 `deps`,用闭包注入

让 `build_*_graph` 接受 `deps`,在 `add_node` 时用 lambda 闭包把 deps 绑进节点函数。

```python
# fix proposal — src/writer/workflows/write_chapter.py

def build_writer_graph(
    *, checkpointer: Any | None = None, deps: RunnerDeps | None = None
) -> CompiledStateGraph:
    """Build the 5-node write_chapter graph.

    ``deps`` is optional — when provided, each node receives it via closure
    instead of reading the module-global ``_WORKFLOW_DEPS``. Production
    callers always pass ``deps``; the module-global fallback is retained
    only for legacy test surfaces that build the graph directly.
    """
    graph = StateGraph(WriterState)
    # 闭包注入 deps(避免模块全局)
    graph.add_node("prep_context",
                   lambda s: _prep_context_node(s, deps=deps) if deps else _prep_context_node(s))
    graph.add_node("plan_chapter",
                   lambda s: _plan_chapter_node(s, deps=deps) if deps else _plan_chapter_node(s))
    graph.add_node("draft_chapter",
                   lambda s: _draft_chapter_node(s, deps=deps) if deps else _draft_chapter_node(s))
    graph.add_node("proofread",
                   lambda s: _proofread_node(s, deps=deps) if deps else _proofread_node(s))
    graph.add_node("review_gate",
                   lambda s: _review_gate_node(s, deps=deps) if deps else _review_gate_node(s))
    graph.add_node("persist_outputs",
                   lambda s: _persist_outputs_node(s, deps=deps) if deps else _persist_outputs_node(s))
    ...
    return graph.compile(checkpointer=checkpointer)


# 节点函数签名加 deps
def _draft_chapter_node(state: WriterState, *, deps: RunnerDeps | None = None) -> WriterState:
    deps = deps or _get_deps()  # 兜底保留 module-global 以防异步并发
    ...


def run(ctx: RunnerContext, deps: RunnerDeps) -> WorkflowResult:
    args = extract_write_chapter_args(ctx.user_input)
    initial_state = {...}
    checkpointer, close_checkpointer = _build_checkpointer(ctx.project_root)
    # 关键:把 deps 传进 build_*_graph
    graph = build_writer_graph(checkpointer=checkpointer, deps=deps)
    config = {...}
    prose_client = _require_prose_client(deps)
    initial_state["prose_client_name"] = prose_client.name
    # 删除 _set_deps / _reset_deps 调用
    try:
        final_state = graph.invoke(initial_state, config=config)
    finally:
        close_checkpointer()
        # 删除 _reset_deps()
    return _state_to_result(final_state, chapter_id=args.chapter_id)
```

**风险**:LangGraph 节点函数接受 `(state)`,lambda 包装后变成 `lambda s: fn(s, deps=deps)` — 闭包能保留 deps 引用,LangGraph 调 `node(state)` 时 lambda 接受 state → 调 fn(state, deps=deps) ✓。

**保留 module-global**:`_get_deps()` 仍存在作为兜底(供测试直接调 `graph.invoke(state)` 而不通过 `run()` 的旧路径)。但 `run()` 不再 set/reset。

### 方案 B(备选):用 LangGraph `RunnableConfig` 传 deps

LangGraph 支持 `add_node(name, fn)` + `graph.invoke(state, config={"configurable": {"deps": deps}})`,节点函数内部从 `config` 读 deps。但当前 LangGraph API 中节点函数的 config 注入需要 `config_schema`,复杂度高于 lambda 闭包。

**否决理由**:LangGraph `config` 设计用于"thread_id / checkpointer"等元数据,语义上不是 deps 通道;且与现有 `engine_config.cfg` 重名。

### 方案 C(备选):用 `functools.partial` 替代 lambda

```python
from functools import partial
graph.add_node("draft_chapter", partial(_draft_chapter_node, deps=deps))
```

**否决理由**:与方案 A 等价但 lambda 更直观。`partial` 适用于节点函数无需 kwargs 的情况(这里要 `deps=deps` 显式 kwarg,lambda 形式更清晰)。

### 方案 D(备选):完全删 module-global,节点函数签名为 `(state, deps)`

LangGraph `add_node(name, fn)` 调 `fn(state)` — **不支持额外参数**。需要 lambda 包装或 `RunnableConfig` 注入,本质上回到方案 A/B。方案 D 不可行。

## 5. 验证步骤(Manual Reproduction)

直接并发验证(单元测试级):

```python
# uv run python - <<'PY'
import asyncio
from pathlib import Path
from writer.tools import ToolRuntime
from writer.runner.deps import _DefaultRunnerDeps
from writer.workflows import run as wc_run
from writer.runner.context import RunnerContext

async def main():
    ctx_a = RunnerContext(user_input="/创作 1.1", project_root=Path("/tmp/proj_a"))
    ctx_b = RunnerContext(user_input="/创作 1.1", project_root=Path("/tmp/proj_b"))
    runtime_a = ToolRuntime(project_root=Path("/tmp/proj_a"))
    runtime_b = ToolRuntime(project_root=Path("/tmp/proj_b"))
    deps_a = _DefaultRunnerDeps(...with runtime_a...)
    deps_b = _DefaultRunnerDeps(...with runtime_b...)

    # 并发触发
    results = await asyncio.gather(
        wc_run(ctx_a, deps_a),
        wc_run(ctx_b, deps_b),
    )
    # 期望(buggy): 某 result 的 draft_path 指向错误的项目根
    # 期望(修复后): 两个 result 的 draft_path 各自对应 ctx_a.project_root / ctx_b.project_root
    for r in results:
        print(r.artifacts.get("draft_path"))
asyncio.run(main())
PY
```

```bash
# 间接验证:确认 _WORKFLOW_DEPS 模块变量不存在
uv run python -c "from writer.workflows import write_chapter; assert not hasattr(write_chapter, '_WORKFLOW_DEPS')"
# 期望(buggy): AssertionError
# 期望(修复后): 无输出

# 同样对 review_chapter:
uv run python -c "from writer.workflows import review_chapter; assert not hasattr(review_chapter, '_REVIEW_DEPS')"
```

## 6. 回归测试用例清单

| 测试文件 | 测试名 | 关键断言 | 类型 |
|---|---|---|---|
| `tests/test_workflows_write_chapter.py` | `test_concurrent_writers_isolated_deps` | `asyncio.gather(write_chapter.run(ctx_a, deps_a), write_chapter.run(ctx_b, deps_b))` 并发,断言各自 `result.artifacts["draft_path"]` 指向各自 project_root | NEW |
| `tests/test_workflows_review_chapter.py` | `test_concurrent_reviewers_isolated_deps` | 同上对 review_chapter | NEW |
| `tests/test_workflows_write_chapter.py` | `test_module_globals_removed` | `assert not hasattr(writer_module, "_WORKFLOW_DEPS")` 或断言 `_set_deps / _reset_deps` 函数已删除 | NEW |
| `tests/test_workflows_review_chapter.py` | `test_module_globals_removed` | 同上对 review_chapter | NEW |
| `tests/test_workflows_write_chapter.py` | `test_build_writer_graph_accepts_deps` | `build_writer_graph(deps=stub_deps)` 返回的 CompiledStateGraph 节点闭包能正确读 deps,无需 module global | NEW |
| `tests/test_workflows_write_chapter.py` | `test_run_no_longer_sets_module_global` | spy `writer.write_chapter._set_deps`,断言 `run()` 不调用它 | NEW |
| `tests/test_workflows_write_chapter.py` | 现有 fixture / stub | 旧测试如果直接 `_set_deps(deps); graph.invoke(state)` 必须改用 `build_writer_graph(deps=deps)` | MODIFY |
| e2e | `tests/e2e/test_repl_concurrent_workflow.py` | REPL 触发两次 `/创作` 命令在同一个 session 内(模拟并发场景),assert 两份 draft 文件路径正确 | NEW e2e |

## 7. 风险与遗留(Risks & Follow-ups)

### 修复后仍未解决的相邻问题

- **LangGraph `checkpointer` 序列化兼容**:Lambda 闭包不可 pickle,如果未来切到 `SqliteSaver` + 多进程部署,需要 `pickle.dumps(graph)` 必须能成功 — 闭包(lambda + deps 对象)pickle 行为依赖 deps 内部组件是否可序列化。**留给未来的 LangGraph 持久化提案**。
- **节点函数签名变化破坏旧测试**:所有直接调 `_draft_chapter_node(state)` 的测试必须改成 `_draft_chapter_node(state, deps=deps)`。**预估 5-10 个测试需要更新**。
- **`_get_deps` 兜底保留 vs 删除**:方案 A 保留 `_get_deps()` 作为旧路径兜底(测试直接 `graph.invoke(state)` 而不通过 `run()`)。如果完全删除,旧 fixture 必须重构。如果保留,需要明确"测试 only"语义。
- **`engine.config.RunnerConfig.cfg` 仍未使用**:`ReActAgent.run(..., cfg)` 当前 `del cfg`,未读取。如果未来需要 per-loop config,可考虑让 `build_*_graph` 也接 cfg。

### 与 OpenSpec 的关系

- **未来 change 提案建议名**:`fix-workflow-concurrent-deps-injection`
- **需要 spec delta**:`engine-loop` spec 的 `#### Scenario: Concurrent workflow execution` 需新增 scenario 描述 deps 隔离
- **文档同步**:`备忘 03-审核工作流.md` 和 `备忘 04-写章节工作流.md` 中"module global deps"段需更新为"闭包注入 deps"
- **`write_chapter.py:362-369` 的注释需要重写**:当前注释说"thread deps through module-level context set by run() before each graph invocation. This is the same pattern LangGraph's own examples use for run-scoped state. Production code paths (CLI / REPL) always call run, which sets the context" — 修复后这段注释应改为"deps 通过 build_writer_graph(deps=...) 闭包注入,无 module global"

### 关联 bug

- 与 [Bug 1](./01-tool-loop-not-rebound.md) **正交**:Bug 1 是 `tool_loop` stale reference(同一 session 内换 project_root),Bug 5 是 `deps` module-global stale(跨 session 并发)。两者独立修复。
- 与 [Bug 3](./03-review-chapter-always-deterministic.md) **间接相关**:Bug 3 修后 `review_chapter` 真的调 LLM,会增加 `_llm_review` 调用次数,放大了 Bug 5 的潜在影响(LLM 调用耗时更长,await 让出点更多)。建议 Bug 5 与 Bug 3 同期修复。
- **未来与 LangGraph 持久化提案联动**:本修复后,`build_writer_graph(checkpointer=...)` + 闭包 deps 在 SQLite 持久化路径下的行为需重新验证。