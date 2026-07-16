# 10 · 项目 Workspace 脚手架（中文目录统一版）

> 对应代码：`src/writer/project/{workspace,state,genre,init_brief,ideas,chapter_summaries}.py`
> 设计备忘：[`备忘 02-正典文件与多源写入一致性`](../../技术难点与解决方案备忘/02-正典文件与多源写入一致性.md)
>
> **2026-07-14 修订**：本文原目录结构为英文（`outline/`、`manuscript/`、`characters/`、`world/`、`notes/`），与代码长期脱节。
> 截至 2026-07-14，项目脚手架已统一为中文目录（`大纲/`、`草稿/`、`正文/`、`人物/`、`世界观/`、`备忘/`），`创意/` 仍由 `with_ideas_dir=True` 开启。
> 文档下面以代码真源为准重写。

---

## 10.1 设计动机

**问题**：每个小说项目是一个独立目录，但目录布局必须**预先约定**——否则 `/大纲` 不知道往哪写文件，`/审核` 不知道去哪读大纲。

**三种做法对比**：

| 方案                          | 缺点                                                       |
| ----------------------------- | ---------------------------------------------------------- |
| 每次命令现建目录              | 用户没大纲前 `/大纲` 不知道写哪                            |
| 固定路径                      | 不灵活，无法应对多项目布局                                  |
| **脚手架建项目**（本项目）    | `writer new <书名>`(Typer 子命令)一次性建好所有目录与 stub 文件;REPL 启动时 `discover_project_root()` 自动绑定 |

**目录布局**（per `fea-genre-aware-init` + 2026-07-14 中文统一）：

```
<project_root>/
├── AGENT.md                          # 项目元数据 + 状态机字段
├── README.md
├── 大纲/                              # 写作前策划材料（一句话创意、分卷、大纲、境界表、感情线）
│   ├── 一句话创意.md
│   ├── 分卷规划.md
│   └── 大纲.md                       # /大纲 写入（SKILL.md directive 命中后）
├── 草稿/                              # /创作 产出（write_chapter 工作流的 persist_outputs 节点）
│   └── chapter-<chapter_id>.md       # 章节草稿（review 通过后由人工/后续流程定稿）
├── 正文/                              # 已定稿（保留目录，当前流程由人工迁移草稿 → 正文）
├── 人物/
│   └── 主要人物.md
├── 世界观/
│   └── 世界观设定.md
├── 备忘/
│   └── 待办.md
├── 创意/                              # /init <brief> 产出（with_ideas_dir=True 才建）
│   └── 核心创意.md
├── 史实/                              # 历史题材专属（apply_genre_scaffolding）
│   ├── 年表.md
│   ├── 人物.md
│   ├── 事件.md
│   └── 考证.md
├── 伏笔/                              # 玄幻题材专属
│   └── 伏笔表.md
├── 大纲/境界表.md                     # 玄幻题材专属
├── 人设/                              # 言情题材专属
│   ├── 男主.md
│   └── 女主.md
├── 大纲/感情线时间轴.md               # 言情题材专属
└── .writer/                          # writer 项目级元数据（`writer new` 路径）
    ├── config                        # env 风格 LLM 配置（优先级高于 .env）
    ├── skills/                       # 项目级 SKILL.md 覆盖
    │   └── <command>/{SKILL.md, references/*.md}
    ├── agents/                       # 项目级 Agent Markdown 覆盖
    │   └── {other, 历史, 言情, 玄幻}.md
    └── checkpoints.sqlite            # LangGraph checkpointer（write_chapter 用）
```

**多题材**（per `fea-genre-aware-init` + REPL 多选题材）：多题材项目（如 `["历史", "玄幻"]`）会同时叠加两套脚手架；additive 语义，旧题材目录不会被删除。

## 10.2 `create_workspace()` —— 核心脚手架

> 对应代码：`src/writer/project/workspace.py`

```python
@dataclass(frozen=True)
class NovelWorkspace:
    root: Path
    created_files: list[Path]


def create_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genre: str = "other",
    genres: list[str] | None = None,
    with_ideas_dir: bool = False,
    with_writer_meta: bool = False,
    seed_agents: bool = False,
) -> NovelWorkspace:
    project_name = _normalize_name(name)
    genre_list = normalize_genres(genres if genres is not None else [genre])
    canonical_genre = primary_genre(genre_list)
    root = base_dir / project_name

    if root.exists() and not force:
        raise FileExistsError(f"项目目录已存在: {root}。如要覆盖请重新执行...")

    # 基础目录布局（与题材无关）
    directories = [
        root / "草稿",
        root / "大纲",
        root / "人物",
        root / "世界观",
        root / "备忘",
        root / "正文",
    ]
    if with_ideas_dir:
        directories.append(root / "创意")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    # 基础文件
    files = {
        root / "AGENT.md": render_agent_file(
            project_name, ProjectState.INITIALIZED,
            genre=format_genre_line(genre_list) or canonical_genre,
        ),
        root / "README.md": f"# {project_name}\n\n长篇小说项目工作区。\n",
        root / "大纲" / "一句话创意.md": "# 一句话创意\n\n",
        root / "大纲" / "分卷规划.md": "# 分卷规划\n\n",
        root / "人物" / "主要人物.md": "# 主要人物\n\n",
        root / "世界观" / "世界观设定.md": "# 世界观设定\n\n",
        root / "备忘" / "待办.md": "# 待办\n\n",
    }

    created_files: list[Path] = []
    for path, content in files.items():
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files.append(path)

    if with_ideas_dir:
        ideas_stub = root / "创意" / "简介.md"
        if force or not ideas_stub.exists():
            ideas_stub.write_text("# 创意库\n\n存放故事创意、灵感与核心设定。\n", encoding="utf-8")
            created_files.append(ideas_stub)

    # 题材特定脚手架叠在基础布局之上。``apply_genre_scaffolding`` 遍历
    # ``genre_list`` 的每个题材，每个白名单题材（``历史 / 言情 / 玄幻``）
    # 都会创建对应脚手架；``other`` 与未知题材是 no-op。多题材项目
    # （例如 ``["历史", "玄幻"]``）会同时创建两套脚手架文件。
    created_files.extend(apply_genre_scaffolding(root, genre_list))

    if with_writer_meta:
        created_files.extend(
            _writer_meta_scaffolding(root, force=force, seed_agents=seed_agents)
        )

    return NovelWorkspace(root=root, created_files=created_files)
```

### 关键参数

| 参数               | 默认      | 含义                                                              |
| ------------------ | --------- | ----------------------------------------------------------------- |
| `force`            | `False`   | 目录存在时是否覆盖                                                |
| `genre`            | `"other"` | 单题材字符串（向后兼容 `test_create_workspace_*_genre_*` 测试）   |
| `genres`           | `None`    | 多题材列表（优先于 `genre`）                                       |
| `with_ideas_dir`   | `False`   | 是否建 `创意/` 目录                                                |
| `with_writer_meta` | `False`   | 是否建 `.writer/` 元数据（`skills/.gitkeep` + `config` + `agents/`） |
| `seed_agents`      | `False`   | 是否在 `.writer/agents/` 镜像 shipped agents（永不覆盖已有文件） |

## 10.3 `create_new_workspace()` —— `writer new` 路径

```python
def create_new_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genres: list[str] | None = None,
) -> NovelWorkspace:
    """`writer new <书名>` 专用路径：打开所有 meta 选项。"""
    return create_workspace(
        name,
        base_dir,
        force=force,
        genres=genres,
        with_ideas_dir=True,
        with_writer_meta=True,
        seed_agents=True,
    )
```

**差异**：

| 维度                  | `create_workspace`（低层 API）  | `create_new_workspace`（`writer new`） |
| --------------------- | ------------------------------- | --------------------------------------- |
| 创意目录              | 取决于 `with_ideas_dir`         | 总是 True                                |
| `.writer/` 元数据     | 取决于 `with_writer_meta`       | 总是 True                                |
| 镜像 shipped agents   | 取决于 `seed_agents`            | 总是 True                                |

**向后兼容**：`create_workspace` 不带任何 meta 选项时，行为与最初版本完全一致（其他回退，无题材目录）。

## 10.4 题材脚手架 `apply_genre_scaffolding()`

```python
def _genre_scaffolding(root: Path, canonical_genre: str) -> dict[Path, str] | None:
    """题材特定脚手架字典查找表（per-genre 应用）。"""
    scaffolds: dict[str, dict[Path, str]] = {
        "历史": {
            root / "史实" / "年表.md": "# 年表\n\n按年份记录关键历史事件。\n",
            root / "史实" / "人物.md": "# 历史人物\n\n记录涉及的关键历史人物。\n",
            root / "史实" / "事件.md": "# 重大事件\n\n记录重大历史事件及其时间顺序。\n",
            root / "史实" / "考证.md": "# 考证备忘\n\n史实资料的核实状态与争议说明。\n",
        },
        "玄幻": {
            root / "伏笔" / "伏笔表.md": "# 伏笔表\n\n记录伏笔编号、内容、计划回收章节。\n",
            root / "大纲" / "境界表.md": "# 境界表\n\n记录修炼等级体系与各境界节点。\n",
        },
        "言情": {
            root / "人设" / "男主.md": "# 男主人设\n\n",
            root / "人设" / "女主.md": "# 女主人设\n\n",
            root / "大纲" / "感情线时间轴.md": "# 感情线时间轴\n\n按关系阶段拆章。\n",
        },
    }
    return scaffolds.get(canonical_genre)


def apply_genre_scaffolding(root: Path, genres: list[str]) -> list[Path]:
    """公开 API：遍历 genres 每个题材，应用对应脚手架（additive，不覆盖）。"""
    created: list[Path] = []
    for canonical_genre in genres:
        mapping = _genre_scaffolding(root, canonical_genre)
        if not mapping:
            continue
        for path, content in mapping.items():
            if path.exists():
                # 已存在则保持原样（additive），不重写
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created
```

**关键设计**：
- 题材差异以**目录 + 文件**显式表达（`史实/` + 4 个 .md / `伏笔/` + 境界表 / `人设/` + 感情线时间轴）。
- **additive 语义**：已存在的文件保持原样，与 `chg-remove-state-machine-enforcement` 的「不删旧文件」一致——题材切换时旧题材的子目录与文件得到保留。
- LLM 工具循环用 `safe_glob` 探测题材特定目录（`史实/`、`伏笔/`、`人设/`）来识别题材。

## 10.5 `_writer_meta_scaffolding()` —— `.writer/` 元数据

```python
_WRITER_CONFIG_TEMPLATE = """\
# 项目级 LLM 配置（优先级高于 .env）
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=
WRITER_BASE_URL=https://api.openai.com/v1
WRITER_TEMPERATURE=0.7
"""


def _writer_meta_scaffolding(
    root: Path, *, force: bool = False, seed_agents: bool = False
) -> list[Path]:
    """在 .writer/ 下建 skills / agents / config。"""
    writer_root = root / ".writer"
    targets = {
        writer_root / "skills" / ".gitkeep": "",
        writer_root / "config": _WRITER_CONFIG_TEMPLATE,
    }
    created: list[Path] = []
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    # 确保 agents 目录存在，即使没镜像。
    (writer_root / "agents").mkdir(parents=True, exist_ok=True)

    created.extend(_seed_directives(writer_root, force=force))
    if seed_agents:
        created.extend(_seed_agents(writer_root, force=force))
    return created
```

**`.writer/` 的三个子区**：

- `.writer/config` —— 项目级 env 风格 LLM 配置（优先级高于 `.env`）
- `.writer/skills/<command>/SKILL.md` + `references/*.md` —— 项目级 skill 覆盖（`last-write-wins`，per `chg-project-skills` + `chg-markdown-skills`）
- `.writer/agents/<name>.md` —— 项目级 agent 覆盖（per `fea-agent-mirror`；镜像永不覆盖已有文件，让用户定制得以保留）

镜像 shipped 是为了让用户能「fork 然后改」。

## 10.6 题材白名单与规范化

> 对应代码：`src/writer/project/genre.py`

```python
_GENRE_ALIASES: dict[str, str] = {
    "历史": "历史", "history": "历史", "historical": "历史",
    "言情": "言情", "romance": "言情",
    "玄幻": "玄幻", "xuanhuan": "玄幻", "fantasy": "玄幻",
    "other": "other", "其他": "other", "其它": "other",
}


def _normalize_genre(genre: str) -> str:
    """返回输入的规范题材 key。不在别名表中的值返回 ``"other"``。"""
    key = (genre or "").strip().lower()
    return _GENRE_ALIASES.get(key, "other")


def normalize_genres(genres: list[str]) -> list[str]:
    """规范化所有 genre 字符串；不在白名单的视为 other。"""
    normalized = []
    for g in genres:
        key = (g or "").strip().lower()
        canonical = _GENRE_ALIASES.get(key, "other")
        normalized.append(canonical)
    # 去重保序
    seen: set[str] = set()
    result: list[str] = []
    for g in normalized:
        if g not in seen:
            seen.add(g)
            result.append(g)
    return result


def primary_genre(genres: list[str]) -> str:
    """主题材（列表第一项；空列表返回 other）。"""
    return genres[0] if genres else "other"


def format_genre_line(genres: list[str]) -> str:
    """AGENT.md 题材行的格式：「题材: 历史, 言情」。"""
    return ", ".join(genres)
```

**关键约束**：**任何不在白名单的值视为 `other`**（包括用户自定义「科幻」「悬疑」等）。`AGENT.md` 写 `题材: other, 科幻` 即可。

## 10.7 `AGENT.md` —— 项目元数据与状态字段

> 对应代码：`src/writer/project/state.py::render_agent_file`

```python
CURRENT_STATE_SECTION_HEADER = "## 当前状态"


def render_agent_file(name: str, state: ProjectState, *, genre: str = "other") -> str:
    return f"""\
# {name}

题材: {genre}

## 当前状态
{state.value}

## 基本要求
- 题材: {genre}
- 字数目标: 200000
- 创作阶段: {state.value}

## 当前卷
(未开始)

## 当前章节
(未开始)

## 当前进度
(未开始)
"""


def detect_state(project_root: Path | None) -> ProjectState:
    """从磁盘推导状态（不主动写）。"""
    if project_root is None or not (project_root / "AGENT.md").exists():
        return ProjectState.UNINITIALIZED
    if _has_drafts(project_root):
        return ProjectState.DRAFTING
    if (project_root / "大纲" / "目录.md").exists():
        return ProjectState.FRAMING
    if (project_root / "大纲" / "大纲.md").exists():
        return ProjectState.OUTLINING
    return ProjectState.INITIALIZED


def read_genre_from_agent(agent_md_path: Path) -> str:
    """从 AGENT.md 的 ``题材:`` 行读取主题材（逗号分隔的第一项）。"""
    if not agent_md_path.exists():
        return "other"
    text = agent_md_path.read_text(encoding="utf-8")
    match = re.search(r"^题材:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return "other"
    raw = match.group(1).strip()
    primary = raw.split(",")[0].strip()
    return primary or "other"
```

### `AGENT.md` 3-stage guard

`safe_write_file` 写入 `AGENT.md` 时强制三道关卡：

1. **必须 `mode="overwrite"`** —— 避免 LLM 用 `append` 拼接错乱
2. **内容必须含 `## 当前状态`** —— 防止 LLM 把整个 AGENT.md 改空
3. **旧题材行自动 merge** —— `_merge_genre_line` 从旧文件抽出 `题材:` 行，合并到新内容，避免被覆盖

```python
def _merge_genre_line(old_content: str, new_content: str) -> str:
    """从旧 AGENT.md 抽出 题材: 行，合并到新内容。"""
    old_match = re.search(r"^(题材:.+)$", old_content, re.MULTILINE)
    new_match = re.search(r"^(题材:.+)$", new_content, re.MULTILINE)
    if old_match and not new_match:
        return old_match.group(1) + "\n" + new_content
    return new_content
```

### 字段语义

| 字段                | 谁读                                          | 谁写                                                      |
| ------------------- | --------------------------------------------- | --------------------------------------------------------- |
| `题材:`             | `Engine.refresh_project_genre()`(会话层) | `create_workspace` / `safe_write_file` merge              |
| `架构方法:`         | `/大纲` SKILL.md body(per `8782c36`)| `create_workspace` 初始(雪花法默认);`update_agent_architecture_method_line` 局部更新 |
| `预计总字数 / 总章数 / 分卷` | `/目录` SKILL.md body(per `34b1c95`)| `create_workspace` 初始(None 时跳过);`update_agent_total_*_line` / `update_agent_volumes_line` 局部更新 |
| `## 当前状态`       | `detect_state()`                              | `safe_write_file` 强制要求存在                             |
| `基本要求`          | LLM 读                                        | `create_workspace` 初始                                    |
| `当前卷/章节/进度`  | LLM 读；`/状态` 显示                          | 当前不主动写；未来由 `/创作` 等命令写入                    |

## 10.8 状态机已退化为展示层

> **2026-07-12 `chg-remove-state-machine-enforcement` 落地**：删除 `validate_command_available()`、`SkillDirective.requires_states`、`DirectiveRegistry.state_matrix()`、shipped SKILL.md 的 `requires_states:` 行。
>
> 命令拦截矩阵已全删，SKILL.md body 由 LLM 自主判断「已存在 vs 新建 / 追加 vs 覆盖」。命令在任意项目状态可调用。

**保留的展示层符号**：`ProjectState` enum / `STATE_DESCRIPTIONS` / `detect_state` / `inspect_project` / `ProjectSnapshot` / `find_outline_path` / `discover_project_root` / `count_chapters` / `safe_cwd` / `render_agent_file` / `refresh_agent_file` / `append_agent_requirements` / `read_genre_from_agent` / `CURRENT_STATE_SECTION_HEADER`。

**派生而非写入**：`detect_state` 从磁盘推导（`AGENT.md` 存在 → `草稿/` 是否有文件 → `大纲/目录.md` → `大纲/大纲.md`），避免状态与文件不一致。

### 命令副作用一览（无状态门禁）

| 命令              | 副作用文件                       | 状态变化           |
| ----------------- | -------------------------------- | ------------------ |
| `writer new <name>`(Typer 子命令)| 建项目目录 + 写 `AGENT.md` | S0 → S1            |
| `/init <故事梗概>`(REPL)  | 写 `创意/核心创意.md` + 题材行   | 保持 S1            |
| `/大纲`           | 写 `大纲/大纲.md`                | 保持 S1 / → S2     |
| `/目录`           | 写 `大纲/章节目录.md`           | 保持 S2 / → S3     |
| `/创作`           | 写 `草稿/chapter-<id>.md` + 更新 `chapter_summaries.json` | 保持 S3 / → S4     |
| `/审核`           | （PR3 待实装）                    | —                  |

> per 2026-07-14:TOC 文件名从 `大纲/目录.md` 改为 `大纲/章节目录.md`(与 SKILL.md body 同步);`/init --name X --dir Y` flag 形式已删除,REPL `/init` 后只跟故事核心创意。

## 10.9 `chapter_summaries.py` —— 章节摘要（per `chg-remove-rag`）

RAG 删除后，章节摘要是 LLM 长程上下文的唯一来源。

```python
def load_chapter_summaries(project_root: Path) -> list[ChapterSummary]:
    """读 <project_root>/chapter_summaries.json（项目根，非草稿/ 下）。"""
    path = project_root / "chapter_summaries.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ChapterSummary(**entry) for entry in data]


def append_summary(project_root: Path, chapter_id: str, summary: str, *, atomic: bool = True) -> Path:
    """原子追加单条章节摘要；write_chapter 的 persist_outputs 节点会调用。"""
    # ...
```

**注意**：当前实装的 `chapter_summaries.json` 在**项目根**（per `write_chapter.py` 的 `summaries_path` 由 `append_summary` 决定），并非旧文档所说的 `草稿/` 下；旧描述已废弃。

**`prep_context`**（per `writer/prompts/context.py`，替代旧的 `_build_canon_block`）：从 `草稿/`、`大纲/`、`chapter_summaries.json`、`史实/` 等文件按 4 层拼装正典上下文，`max_tokens=8000` 截断。

## 10.10 `init_brief.py` —— `/init <brief>` 入口

> 对应代码：`src/writer/project/init_brief.py`

`/init <brief>` 的入口是 `apply_init_brief()`，它内部调 `writer.agents.process_init_brief`：

```python
def apply_init_brief(
    project_root: Path,
    brief: str,
    *,
    settings: Settings,
    llm: Any | None = None,
) -> InitBriefResult:
    """/init <brief> 入口。

    1. 判断是否在 S1（已 init 项目但还没 brief）
    2. 用 LLM 展开 brief 为完整创意访谈（无 API key 时直接用 brief）
    3. 写入 创意/核心创意.md
    4. 更新 AGENT.md 的基本要求
    """
    from writer.agents import process_init_brief
    return process_init_brief(project_root, brief, settings=settings, llm=llm)
```

### REPL 抢先消费（per 2026-07-13 落地,2026-07-14 收紧）

> **2026-07-14 收紧**:REPL `/init` 后只跟故事核心创意;`/init --name X --dir Y` flag 形式已删除(创建项目请用 `writer new <书名>` Typer 子命令)。

REPL `handle_repl_input` 在 brief 形式下**抢先**消费(per `dfe58d0`,2026-07-15 进入多轮 explore 模式):

```python
def _try_handle_repl_init_brief(text: str, session: Engine) -> bool:
    """返回 True 表示已消费（不交给 engine）。"""
    if not (text.startswith("/init ") and looks_like_creative_brief(extract_init_brief_text(text))):
        return False
    project_root = session.project_root or discover_project_root()
    if project_root is None:
        console.print("[red]请先执行 writer new <书名> 创建项目,再 cd 进入项目目录。[/red]")
        return True
    selected = prompt_genres(console, default=None)  # TTY 交互 / 非 TTY 兜底 ["其他"]
    outcome = apply_genre_and_brief(
        session.project_root, genres=genres, brief=extract_init_brief_text(text),
        settings=session.settings,
    )
    console.print(f"已补脚手架 + 写 brief + 更新题材行：{outcome}")
    return True
```

`Runner._maybe_run_init_brief_or_block` 不动（继续服务 `runner.run` 直接驱动 / SDK / e2e pipe；2026-07-16 前是 `Engine._maybe_run_init_brief_or_block`），docstring 注明「REPL 抢先消费」。

### 关键设计

- **`looks_like_creative_brief` 闸门**(per 2026-07-14 单闸门化):识别标点(`。！？；,.!?;`)或长度 > 30 才视为 brief。短 token(如 `/init 双生`)不视为 brief,**落给 engine 路径**(engine 内部 `_maybe_run_init_brief_or_block` 在 S0 时引导 "请先 `writer new <书名>`")。该判断早期(2026-07-12 之前)需要同时区分"建项目"/"写 brief"两种形态;2026-07-14 删除 `/init --flag` 创建项目路径后,只服务 brief 一种形态,双闸门简化为单闸门。

## 10.11 完整数据流：`writer new 长安程序员 -g 历史`

```
CLI: writer new 长安程序员 -g 历史
   ↓
Typer command new(name="长安程序员", genre=["历史"]):
    workspace = create_new_workspace("长安程序员", Path("."), genres=["历史"])
        ├─ create_workspace(name, base_dir, genres=["历史"],
        │                    with_ideas_dir=True, with_writer_meta=True, seed_agents=True)
        ├─ 建基础目录:草稿/ 大纲/ 人物/ 世界观/ 备忘/ 正文/ 创意/
        ├─ 写基础文件:AGENT.md(含 题材: 历史, 当前状态: S1) + README.md + 6 个 stub
        ├─ apply_genre_scaffolding(root, ["历史"]):
        │     └─ 写 史实/年表.md 史实/人物.md 史实/事件.md 史实/考证.md
        ├─ _writer_meta_scaffolding(root, force=False, seed_agents=True):
        │     ├─ 写 .writer/config(env 模板)
        │     ├─ _seed_agents(): 镜像 4 份 _shipped/*.md → .writer/agents/
        │     │   （已有文件不覆盖，per fea-agent-mirror）
        │     └─ _seed_directives(): 镜像 _shipped/{大纲,目录}/ → .writer/skills/<command>/
        └─ return NovelWorkspace(root=./长安程序员, created_files=[...])
   ↓
console.print(f"已创建: {workspace.root}")
   ↓
用户 cd 长安程序员 && uv run writer
   ↓
REPL 启动:
    Engine(project_root=./长安程序员)
        ├─ discover_project_root() → ./长安程序员(有 AGENT.md)
        ├─ production_deps(project_root=./长安程序员)
        │     ├─ built_directive_registry(project_root=./长安程序员)
        │     │     ├─ discover_shipped_directives() → [大纲, 目录, 人物]
        │     │     └─ discover_project_directives() → [] (空,项目级未改)
        │     └─ built_agent_registry(project_root=./长安程序员)
        │           ├─ discover_shipped_agents() → [other, 历史, 言情, 玄幻]
        │           └─ discover_project_agents() → [] (空)
        └─ session.project_state = "S1"
        └─ session.project_genre = "other"(writer new 默认,后续 /init 多选调整)
```

## 10.12 进一步阅读

- [03-会话与状态机](03-会话与状态机.md) —— 状态机展示层机制
- [08-题材与Agent层](08-题材与Agent层.md) —— 题材差异在 agent Markdown 中的表达
- [12-工作流与审核](12-工作流与审核.md) —— write_chapter LangGraph 实装
- [备忘 02-正典文件与多源写入一致性](../../技术难点与解决方案备忘/02-正典文件与多源写入一致性.md)
- [备忘 16-Agent架构模式与本项目选型](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)