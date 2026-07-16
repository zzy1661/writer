# tasks: production_deps 纯化

## 1.1 `src/writer/engine/deps.py` 纯工厂化

- [x] 删除 `_select_consultant` 函数（含其内部 `from writer.project
      import read_genre_from_agent` 懒导入）
- [x] `production_deps` 新增 `genre: str = "other"` keyword-only 参数
- [x] `production_deps` 内部 `_select_consultant(resolved, project_root)`
      改为 `_consultant_for_genre(resolved, genre)`
- [x] 更新 `production_deps` docstring：明示"pure factory" +
      `genre` 参数说明 + 调用方责任
- [x] 更新 `_consultant_for_genre` docstring：移除"_select_consultant"
      引用，简化"Used by both ..." 段

## 1.2 `src/writer/session/engine_session.py` `__post_init__` 显式 refresh

- [x] `__post_init__` 在 `if self.deps is None` 块内增加
      `if self.project_root is not None: self.refresh_project_genre()`
- [x] `production_deps(project_root=...)` 改
      `production_deps(project_root=..., genre=self.project_genre)`

## 1.3 `src/writer/cli/main.py` 透传 genre

- [x] `_maybe_apply_init_brief` 新增 `genre: str` keyword-only 参数
- [x] `_maybe_apply_init_brief` 内 `production_deps(project_root=...)`
      改 `production_deps(project_root=..., genre=genre)`
- [x] `init_project` 把 `resolved_genre` 传给 `_maybe_apply_init_brief`

## 1.4 `tests/test_engine_deps.py` 6 个题材测试加 `genre=`

- [x] `test_production_deps_picks_history_consultant_for_genre_history` → `genre="历史"`
- [x] `test_production_deps_picks_romance_consultant_for_genre_romance` → `genre="言情"`
- [x] `test_production_deps_picks_xuanhuan_consultant_for_genre_xuanhuan` → `genre="玄幻"`
- [x] `test_production_deps_falls_back_to_story_consultant_without_genre` → `genre="other"`
- [x] `test_production_deps_falls_back_when_project_root_is_none` → `genre="other"`
- [x] `test_production_deps_falls_back_for_unknown_genre_label` → `genre="都市悬疑"`

## 1.5 文档同步

- [x] `src/writer/project/state.py::render_agent_file` docstring：
      "production_deps" 那半句替换为 "EngineSession.refresh_project_genre / CLI init_project"
- [x] `src/writer/roles/__init__.py` 模块 docstring：
      "selected by production_deps based on AGENT.md" → "selected by the
      caller of production_deps (typically EngineSession.__post_init__)"
- [x] `docs/技术架构总览.md` §八 题材分支：重写 370-377 段
      （派生 / 脚手架 / 当前缺口 → 派生 / 脚手架 / 运行期切换）

## 1.6 OpenSpec artifacts

- [x] `openspec/changes/2026-07-08-refactor-engine-deps-purity/proposal.md`
- [x] `openspec/changes/2026-07-08-refactor-engine-deps-purity/design.md`
- [x] `openspec/changes/2026-07-08-refactor-engine-deps-purity/tasks.md`
- [x] `openspec/changes/2026-07-08-refactor-engine-deps-purity/specs/engine-deps/spec.md`

## 1.7 MEMORY.md 同步

- [ ] "Genre-aware init 决策" 段补 2026-07-08 M2 落地注
