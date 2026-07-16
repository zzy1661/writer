# refactor: production_deps 纯化（去掉隐式 AGENT.md IO）

## Why

`production_deps(project_root=...)` 在 `src/writer/engine/deps.py` 调
`_select_consultant`，而后者通过 `read_genre_from_agent(project_root / "AGENT.md")`
**在工厂里读磁盘**。这违反项目自己的 DI 规范（`code-review/SKILL.md` §"DI
入口 / 工厂单一入口"）：

- **隐性耦合**：18+ 测试站点静默依赖工厂自动挑 Consultant，忘了
  `_seed_genre()` 也不会报错——评审者无法一眼看出"这个测试是不是题材相关"
- **冗余 IO**：M1 修复（2026-07-07）已经在 `set_project_root` 走
  `refresh_project_genre()` + `rebind_story_consultant` 重建 Consultant；
  工厂里那次 AGENT.md 读的结果会被运行时切换覆盖，等于"读两次磁盘、丢弃一次"
- **顺序坑**：`EngineSession.__post_init__` 在构造期读 AGENT.md，构造
  顺序和写 AGENT.md 顺序耦合，难以在依赖注入测试里跳过 IO
- **作者标记**：`engine/deps.py:87-90` 自己的 docstring 已标为 M2 / sprint 候选

**目标**：让 `production_deps` 变回纯工厂，AGENT.md 读取责任推回给真正
知道 genre 的两个调用方（`EngineSession.__post_init__` 与 CLI
`init_project` / `_maybe_apply_init_brief`）。

## What Changes

- `src/writer/engine/deps.py::production_deps` 新增 `genre: str = "other"`
  keyword-only 参数；`production_deps` 内部不再读 AGENT.md，删除
  `_select_consultant` 函数（仅保留纯查表的 `_consultant_for_genre`）
- `src/writer/session/engine_session.py::EngineSession.__post_init__` 在
  `self.deps is None` 块内调用 `refresh_project_genre()`（仅当
  `project_root is not None`），把结果作为 `genre` 传给 `production_deps`
- `src/writer/cli/main.py::_maybe_apply_init_brief` 新增 `genre: str`
  keyword-only 参数；`init_project` 把已经算好的 `resolved_genre` 透传进去；
  `_maybe_apply_init_brief` 内部 `production_deps(project_root=...)` 改
  为 `production_deps(project_root=..., genre=genre)`
- 6 个 `test_engine_deps.py` 题材相关测试加显式 `genre=` kwarg，让
  "题材注入"在测试代码里一目了然
- 文档同步：`project/state.py::render_agent_file` docstring、
  `roles/__init__.py` 模块 docstring、`docs/技术架构总览.md` §八
  题材分支一段重写

## Capabilities

### 新建 capability

- `engine-deps` —— `production_deps` 纯工厂契约（不读 AGENT.md；
  genre 由调用方显式提供）

### 不动 capability

- `engine-session` —— `__post_init__` 行为兼容（多调一次
  `refresh_project_genre()` 是 implementation detail；spec 现有
  场景仍通过）
- `genre-init` —— `EngineDeps.story_consultant` 题材槽位契约不变

## Impact

- **直接修改文件**：5 个（`engine/deps.py`、`session/engine_session.py`、
  `cli/main.py`、`tests/test_engine_deps.py`、`docs/技术架构总览.md`）
- **文档同步**：3 个 docstring 调整（`project/state.py`、`roles/__init__.py`）
- **OpenSpec artifacts**：4 个（`proposal.md` / `design.md` / `tasks.md` /
  `specs/engine-deps/spec.md`）
- **非破坏性**：`production_deps` 新参数有 default `"other"`，现有
  18+ 调用点不传 `genre` 时行为与原 `_select_consultant(..., None)`
  一致；6 个题材相关测试通过显式 `genre=` 升级到新契约
- **风险**：
  1. `EngineSession.__post_init__` 走 `refresh_project_genre()` 意味着
     `project_root is not None` 时构造期多一次 AGENT.md 读；M1 路径
     （运行期 `set_project_root`）不变
  2. CLI `_maybe_apply_init_brief` 必须从 `init_project` 接收
     `resolved_genre`，漏传会让 brief 应用走兜底 `StoryConsultant`——
     由 type checker + 1 个新增测试点覆盖
