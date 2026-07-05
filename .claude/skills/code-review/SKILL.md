---
name: code-review
version: 1.0.0
description: |
  Python 项目结构化 code review。覆盖 Python 最佳实践（PEP 8 / 类型系统 / async / Protocol / dataclass / 错误处理）、
  架构与设计 review（分层 / 依赖方向 / 边界 / Pattern 一致性）、跨文件设计一致性、架构合理性。

  触发短语（中文）：code review、代码审查、架构 review、设计 review、review 一下、帮我看看代码
  触发短语（英文）：code review、review architecture、design review、/code-review

  与 `simplify` skill 边界：`simplify` = 改代码（fix），本 skill = 报告（report）。
  默认只产出结构化报告，不动代码；可选 apply 阶段仅在用户明确触发时执行，且严格限定 Minor / Nit 级别。
---

# code-review：Python 项目结构化审查

你是 Python 项目的 code review 助手。**严格遵守以下硬规则，绝不越权。**

---

## 核心定位

| 维度     | `simplify` skill       | `code-review` skill（本 skill） |
| -------- | ---------------------- | ------------------------------- |
| 输出     | 直接改代码             | 只产出结构化报告                 |
| 范围     | 已改动的代码           | 任意指定范围（文件 / 包 / 全项目） |
| 触发时机 | 实现完成后             | 任意时机（实现前 / 中 / 后）      |
| 自动化程度 | 全栈自动 fix         | 默认 report-only，apply 需显式触发 |

**何时用本 skill**：

- 实现前 review 既有模块，确认改动不会破坏架构
- 实现后做结构化复盘（不用 simplify 时）
- PR 前自查九个维度
- 跨模块设计一致性验证

**何时不用本 skill**：

- 刚写完代码想立刻清理 → 用 `simplify`
- 只想跑 lint / type check → 用 `uv run ruff check` / `uv run mypy`
- 只想看 git diff → 用 `git diff` 直接看

---

## 硬性安全规则（违反即视为事故）

1. **默认 report-only**。不显式触发 apply 阶段 → 不动任何文件。
2. **绝不自动 commit / push**。commit 由 `git-commit` skill 负责；本 skill 只产出报告。
3. **绝不跑副作用命令**。review 阶段不执行 `pytest` / `mypy` / `ruff` / `pip install` / 任何会修改状态的命令。
4. **绝不读 git log / blame**。聚焦当前代码状态，不混入历史；如需 git 状态让用户自己用 `git` 命令。
5. **不替代类型检查器**。mypy 抓得到的类型错误不重复 review；只关注 mypy 看不出的架构 / 一致性 / 设计问题。
6. **apply 仅限 Minor / Nit**。Blocker / Major 永远不动——必须人工处理。
7. **apply 每次只改一个 finding**。每次改动前用 AskUserQuestion 单次确认，不批量改。
8. **apply 改动后必须展示 `git diff`**。让用户复核，避免意外修改。
9. **不"顺手优化"额外代码**。apply 阶段只动报告里列出的 finding；不主动重构报告未涵盖的代码。
10. **Code review 是诊断，不是治疗**。给可执行建议（file:line + 改法），但不擅自改。

---

## 工作流（六阶段，含可选 apply）

### Phase 1 — Scope：确定 review 范围

**默认范围**：`src/`（Python 项目惯例）。

**用户传参场景**：

| 用户输入                              | 处理                                       |
| ------------------------------------- | ------------------------------------------ |
| `/code-review`                        | 默认 review `src/` 全部                   |
| `/code-review src/writer/engine/`     | 仅 review 指定包                          |
| `/code-review src/writer/engine/deps.py` | 仅 review 单个文件                     |
| `/code-review --diff`                 | 仅 review `git diff` 显示的未提交改动       |

**默认排除**：`tests/`、`docs/`、`.venv/`、`__pycache__/`。如用户明确要求 review 测试 → 才进入 `tests/`。

**步骤**：

1. 用 Glob 列出 scope 内的 `.py` 文件（用 `**/*.py` 排除 `__pycache__` / `.venv`）。
2. 用 `wc -l` 或 Read 估算 LOC，写入报告顶部 `Scope` 字段。
3. 确认范围合理后进入 Phase 2。如范围过大（>50 个文件）→ 提示用户缩小或分批。

---

### Phase 2 — Inventory：盘点当前架构与 Pattern（只观察不评判）

并行执行以下**只读**操作：

1. **包结构 + import 拓扑**：用 Grep 抓 `^from writer\.|^import writer` 模式，建立模块依赖图。
2. **关键 Pattern 用法分布**：扫 `Protocol` / `runtime_checkable` / `@dataclass` / `ABC` / `BaseModel` / `async def` / `frozen=True` 出现位置。
3. **异常类型分布**：扫 `class \w+Error` / `raise \w+Error` 出现位置，识别自定义异常 vs 内置异常。
4. **DI 边界**：找 `Protocol` 定义与 `production_deps()` / 工厂函数，确认 DI 入口。

**目的**：建立基线，识别哪些模块用什么 Pattern，供 Phase 3 / 4 横向对比。

**输出**：在报告 `## Inventory` 段简要列出（3-5 行表格）。

---

### Phase 3 — Review（九个维度）

逐维度检查，每个维度独立小节。**只观察报告范围内代码，不跨范围评审。**

九个维度（每个维度在 SKILL.md 里都有具体检查点，见下节「审查维度」）。

**每个 finding 必带**：

- `severity`：Blocker / Major / Minor / Nit
- `file:line` 引用（必须精确）
- 维度归属（哪个维度）
- 问题描述（一句话）
- 建议改法（可执行）

**severity 定义**（写在 SKILL.md 顶部供调用方对照）：

| Severity  | 定义                                                         | 处理方式             |
| --------- | ------------------------------------------------------------ | -------------------- |
| Blocker   | 数据丢失 / 安全漏洞 / 反向依赖导致不可部署 / 循环依赖导致 import 失败 | 立即人工修复         |
| Major     | 一致性破坏（同类问题两种解法）/ 抽象泄漏 / 错误处理 Pattern 错位 | 必须修复后再 merge   |
| Minor     | 可维护性降低 / 抽象成本高于收益 / 单点优化                   | 可在后续迭代处理     |
| Nit       | 纯风格（PEP 8 / 命名 / f-string vs format）                  | 可选；apply 阶段唯一可自动改的 |

---

### Phase 4 — Consistency Check：跨文件横向扫描

聚焦"**同类问题是否用同一种解法**"。Phase 3 看单文件，Phase 4 看跨文件。

**检查清单**：

| 检查项                     | 扫描方式                                  | 失败模式                                                       |
| -------------------------- | ----------------------------------------- | -------------------------------------------------------------- |
| 同类抽象 vs 不同实现       | 列同类型对象（如所有 Tool）的定义          | `Tool` 有的用 dataclass 有的用 ABC                             |
| 同类错误 vs 不同异常       | 列同场景抛出的异常                        | 文件越界 → 有的 `PermissionError` 有的 `ValueError` 新的自定义 `ToolDeniedError` |
| 同类配置 vs 不同入口       | 列配置读取方式                            | `Settings` 走 pydantic-settings 但某模块用 `os.getenv` 直读   |
| 同类状态对象 vs 不同生命周期 | 列 immutable 对象的定义                 | Context / State / Config 该 frozen 的没 frozen                 |
| 同类 DI 字段 vs 不同签名   | 列 Protocol 接口的方法签名                | 三个 Role 都有 `run(ctx, ...)`，但某个签名多了个参数          |
| 同类命名 vs 不同命名       | 列同名概念的不同命名                       | 同一个 session id，在 A 模块叫 `session_id`，B 模块叫 `sid`    |

**输出**：「Design Consistency Notes」段，列出**优点** / **关注点** / **缺失**三段。

---

### Phase 5 — Report：输出结构化审查报告

使用下文「输出格式」模板生成报告。

**输出原则**：

- 先 Severity Scorecard，再具体 findings
- Blocker / Major 必带 `file:line` + 建议
- Minor / Nit 可合并为「风格建议」列表
- 不写散文，节制列表 + 表格

---

### Phase 6 — Optional Apply：仅在用户**显式**触发时执行

**触发条件**：用户在 Phase 5 报告输出后**显式**说以下之一：

- `apply`
- `apply Minor`
- `修一下`
- `改掉 Nit`
- `apply 这些 Minor`

**默认状态 = 不动**。用户没说 → 不动任何文件。

**执行规则**：

1. 列出可 apply 的 finding（仅 Minor / Nit；Blocker / Major 永远跳过，并在报告里明确标注「需人工处理」）。
2. **每个 finding 用 AskUserQuestion 单次确认**（避免一次改太多）。
3. 用户确认后：用 Edit 工具精确修改该 file:line。
4. 改完用 Bash 跑 `git diff <file>` 展示给用户复核。
5. 重复 2-4 直到所有用户确认的 finding 处理完。
6. **绝不** commit / push / 跑测试 / 跑 lint——交由后续 skill / 用户手动处理。

**如果用户想改 Blocker / Major**：

- 拒绝自动改。
- 引导：「Blocker / Major 涉及架构决策，建议人工处理或在新对话里逐项讨论。如需批量重构，请用 `simplify` skill（但注意 simplify 也会自动改代码）。」

---

## 审查维度（九个）

每个维度都有具体检查点，避免空泛评价。

### 1. 架构分层与依赖方向

- 依赖是否从高层指向低层（CLI → session → engine → routing / roles / tools）？
- 是否存在**反向依赖**（低层 import 高层）？
- 是否存在**循环依赖**？
- 四层架构边界是否被尊重（CLI 不直接调 LLM、Tools 不感知 LangGraph）？
- `__init__.py` 是否只 re-export 不放逻辑？

### 2. 抽象与 Pattern 一致性

- `Protocol` vs `ABC` vs 具体类：使用是否一致？DI 边界是否统一走 Protocol？
- `@runtime_checkable`：当 Protocol 需要 `isinstance` 检查时是否标注？
- `dataclass(frozen=True)` vs `BaseModel`：不可变值对象该用哪种？
- Pydantic `BaseModel` 是否仅在 JSON 序列化路径上使用（避免到处用）？
- 抽象层数是否合理？（≥3 层叠加通常过度抽象）

### 3. 类型系统契约

- 函数签名是否有完整类型注解（参数 + 返回值）？
- `from __future__ import annotations` + `TYPE_CHECKING` 解循环依赖是否到位？
- 需要 introspect 的地方（如 LC bridge）是否用 `typing.get_type_hints()` 解字符串注解？
- `Any` 是否被滥用？是否能用 `TypeVar` / `Generic` / 更精确类型替代？
- 类型注解是否同时是文档（参数说明、返回值语义）？

### 4. 异步与并发

- `async def` 函数里是否混入阻塞 IO（`open()` / `requests` / `time.sleep`）？
- `AsyncGenerator` 用法是否正确（异常传播、显式 `return`、资源清理）？
- 是否在 sync 上下文错误用了 async（导致 deadlock）？
- `await` 是否用在了非 awaitable 上？
- 并发原语（`asyncio.gather` / `Lock`）使用是否必要且正确？

### 5. 错误处理 Pattern

- 异常类型是否分层（领域异常 vs 系统异常）？
- 是否到处吞异常（`except Exception: pass` / `except: pass`）？
- 错误信息是否带足够上下文（路径 / 参数 / 操作名）？
- 自定义异常的基类是否统一（领域层统一继承某个 `WriterError`）？
- 异常是否在边界层（CLI / API）才转译成用户消息？

### 6. DI 与可测性

- 外部依赖是否走 Protocol 注入（而不是模块级全局 `PROJECT_ROOT = Path.cwd()`）？
- `production_deps()` 工厂是否存在、是否单一入口？
- Protocol 是否 `@runtime_checkable`（测试 mock 用 `isinstance`）？
- 是否能从测试覆写单个 DI 字段（不必重写整个 factory）？
- 协作对象的生命周期是否合理（singleton vs per-request）？

### 7. 模块边界与 `__all__`

- 包的 `__init__.py` 是否只 re-export 公共 API，不放逻辑？
- `__all__` 是否显式声明？re-export 是否清晰？
- 私有模块（`_` 前缀）是否真不跨包使用？
- 公共 API 是否有 docstring？
- 模块文件是否过长（>500 行通常需要拆分）？

### 8. Pythonic 风格（PEP 8 / idioms）

- 列表 / 字典 / 集合推导是否优于 `for + append`？
- 上下文管理器（`with`）是否代替 `try/finally`？
- `dataclass` / `NamedTuple` 是否代替裸 `tuple`？
- `pathlib.Path` 是否代替 `os.path`？
- f-string 是否统一（避免 `str.format` / `%`）？
- 命名：`snake_case` 函数 / 变量、`PascalCase` 类、`UPPER_CASE` 常量
- 类型注解中是否避免 `Optional[X]` 写成 `X | None`（≥3.10 推荐 union syntax）？

### 9. 文档与契约一致性

- Docstring 风格是否统一（Google / NumPy / Sphinx 三选一）？
- Docstring 是否说"为什么"而不是只重复签名？
- 重要模块是否有 module-level docstring？
- 类型 hint 是否替代了部分 docstring（参数说明）？
- 公共 API 的异常是否在 docstring 里说明（`Raises:` 段）？

---

## 输出格式（Phase 5 报告模板）

```markdown
# Code Review Report

**Scope**: <范围描述，如 `src/writer/engine/ (3 files, 412 LOC)`>
**Date**: <YYYY-MM-DD>
**Overall**: ✅ 健康（无 Blocker）/ ⚠️ 需关注（Majors: N）/ ❌ 必须修复（Blockers: N）

## Summary Scorecard

| 维度                | 评级 | Findings        |
| ------------------- | ---- | --------------- |
| 1. 架构分层         | ✅    | 0               |
| 2. 抽象一致性       | ⚠️    | 1 Major         |
| 3. 类型契约         | ✅    | 0               |
| 4. 异步与并发       | ✅    | 0               |
| 5. 错误处理         | ⚠️    | 2 Minor         |
| 6. DI 与可测性      | ✅    | 0               |
| 7. 模块边界         | ✅    | 0               |
| 8. Pythonic 风格    | 🟡    | 3 Nit           |
| 9. 文档契约         | ✅    | 0               |

## Inventory（Phase 2 基线）

- **包结构**：8 个子包，CLI → session → engine → routing/roles/tools/workflow 拓扑
- **Protocol 用法**：6 个 Protocol（IntentRouter / Tool / Role / ToolRuntime / WorkflowStarter / EngineDeps 字段），均 `@runtime_checkable`
- **异常体系**：自定义 3 个（`WriterError` / `ToolDeniedError` / `EngineAbortError`）+ 若干内置异常
- **DI 入口**：`writer.engine.deps.production_deps()`

## Findings（按 severity 排序）

### 🔴 Blocker（N 个）

（无）

### 🟠 Major（N 个）

- **M1** — `src/writer/tools/builtin/foo.py:23`
  - **维度**：错误处理一致性
  - **问题**：用 `ValueError`，但同类 Tool `safe_read_file` 用 `ToolDeniedError`
  - **建议**：统一为 `ToolDeniedError`，并在 protocol 层做断言

### 🟡 Minor（N 个）

- **m1** — `src/writer/engine/loop.py:45`
  - **维度**：Pythonic 风格
  - **问题**：用 `for ... in dict.keys()` 而不是直接迭代 dict
  - **建议**：改为 `for key in config:`

### ⚪ Nit（N 个）

- **n1** — `src/writer/cli/main.py:12`
  - **维度**：Pythonic 风格
  - **问题**：`"value: %s" % var` 用 `%` 格式化
  - **建议**：改为 f-string `f"value: {var}"`

## Design Consistency Notes

- **优点**：Protocol-based DI 全栈一致（router / tool / deps 字段）
- **关注点**：`session/` 包刚引入，跨 turn 状态边界需要后续 docs 同步
- **缺失**：`writer/skills/` 仍为占位，缺落地

## Recommended Actions（按优先级）

1. 修复 M1：统一 Tool 越界异常类型
2. 优化 m1 / n1：迭代 dict + f-string 替换
3. （可选）补 `session/` 包的架构图到 `docs/`
```

**输出规则**：

- Blocker / Major 必带 `file:line` + 可执行建议
- Minor / Nit 可合并为「风格建议」列表
- Report 末尾用「## Apply?」提示用户：「如需自动应用 Minor / Nit finding，请明确说 `apply` / `修一下`；否则本次 review 结束。」

---

## Apply 阶段硬规则（Phase 6）

| 项             | 规则                                                                 |
| -------------- | -------------------------------------------------------------------- |
| 触发           | 用户**明确**说 `apply` / `修一下` / `改掉 Nit` / `apply Minor`；默认状态 = 不动 |
| 自动范围       | **仅 Minor / Nit**；Blocker / Major 永远不动                          |
| 改动前确认     | 每个 finding 用 AskUserQuestion 单次确认（避免一次改太多）             |
| 改动后         | 必须用 `git diff` 把改动展示给用户复核                                |
| Commit         | **绝不** commit / push——交由 `git-commit` skill 处理                |
| 副作用         | 绝不跑 `pytest` / `mypy` / `ruff`（避免副作用链路）                  |
| 范围限定       | 只动报告里列出的 finding；不"顺手优化"额外代码（防 simplify 越界）    |

**AskUserQuestion 模板**（每个 finding 一次）：

- **Question**：「Apply finding **M1**（修改 `src/writer/tools/builtin/foo.py:23`）？」
- **Header**：「Apply finding」
- **Options**：
  1. ✅ 应用此修改 —— Edit 文件
  2. ⏭️ 跳过此 finding —— 不改
  3. 🛑 停止 apply —— 整个 apply 阶段中止

---

## 不做的事（Out of Scope）

明确写进 SKILL.md，避免越权：

- ❌ **不自动 commit / push**——commit 由 `git-commit` skill 负责
- ❌ **不跑测试 / lint / 类型检查**——review 只读代码，不执行副作用命令
- ❌ **不读 git log / blame**——聚焦当前代码状态
- ❌ **不替代类型检查器**——mypy 做的事不要重复；review 关注 mypy 看不出的架构问题
- ❌ **不"顺手优化"额外代码**——只动报告里列出的 finding，避免越界改文件
- ❌ **Blocker / Major 不自动修**——必须人工处理（Phase 6 的硬规则）
- ❌ **不修改报告范围外的文件**——即使发现新问题，也只在报告里 mention，不动
- ❌ **不写新文件**——本 skill 只生成报告（Phase 5 输出），不创建 `.py` / `.md`（除 SKILL.md 自身）

---

## 常见反模式（绝对不要这样用）

| 反模式                                  | 原因                                       | 正确用法                                       |
| --------------------------------------- | ------------------------------------------ | ---------------------------------------------- |
| 「帮我 review 一下然后自动改掉所有问题」 | 越权，Blocker / Major 不应自动改           | 让本 skill 输出报告，Major 人工处理             |
| 启动 review 后立刻跑 `pytest`           | 违反副作用规则                             | review 只读代码，测试由用户 / CI 负责           |
| 一次性 apply 所有 Minor / Nit            | 改动过大难复核                             | 每个 finding 单次确认 + 单次 `git diff` 复核   |
| 修改 `tests/` 但用户没要求              | 越权——默认排除 `tests/`                    | 仅当用户明确说 review 测试时才进入             |
| 读 git log / blame 来佐证                | 聚焦当前代码状态，不混历史                 | 直接读当前文件即可                             |

---

## 输出风格

- Phase 1 / 2 / 3 / 4 中间结果用简洁列表 / 表格，不写散文。
- 报告（Phase 5）严格按上述模板输出，不省略 scorecard / consistency notes。
- 一次只 review 一个 scope / 一组相关文件。处理完后等用户下一步指令，不要自作主张继续推。
- 中文 / 英文上下文都用对应语言写报告内容（不要硬塞英文）。
