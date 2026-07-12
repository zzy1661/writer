# Bug 01: `set_project_root` 后 `tool_loop` 没重建,LLM 工具调用仍指向旧根目录

> 🔴 **Blocker** — 该 bug 直接导致 `/init` 后切换项目时,LLM 工具调用静默指向旧 `project_root`,用户级错误(可能读到旧项目的状态、写错位置)。是 5 个 bug 中唯一标记 Blocker 的,因为它会跨 turn 影响多轮对话且无明确错误信号。

## 元信息

| 严重程度 | 🔴 Blocker |
|---|---|
| 状态 | 待修 |
| 发现日期 | 2026-07-09 |
| 关联文件 | `src/writer/session/engine_session.py:94-154`、`src/writer/engine/deps.py:212-243`、`src/writer/engine/deps.py:333-339`(`LLMToolLoop` 构造) |
| 测试盲区 | 测试 `set_project_root` 后只断言 `deps.tool_runtime.project_root == new_root`,从未断言 `deps.tool_loop._runtime.project_root == new_root`(因为根本没想到) |

## 1. 现象(Symptom)

### 可复现步骤

1. REPL 启动 → 在 `project_a/` 下 `/init 穿越题材 --genre 其他`
2. `LLMToolLoop` 在 `production_deps()` 时构造,绑定 `runtime_a`(见 `engine/deps.py:333-339`)
3. 用户切换: `set_project_root(project_b/)`(任何触发方式 — 比如改 `.env` 的 `WRITER_PROJECT_ROOT` 或外部命令)
4. `EngineSession.set_project_root()` 重建 `tool_runtime = ToolRuntime(project_root=project_b)`,通过 `rebind_tool_runtime(new_runtime)` 把 deps 里的 runtime 替换掉
5. ❌ **但**:`deps.tool_loop` 内部 `self._runtime` 仍然是 `runtime_a`,因为 `LLMToolLoop` 构造时硬绑 runtime,没有 rebind 入口
6. 下一次 LLM 工具循环调用: `self._registry.invoke(tool_name, self._runtime, **arguments)` → 所有 `safe_path()` / `safe_list_dir()` / `safe_write_file()` 都基于 `runtime_a.project_root`
7. 用户看到的结果:LLM 报告"已写到 `.writer/cache/x.md`",但实际上写到 `project_a/.writer/cache/x.md`;或者读到的章节是 `project_a/manuscript/...` 的旧内容

### 代码引用

```python
# src/writer/session/engine_session.py:94-154 (set_project_root)
def set_project_root(self, new_root: Path | None) -> None:
    ...
    new_runtime = ToolRuntime(project_root=resolved)
    self.deps = self.deps.rebind_tool_runtime(new_runtime)   # ← 只 rebind runtime
    self.refresh_project_state()
    self.refresh_project_genre()

    new_registry = built_directive_registry(project_root=resolved)
    self.deps = self.deps.rebind_directive_registry(new_registry)

    new_agent_registry = built_agent_registry(project_root=resolved)
    self.deps = self.deps.rebind_agent_registry(new_agent_registry)
    # ↑ 这里有 rebind_tool_runtime / rebind_directive_registry / rebind_agent_registry
    #   但没有 rebind_tool_loop → Bug 1

# src/writer/engine/deps.py:184 (EngineDeps Protocol 字段)
tool_loop: LLMToolLoop | None   # ← 字段存在,但 rebind 入口缺失

# src/writer/llm/agent.py:147-149 (LLMToolLoop.__init__)
self._settings = settings
self._registry = registry
self._runtime = runtime    # ← 硬绑,无 rebind 入口
```

### 旁证:`rebind_*` 现有模式(2026-07-05 起逐步实装)

```python
# src/writer/engine/deps.py:212-243 (_DefaultEngineDeps)
def rebind_tool_runtime(self, new_runtime):
    return replace(self, tool_runtime=new_runtime)

def rebind_skill_registry(self, new_registry):
    return replace(self, directive_registry=new_registry)

def rebind_directive_registry(self, new_registry):
    return replace(self, directive_registry=new_registry)

def rebind_agent_registry(self, new_registry):
    return replace(self, agent_registry=new_agent_registry)
```

→ `rebind_tool_loop` 在 Protocol 和实现里都缺失,与上面 4 个 rebind 不对称。

## 2. 根因(Root Cause)

`EngineDeps` Protocol 设计时把 `tool_loop` 当作"启动时绑定、运行时不变"的资源(reasoning 见 `engine/deps.py:84` 注释"Forward-referenced as a string to keep the engine package free of direct ``writer.llm.*`` imports"),但 `LLMToolLoop` 内部硬绑 `_runtime`(因为构造时一次性 `bind_tools(tools)`)。`EngineSession.set_project_root()` 期望的所有 deps-level 资源都能被替换,但漏了 `tool_loop`。

### 数据流图

```
production_deps(project_root=A)
    └─ LLMToolLoop(settings, registry, runtime=A)  # self._runtime = A
                                ↓
User: set_project_root(B)
                                ↓
EngineSession.set_project_root(B):
    new_runtime = ToolRuntime(project_root=B)
    deps = deps.rebind_tool_runtime(new_runtime)    # ✓ deps.tool_runtime = runtime_B
    deps = deps.rebind_directive_registry(...)     # ✓ directive registry 重建
    deps = deps.rebind_agent_registry(...)         # ✓ agent registry 重建
    # ✗ 缺 rebind_tool_loop:
    deps.tool_loop._runtime 仍 = runtime_A          # ✗ 隐性 stale reference
                                ↓
LLM Tool Loop 下一次调用:
    self._registry.invoke(tool_name, self._runtime, ...)  # → runtime_A ✗
```

## 3. 影响范围(Blast Radius)

| 受影响表面 | 触发条件 | 严重性 | 当前绕过方式 |
|---|---|---|---|
| LLM 工具循环(规则 + LLM 双 provider 路径) | API key 配了 + 用户切换项目根 | 🔴 高(静默写错位置) | 整段重启 REPL,让 `production_deps` 重新构造 |
| `/init` 多项目复用同一 session | 同 session 内连续 `/init` 两个项目 | 🔴 高(第二个项目路径完全错乱) | 退出 REPL + 重新 `uv run writer` |
| `tool_loop=None` 部署(rule-only) | API key 未配 | — (空指针,done) | 无 |
| `prose_client` 类似问题? | **不存在**(prose_client 无 project_root 依赖) | — | — |
| `agent_registry` / `directive_registry` | 已经 rebind ✓ | — | — |

## 4. 修复方案(Fix)

### 方案 A(★ 主推):新增 `rebind_tool_loop` Protocol 方法

镜像现有 4 个 `rebind_*` 的对称设计。

```python
# fix proposal — src/writer/engine/deps.py (Protocol 扩展)

@runtime_checkable
class EngineDeps(Protocol):
    ...
    def rebind_tool_loop(
        self, new_loop: LLMToolLoop | None
    ) -> EngineDeps:
        """Return a new (or in-place mutated) ``EngineDeps`` with the
        ReAct-style tool loop swapped.

        Called by :meth:`writer.session.EngineSession.set_project_root`
        after ``tool_runtime`` has been swapped — the new loop must be
        constructed against the new runtime so its
        ``self._runtime`` points at the new project root.

        Pass ``None`` to keep the session in rule-only mode (no API key).
        Implementations free to return a new instance (default impl
        uses ``dataclasses.replace``) or mutate ``self``.

        Added 2026-07-09 to fix Bug 01 (tool_loop not rebound on
        project change).
        """
        ...

# fix proposal — src/writer/engine/deps.py (_DefaultEngineDeps 实现)
def rebind_tool_loop(self, new_loop):
    return replace(self, tool_loop=new_loop)

# fix proposal — src/writer/session/engine_session.py:set_project_root 末尾
from writer.llm.agent import LLMToolLoop  # lazy import 避免循环
new_loop: LLMToolLoop | None = None
if self.deps.tool_loop is not None:
    new_loop = LLMToolLoop(
        settings=self.deps.settings,
        registry=self.deps.tool_registry,
        runtime=new_runtime,   # ← 关键:绑新 runtime
    )
self.deps = self.deps.rebind_tool_loop(new_loop)
```

**改动文件清单**:
1. `src/writer/engine/deps.py` — Protocol 加方法 + 实现加方法
2. `src/writer/session/engine_session.py` — `set_project_root` 末尾加重建块
3. `tests/conftest.py`(如有)— 测试 stub `PlainDeps` 补 `rebind_tool_loop` 方法
4. `tests/test_engine_deps.py` — 新增 `test_production_deps_rebind_tool_loop` 测试
5. `tests/test_engine_session.py` — 新增 `test_set_project_root_rebuilds_tool_loop` 测试

### 方案 B(备选):在 `LLMToolLoop` 加 `rebind_runtime` 方法

```python
# src/writer/llm/agent.py
class LLMToolLoop:
    def rebind_runtime(self, new_runtime: ToolRuntime) -> None:
        self._runtime = new_runtime
        self._tools = to_langchain_tools(self._registry, new_runtime)
        self._bound_llm = (
            self._llm.bind_tools(self._tools) if not self._use_json_prompt else None
        )

# src/writer/session/engine_session.py
self.deps.tool_loop.rebind_runtime(new_runtime)  # 直接 mutate
```

**否决理由**:
1. `EngineDeps` 抽象层被绕过,session 层直接修改 deps 内部组件,违反 DI 边界设计(`engine/deps.py:212-216` 注释明示 `dataclasses.replace` 而非 in-place mutation)
2. `LLMToolLoop` 的 mutation 路径会与"原有 `self._tools` 已 bind"的 LC 协议冲突 — `bind_tools` 返回新对象,但 `_bound_llm` 可能被多个共享引用持有
3. 方案 A 的 Protocol 扩展是"已有 4 个 rebind_* 模式"的自然延续,边界更对称

### 方案 C(备选):`production_deps` 加 `tool_loop_factory` 注入

```python
def production_deps(*, tool_loop_factory: Callable | None = None, ...):
    ...
    if resolved.has_api_key:
        factory = tool_loop_factory or _default_tool_loop_factory
        tool_loop = factory(settings, tool_registry, tool_runtime)
```

**否决理由**:为单个调用点(`EngineSession.set_project_root`)引入工厂注入,过度设计;且 session 调用 production_deps 路径不变,需要在 session 加 factory 字段 → 复杂度高于方案 A。

## 5. 验证步骤(Manual Reproduction)

```bash
# 1. 创建项目 A,启动 REPL
cd /tmp
mkdir proj_a proj_b
WRITER_PROJECT_ROOT=/tmp/proj_a printf "/init 穿越题材 --genre 其他\n" | uv run writer
ls /tmp/proj_a/   # 确认 manuscript/ outline/ AGENT.md 都建好

# 2. 通过 REPL 切换到 proj_b(假设有 set_project_root 触发器)
# 注意:目前 REPL 没有内置命令切换项目根,需要外部 process 改 WRITER_PROJECT_ROOT
# 然后重新进入 — 但此时 session 是同一个,LLM 工具循环指向 proj_a
WRITER_PROJECT_ROOT=/tmp/proj_b printf "在 proj_b 创建 outline/大纲.md\n" | uv run writer

# 期望(buggy):
#   ls /tmp/proj_b/outline/  → ✗ 不存在
#   ls /tmp/proj_a/outline/  → ✓ 大纲.md 写到了 proj_a(静默错误!)

# 期望(修复后):
#   ls /tmp/proj_b/outline/  → ✓ 大纲.md 正确
#   ls /tmp/proj_a/outline/  → ✗ 不变
```

更直接的单元验证:

```python
# uv run python - <<'PY'
import asyncio
from pathlib import Path
from writer.config import Settings
from writer.engine.deps import production_deps
from writer.session.engine_session import EngineSession
from writer.tools import ToolRuntime

session = EngineSession(project_root=Path("/tmp/proj_a"))
session.set_project_root(Path("/tmp/proj_b"))
loop = session.deps.tool_loop
assert loop is not None
print(loop._runtime.project_root)   # 期望:/tmp/proj_b
# buggy 当前: /tmp/proj_a
PY
```

## 6. 回归测试用例清单

| 测试文件 | 测试名 | 关键断言 | 类型 |
|---|---|---|---|
| `tests/test_engine_session.py` | `test_set_project_root_rebuilds_tool_loop` | mock tool_loop 构造;`session.set_project_root(new)` 后 `deps.tool_loop._runtime.project_root == new` | NEW |
| `tests/test_engine_deps.py` | `test_production_deps_rebind_tool_loop` | `_DefaultEngineDeps.rebind_tool_loop(new_loop)` 返回新实例,`tool_loop == new_loop`,其他字段保留 | NEW |
| `tests/test_engine_deps.py` | `test_protocol_duck_typed_rebind_tool_loop` | PlainDeps stub hasattr check,补 `rebind_tool_loop` 后 `isinstance(stub, EngineDeps)` 通过 | NEW |
| `tests/test_engine_session.py` | `PlainDeps` | 测试 stub 补 `def rebind_tool_loop(self, new_loop): return self` | MODIFY |
| `tests/test_engine_session.py` | `test_set_project_root_none_clears_tool_loop` | API key 从有到无的 scenario(如测试 fixture 切换),`deps.tool_loop` 变 None | NEW |
| `tests/test_engine_session.py` | `test_set_project_root_with_no_api_key_keeps_tool_loop_none` | 无 API key 时 `set_project_root` 不抛 `LLMConfigError`,`tool_loop` 保持 None | NEW |
| e2e | `tests/e2e/test_repl_switch_project_root.py` | REPL 启动 + 切项目根 + 跑 LLM 工具循环,assert 写入文件路径正确 | NEW e2e |

## 7. 风险与遗留(Risks & Follow-ups)

### 修复后仍未解决的相邻问题

- **`LLMToolLoop._settings` 不 rebind**:换项目可能换 `.env` 中的 `OPENAI_API_KEY`(API key 不同)。`_settings` 仍是旧 settings,但 LLM 客户端(LangChain `ChatOpenAI`)是 lazy 构造的,所以**短期**没问题。若未来在 `_settings` 上读取 `temperature` 等字段,会失效。**留给未来的 `EngineDeps.rebind_settings` 提案**。
- **`prose_client` 同理**:不依赖 project_root,无需 rebind,但其内部 `RealProseClient` 持有 `_llm` 引用,_llm 来自旧 settings。**留给未来**。
- **`EngineConfig` 与 `cfg` 参数**:`LLMToolLoop.run(..., cfg: EngineConfig)` 当前 `del cfg`,未使用。重构时不需关注。

### 与 OpenSpec 的关系

- **未来 change 提案建议名**:`fix-tool-loop-rebind-on-project-change`
- **需要 spec delta**:`engine-loop` spec 的 `#### Scenario: Switch project root mid-session` 需新增一条 scenario 描述 `tool_loop` 必须 rebind
- **文档同步**:`备忘 16-EngineSession与跨轮状态.md` 中 `set_project_root` 段需补一行"tool_loop also rebound"

### 关联 bug

- 与 [Bug 4](./04-whitelist-vs-first-segment.md) **协同**:LLM 工具循环切到新 runtime 后,白名单匹配规则仍是新的(`runtime.allowed_write_paths` 来自 `ToolRuntime` 构造,`production_deps` 永远用 `DEFAULT_WRITE_WHITELIST`),所以 Bug 1 + Bug 4 同时修才能让"换项目后 LLM 写文件"完整工作。
- 与 [Bug 2](./02-action-answer-ignored-by-tool-loop.md) **正交**:system prompt 的 directive/agent body 注入不依赖 `tool_loop` 重建。
- 与 [Bug 5](./05-workflow-module-globals.md) **间接相关**:work flow module globals 是另一类 stale reference 问题,但两者独立修复。