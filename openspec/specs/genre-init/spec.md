# Capability: genre-aware-init

## Purpose

让 `/init` 命令接收并持久化小说题材，按题材派生具体 `StoryConsultant` 子类，并生成题材特定的项目脚手架子目录。历史题材的 `史实/` 目录建起来但不被引擎消费（备忘 09 的 history_check 留待未来实现）。

术语约定：
- **genre**（题材）：`历史 | 言情 | 玄幻 | other`
- **兜底**：`other` 路径走固定四幕（与 `StoryConsultant` 当前实现一致）
## Requirements
### Requirement: `/init` 接受 `--genre` 选项

`/init <name> --dir <dir> [--force] [--genre 历史|言情|玄幻|other]` 子命令 MUST 接受 `--genre` 选项。缺失 `--genre` 时 MUST 通过 Typer 交互 prompt 提供 `历史 / 言情 / 玄幻 / 其他(自定义)` 四选一。

#### Scenario: 通过 --genre 显式提供历史题材
- **WHEN** 用户执行 `writer init 贞观长歌 --dir ./novels --genre 历史`
- **THEN** 流程 MUST 不进入交互 prompt
- **AND** 写入 `AGENT.md` 的题材字段值为 `历史`

#### Scenario: 缺省 --genre 触发交互 prompt
- **WHEN** 用户执行 `writer init 废土王朝 --dir ./novels`（无 `--genre`）
- **THEN** CLI MUST 渲染 Typer prompt 列出 `历史 / 言情 / 玄幻 / 其他`
- **AND** 用户选择 `其他` 后 MUST 提示输入自定义题材名（自由字符串）
- **AND** 自定义字符串视为 `other` 兜底

#### Scenario: --genre 取值不在白名单
- **WHEN** 用户执行 `writer init foo --genre 都市`（不在白名单）
- **THEN** CLI MUST 拒绝并打印可用值列表（参考 implementation hint 但不强制）

### Requirement: AGENT.md 持久化题材

`/init` 完成后 MUST 在 `AGENT.md` 写入 `题材: <genre>` 行，字段位置紧邻现有 `state` 行（若有），并作为项目题材的唯一持久事实来源。

#### Scenario: 历史题材持久化
- **WHEN** `/init` 选 `历史` 完成
- **THEN** `AGENT.md` MUST 包含行 `题材: 历史`
- **AND** `AGENT.md` 中 `state: S1` 行（若存在）保持不变

#### Scenario: 兜底题材持久化
- **WHEN** `/init` 选 `other` 或未识别题材完成
- **THEN** `AGENT.md` MUST 包含 `题材: other`

### Requirement: create_workspace 按题材生成不同子目录

`create_workspace(name, base_dir, *, force=False, genre="other")` MUST 按 `genre` 参数在现有六文件基础上追加题材特定文件：

| genre | 追加文件 |
|---|---|
| `历史` | `史实/年表.md`, `史实/人物.md`, `史实/事件.md`, `史实/考证.md` |
| `玄幻` | `伏笔/foreshadow.md`, `大纲/境界表.md` |
| `言情` | `人设/男主.md`, `人设/女主.md`, `大纲/感情线时间轴.md` |
| `other` | （不追加） |

追加的文件 MUST 出现在返回的 `NovelWorkspace.created_files` 列表中。`genre` 参数 MUST 是 keyword-only，默认 `"other"` 以保持向后兼容。

#### Scenario: 历史题材脚手架
- **WHEN** `create_workspace("长安", base, genre="历史")`
- **THEN** `史实/年表.md / 人物.md / 事件.md / 考证.md` MUST 存在
- **AND** 现有六文件（`README.md / outline/premise.md ...`）MUST 保留

#### Scenario: 玄幻题材脚手架
- **WHEN** `create_workspace("破界", base, genre="玄幻")`
- **THEN** `伏笔/foreshadow.md` + `大纲/境界表.md` MUST 存在
- **AND** 不存在 `史实/` 或 `人设/` 目录

#### Scenario: 言情题材脚手架
- **WHEN** `create_workspace("双生", base, genre="言情")`
- **THEN** `人设/男主.md / 女主.md / 大纲/感情线时间轴.md` MUST 存在
- **AND** 不存在 `史实/` 或 `伏笔/` 目录

#### Scenario: 兜底题材脚手架
- **WHEN** `create_workspace("杂项", base)`（默认 `genre="other"`）
- **THEN** MUST 仅含现有六文件
- **AND** MUST 不含 `史实/`、`伏笔/`、`人设/` 目录

#### Scenario: 题材参数向后兼容
- **WHEN** 旧调用 `create_workspace("x", base)`（无 `genre` 关键字参数）
- **THEN** MUST 与未传 `genre` 行为一致（默认 `other`）

### Requirement: 三题材独立 StoryConsultant 子类

`writer.roles` 包 MUST 暴露 `HistoryConsultant` / `XuanhuanConsultant` / `RomanceConsultant`，每个实现 `StoryConsultant` 现有契约（含 `draft_outline(idea) -> OutlineResult`）。每个子类的 `chapters` 字段内容 MUST 反映该题材的写作方法论。

#### Scenario: HistoryConsultant.draft_outline 输出史实导向章纲
- **WHEN** `HistoryConsultant(s).draft_outline("贞观治世")`
- **THEN** `OutlineResult.chapters` MUST 含至少 4 条 `chapters`
- **AND** 每条 MUST 含可读作"史实锚点 + 虚构标注"语义的标签（实现可自由决定具体前缀，如 `史实:` / `虚构:`）
- **AND** MUST 不返回空列表

#### Scenario: XuanhuanConsultant.draft_outline 输出境界导向章纲
- **WHEN** `XuanhuanConsultant(s).draft_outline("废柴觉醒")`
- **THEN** `OutlineResult.chapters` MUST 含至少 4 条
- **AND** 每条 MUST 含可读作"境界节点"语义的标签（如 `境界:` / `境界1:`...）

#### Scenario: RomanceConsultant.draft_outline 输出情感节拍章纲
- **WHEN** `RomanceConsultant(s).draft_outline("仇人之子")`
- **THEN** `OutlineResult.chapters` MUST 含 8 ~ 12 条
- **AND** 每条 MUST 含可读作"情感节拍"语义的标签（如 `节拍:` / `GMC:`）

#### Scenario: StoryConsultant 兜底四幕
- **WHEN** `StoryConsultant(s).draft_outline("something")`（兜底类）
- **THEN** `OutlineResult.chapters` MUST 仍为现行 4 条幕结构（与原 MVP 行为一致）
- **AND** 该行为 MUST 通过既有 `tests/test_roles.py` 测试（不破坏既有基线）

### Requirement: REPL `/init` 走同一条 init 逻辑

REPL `/init` 命令 MUST 调用与 Typer `init` 子命令相同的后端（同一 `init_project(name, dir, genre)` 函数入口），保证 CLI 与 REPL 的初始化行为一致。

#### Scenario: REPL /init 选 言情 时生成言情脚手架
- **GIVEN** REPL 处于 S0 状态
- **WHEN** 用户输入 `/init --name 双生 --dir novels --genre 言情`
- **THEN** REPL MUST 走 `init_project()` 入口
- **AND** 工作区 MUST 含 `人设/` 子目录

### Requirement: Engine.project_genre 反映当前题材

`EngineSession` MUST 暴露 `project_genre: str = "other"` 字段。
- `set_project_root(path)` 调用时 MUST 从 `(path / "AGENT.md")` 重新加载（覆盖内存值）
- 缺失 `AGENT.md` 或无题材行时回落到 `"other"`

#### Scenario: set_project_root 读取 AGENT.md 题材
- **GIVEN** 项目根下 `AGENT.md` 含 `题材: 言情`
- **WHEN** 调用 `EngineSession().set_project_root(path)`
- **THEN** `session.project_genre == "言情"`

#### Scenario: AGENT.md 无题材行时回落到 other
- **GIVEN** 项目根下 `AGENT.md` 不含 `题材:` 行
- **WHEN** 调用 `EngineSession().set_project_root(path)`
- **THEN** `session.project_genre == "other"`

### Requirement: RunnerDeps.story_consultant 按题材派生

`production_deps(project_root=...)` MUST 在 `project_root` 含 `AGENT.md` 带题材行时，按题材构造具体 Consultant 子类并注入 `EngineDeps.story_consultant` 槽。

#### Scenario: 历史项目载入 HistoryConsultant
- **GIVEN** `project_root/AGENT.md` 含 `题材: 历史`
- **WHEN** `production_deps(project_root=...)`
- **THEN** `deps.story_consultant` MUST 为 `HistoryConsultant` 实例

#### Scenario: 无 AGENT.md 时回落到 StoryConsultant 兜底
- **WHEN** `project_root` 不存在或无 `AGENT.md`
- **THEN** `deps.story_consultant` MUST 为 `StoryConsultant` 实例

#### Scenario: 题材行为对 EngineContext 透明
- **WHEN** 引擎取 `deps.story_consultant.draft_outline(idea)` 时
- **THEN** 调用方 MUST 不知道也不需要知道具体类型（仍是 Protocol 槽）
- **AND** `OutlineResult` 形状 MUST 保持与历史一致（增加 / 移除字段禁止）

## 不做什么 / 留待未来

- **`history_check` 审核节点**（备忘 09）—— 本次不实现；`史实/` 目录可建，但不被引擎消费。
- **GenreLocator 自动识别** —— 总是显式提供题材，不做关键词分类。
- **运行时改题材流程** —— 项目跑到一半改题材不在本次范围。
- **LLM 化 Consultant / Prompt 模板系统** —— 三 Consultant 仍 deterministic。
- **`/目录 /写 /审核` 的题材分化** —— 三题材只影响 init + Outline；后续命令维持通用流程。