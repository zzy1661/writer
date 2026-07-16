# design: production_deps 纯化

## Context

`production_deps` 是 `EngineDeps` 的唯一生产装配点（per
`code-review/SKILL.md` §"DI 入口 / 工厂单一入口"）。当前实现在工厂
内部调 `read_genre_from_agent(project_root / "AGENT.md")` 来选
Consultant 子类，造成三处问题：

1. **DI 边界漏**：工厂做"读盘"是 side effect，DI 规范要求工厂只做
   装配（参数 → 字段），不做 IO 探测
2. **冗余 IO**：M1（2026-07-07）已经在 `EngineSession.set_project_root`
   走 `refresh_project_genre()` + `_consultant_for_genre` 重建
   Consultant；工厂那次读的结果会立刻被运行期切换覆盖
3. **测试耦合**：18+ 测试站点依赖工厂自动读 AGENT.md，忘记 seed
   genre 也不会 fail——题材注入在测试代码里不可见

## Goals

- `production_deps` 变纯工厂，签名加 `genre: str = "other"`
- 删除 `_select_consultant`（含其内部 `read_genre_from_agent` 懒导入）
- AGENT.md 读取责任**显式**回到 `EngineSession.__post_init__` 与 CLI
  `init_project` 两个调用方
- 6 个题材相关测试改用显式 `genre=` kwarg，让"题材注入"在测试代码里
  一目了然

## Non-goals

- 不实现 `LlmIntentRouter`（独立 sprint）
- 不动 LangGraph 真实图
- 不动 `set_project_root` 的 M1 逻辑（继续是运行期 genre 切换的唯一入口）
- 不重命名 `EngineDeps` 字段
- 不引入 `Callable[[Path], str]` 注入（D 方案过设计，本轮已否决）
- 不动 OpenSpec `engine-session` capability（`__post_init__` 行为兼容，
  spec 现有场景仍通过）

## Decisions

### D1: `production_deps` 加 `genre: str = "other"` keyword-only

- 选 keyword-only（`*, genre=...`）而非 positional：与现有
  `project_root=` / `primary_router=` 风格一致；调用点必须用 kwarg
  传值，避免位置漂移
- default `"other"` 而不是 required：S0 哨兵（`test_engine_session.py`
  这类只关心 deps surface 的 stub）和没有 `AGENT.md` 的临时目录
  仍能构造 deps，不破现有 30+ 测试站点
- 不引入 enum：`"其他"` / `"other"` 仍是自由字符串，未来扩展题材不
  必改 production_deps 签名

### D2: 删除 `_select_consultant`，仅留 `_consultant_for_genre`

- `_consultant_for_genre` 已是纯查表（`_GENRE_CONSULTANT` 字典 + fallback
  到 `StoryConsultant`），M1 时为这个 helper 写过专项 docstring；
  把 `_select_consultant` 删掉后，文档里"Used by both ... and ..." 那段
  只需小修
- `from writer.project import read_genre_from_agent` 懒导入一并消失，
  `engine/deps.py` 不再 `import writer.project.*`（DI 边界恢复对称）

### D3: `EngineSession.__post_init__` 显式调 `refresh_project_genre`

- 调用条件：`if self.deps is None and self.project_root is not None`
  —— deps 注入测试（直接 `deps=stub`）跳过 refresh
- `if self.deps is None` 块外不调 refresh：避免对"deps 已被注入"的测试
  多余 IO（per `test_engine_session.py::PlainDeps` 这类手写 Protocol stub）
- refresh 后 `self.project_genre` 字段被赋值，`production_deps(genre=self.project_genre)`
  读到一致值

### D4: CLI `_maybe_apply_init_brief` 新增 `genre: str` keyword-only

- `init_project` 上游已有 `resolved_genre`（580 行），直接透传
- 不在 `_maybe_apply_init_brief` 内部重读 AGENT.md —— 那样等于把
  M2 漏出去的 IO 又补回来
- 新增 1 个测试点：`test_init_brief_uses_resolved_genre_for_consultant`
  （覆盖 `init_project` → `_maybe_apply_init_brief` → `production_deps`
  链路上的 genre 透传）

### D5: 6 个测试加显式 `genre=`

- `test_production_deps_picks_history_consultant_for_genre_history` → `genre="历史"`
- `test_production_deps_picks_romance_consultant_for_genre_romance` → `genre="言情"`
- `test_production_deps_picks_xuanhuan_consultant_for_genre_xuanhuan` → `genre="玄幻"`
- `test_production_deps_falls_back_to_story_consultant_without_genre` → `genre="other"`
- `test_production_deps_falls_back_when_project_root_is_none` → `genre="other"`
- `test_production_deps_falls_back_for_unknown_genre_label` → `genre="都市悬疑"`
- 其余 30+ 站点（S0 哨兵 / `create_workspace` 默认 / `deps=` 注入）
  保持不变

### D6: 不动 `set_project_root` / M1 路径

- M1 的 `refresh_project_genre()` + `_consultant_for_genre()` +
  `rebind_story_consultant()` 三件套是运行期 genre 切换的唯一入口，
  本次 M2 不动
- M2 与 M1 的边界：
  - **M1**：运行期 `set_project_root(new_root)` 触发 genre 切换
  - **M2**：构造期 `production_deps()` 不再做隐式 IO，genre 由调用方
    显式提供
- 两者不重叠：M1 仍在 `_consultant_for_genre` 这条纯查表路径上
  重建 Consultant；M2 仅清掉 `production_deps` 自己读 AGENT.md 的
  那条 side path

## Risks

1. **构造期多一次 AGENT.md IO**：`EngineSession.__post_init__` 在
   `project_root is not None` 时多调一次 `refresh_project_genre()`。
   实际影响：仅在 REPL 启动后 `/init` 之前那段 S0 窗口会走
   `project_root is None` 分支跳过；正常 `/init` 完进入 REPL 时
   `__post_init__` 已跑过，构造期多读一次 AGENT.md 可忽略
2. **`_maybe_apply_init_brief` 漏传 genre**：让 brief 应用走兜底
   `StoryConsultant`。覆盖：type checker 强制 `genre: str`（无 default），
   编译期就能拦下
3. **新增 `engine-deps` capability 描述可能与 `engine-session` 重叠**：
   已确认 `engine-deps` 关注 DI 工厂层、`engine-session` 关注
   session-lifecycle；两个抽象轴正交

## Migration

- `production_deps` 新参数有 default，**不需要** 同步修改 30+ 现有调用点
- 仅 6 个 `test_engine_deps.py` 题材测试需要升级（test-only 改动）
- `EngineSession.__post_init__` 行为变化对所有生产代码路径透明：
  - 启动期：构造 session 时 refresh genre + 用对 consultant
  - 运行期：`set_project_root` 仍是 genre 切换入口，行为不变
- 不需要 deprecation 周期（旧 `_select_consultant` 在同一次提交里删掉，
  因为它不是 public API——只有 `_consultant_for_genre` 是；`_select_consultant`
  仅为 `_select_consultant` 服务，无外部依赖）
