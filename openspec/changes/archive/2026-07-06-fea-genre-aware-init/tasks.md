# Tasks: fea-genre-aware-init

依赖顺序：1 → 2 → 3 → 4 → 5 → 6 → 7，每块约 30~90 分钟，可独立提交。

## 1. create_workspace 扩展 `genre` 参数

- [x] 1.1 改 `src/writer/project/workspace.py`：`create_workspace` 加 keyword-only `genre: str = "other"` 参数
- [x] 1.2 新增模块私有辅助函数 `_genre_scaffolding(root: Path, genre: str) -> list[Path]`：按白名单追加文件，返回追加文件路径列表
- [x] 1.3 `_genre_scaffolding` 内部对 `genre` 取 `strip().lower()` 但保留中文值 "历史/言情/玄幻" 与 "other" 等价键的归一化方式（实现时可定 —— 见 proposal.md "待用户拍板"）
- [x] 1.4 把 `_genre_scaffolding(root, genre)` 返回的文件**并入** `NovelWorkspace.created_files`（先现存六文件，再追加题材文件）

## 2. 三题材 StoryConsultant 子类

- [x] 2.1 新增 `src/writer/roles/history_consultant.py`：导出 `HistoryConsultant`，`draft_outline` 返回含史实锚点标签的 ≥4 条 chapters
- [x] 2.2 新增 `src/writer/roles/xuanhuan_consultant.py`：导出 `XuanhuanConsultant`，返回境界节点 ≥4 条 chapters
- [x] 2.3 新增 `src/writer/roles/romance_consultant.py`：导出 `RomanceConsultant`，返回 8~12 条情感节拍 chapters
- [x] 2.4 保留 `StoryConsultant` 为兜底类（不改文件，作为 `other` 路径）
- [x] 2.5 更新 `src/writer/roles/__init__.py` re-export 四个类

## 3. EngineSession 题材字段

- [x] 3.1 在 `src/writer/session/engine_session.py` 加 `project_genre: str = "other"` 字段
- [x] 3.2 `set_project_root()` 内从 `(root / "AGENT.md")` 读取题材行；缺失则保持 "other"
- [x] 3.3 新增私有辅助 `_read_genre_from_agent(agent_md: Path) -> str`：解析 `题材:` 行；不抛异常

## 4. AGENT.md 写入题材

- [x] 4.1 `create_workspace` 内追加 `AGENT.md`（或更新现有 AGENT.md）：写入 `题材: <genre>` 行
- [x] 4.2 若文件已有 `题材:` 行：按 `force` 决定是否覆盖（force=True → 覆盖；force=False → 保留）
- [x] 4.3 文件不存在时新建而非抛异常；空目录项目可先 init 后大纲

## 5. production_deps 按题材派生 Consultant

- [x] 5.1 改 `src/writer/engine/deps.py:production_deps(project_root=...)`：根据 `project_root / "AGENT.md"` 题材行选 Consultant 类
- [x] 5.2 题材解析白名单：`{"历史": HistoryConsultant, "言情": RomanceConsultant, "玄幻": XuanhuanConsultant, "other"/缺失 → StoryConsultant}`
- [x] 5.3 `project_root=None` 仍走 `StoryConsultant` 兜底

## 6. CLI / REPL init 入口

- [x] 6.1 在 `cli/main.py` 新增 `init(name, directory, force, genre)` Typer 子命令（**保留现有 `new` 子命令作为 `init` 的别名 / 引导**——避免一次性破坏 CLI 表面）
- [x] 6.2 `--genre` 选项缺失时使用 Typer `typer.Option(..., prompt=...)` 渲染交互 prompt；选项为 `["历史", "言情", "玄幻", "其他"]`
- [x] 6.3 "其他" 选项触发二级 prompt 接收自定义字符串；自定义值一律视为 `other`
- [x] 6.4 提取并复用 `init_project()` 公共入口（Typer 子命令 + REPL `/init` 都调用它）
- [x] 6.5 REPL `/init` 命令处理：在 `handle_repl_input` 内解析参数 → 调用 `init_project()` → 输出与 Typer 子命令等价
- [x] 6.6 （可选）`/init` 在 REPL 内复用 `set_pending_interrupt` 模式分步走（仅当类型不支持字符串时才需要）

## 7. 测试扩展

- [x] 7.1 `tests/test_workspace.py` 新增 ~6 个 genre-specific 创建测试（每个题材 + 总追加行为）
- [x] 7.2 （合并到 7.5 与 test_roles.py）`tests/test_genre_init.py` 因 init_project 与 Typer 子命令共享，被并入 `tests/test_cli.py`
- [x] 7.3 `tests/test_engine_session.py` 新增：AGENT.md 题材行读取 / 缺失回落
- [x] 7.4 `tests/test_engine_deps.py` 新增：`production_deps` 按 AGENT.md 题材注入对应 Consultant
- [x] 7.5 `tests/test_cli.py`：`init` 子命令 + REPL `/init` 各加 ≥1 e2e 测试
- [x] 7.6 `tests/test_roles.py` 新增：三题材 Consultant 各自输出前缀约定 + 共享 OutlineResult 形状

## 8. 文档与备忘同步

- [x] 8.1 `docs/技术架构总览.md`：补"题材"层（四层 / 五层讨论）
- [x] 8.2 备忘 16（Agent 架构模式）：补题材分支的实现位置
- [x] 8.3 备忘 09（历史史实）：明确标记"目录已建，history_check 留待 fea-genre-aware-init-history-check"

## 9. 验收

- [x] 9.1 `uv run pytest tests/ -q` 全过；**170 测试通过**（基线 121 + 新增 49）
- [x] 9.2 `uv run pytest --cov=writer --cov-report=term-missing` = **94%**（statements 翻倍到 1457；新增模块 ≥ 90%；workspace / roles / cli / engine_session / engine_deps / state 都是 100%）
- [x] 9.3 `uv run ruff check src tests` clean
- [x] 9.4 `uv run mypy src/writer` clean
- [x] 9.5 e2e: `writer init 双生 --dir /tmp/x --genre 言情` → 项目建立、`人设/男主.md` 存在；`--genre "都市悬疑"` → 兜底为 other；AGENT.md 含 `题材: 言情`
- [x] 9.6 提议 artifact：`openspec validate fea-genre-aware-init --strict` 通过

## 范围外显式标记

- ❌ `history_check` 工作流节点（备忘 09）
- ❌ GenreLocator 自动识别
- ❌ 运行时改题材流程
- ❌ LLM 化 Consultant
- ❌ `/目录 /写 /审核` 的题材分化
