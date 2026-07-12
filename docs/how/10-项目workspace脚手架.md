# 10 · 项目 Workspace 脚手架

> 对应代码:`src/writer/project/{workspace,state,genre,init_brief,ideas,chapter_summaries}.py`
> 设计备忘:[`备忘 02-正典文件与多源写入一致性`](../../技术难点与解决方案备忘/02-正典文件与多源写入一致性.md)

---

## 10.1 设计动机

**问题**:每个小说项目是一个独立目录,但目录布局必须**预先约定**——否则 `/大纲` 不知道往哪写文件,`/审核` 不知道去哪读大纲。

**三种做法对比**:

| 方案 | 缺点 |
| ---- | ---- |
| 每次命令现建目录 | 用户没大纲前 `/大纲` 不知道写哪 |
| 固定路径(`/outline/大纲.md`) | 不灵活,无法应对多项目布局 |
| **脚手架建项目**(本项目) | `/init <name>` 时一次性建好所有目录与 stub 文件 |

**目录布局**(per `fea-genre-aware-init`):

```
<project_root>/
├── AGENT.md                # 项目元数据 + 状态机字段
├── README.md
├── outline/
│   ├── premise.md          # 一句话创意
│   ├── volume-plan.md      # 分卷规划
│   └── 大纲.md             # /大纲 生成
├── characters/
│   └── main.md             # 主要人物
├── world/
│   └── setting.md          # 世界观
├── notes/
│   └── todo.md             # 待办
├── manuscript/             # /创作 产出
├── 创意/                    # /init <brief> 产出(可选)
│   └── 核心创意.md
└── .writer/                # writer 项目级元数据(`writer new` 路径)
    ├── config              # env 风格配置
    ├── skills/             # 项目级 SKILL.md 覆盖
    └── agents/             # 项目级 Agent Markdown 覆盖
```

## 10.2 `create_workspace()` — 核心脚手架

> 对应代码:`src/writer/project/workspace.py`

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
        raise FileExistsError(f"项目目录已存在: {root}...")

    # 基础目录布局(与题材无关)
    directories = [
        root / "manuscript",
        root / "outline",
        root / "characters",
        root / "world",
        root / "notes",
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
        root / "outline" / "premise.md": "# 一句话创意\n\n",
        root / "outline" / "volume-plan.md": "# 分卷规划\n\n",
        root / "characters" / "main.md": "# 主要人物\n\n",
        root / "world" / "setting.md": "# 世界观设定\n\n",
        root / "notes" / "todo.md": "# 待办\n\n",
    }

    created_files: list[Path] = []
    for path, content in files.items():
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files.append(path)

    # 题材特定脚手架
    created_files.extend(_genre_scaffolding(root, canonical_genre))

    # writer 项目级元数据(`writer new` 路径)
    if with_writer_meta:
        created_files.extend(_writer_meta_scaffolding(root, force=force, seed_agents=seed_agents))

    return NovelWorkspace(root=root, created_files=created_files)
```

### 关键参数

| 参数 | 默认 | 含义 |
| ---- | ---- | ---- |
| `force` | `False` | 目录存在时是否覆盖 |
| `genre` | `"other"` | 单题材字符串(向后兼容) |
| `genres` | `None` | 多题材列表(优先于 `genre`) |
| `with_ideas_dir` | `False` | 是否建 `创意/` 目录 |
| `with_writer_meta` | `False` | 是否建 `.writer/` 元数据 |
| `seed_agents` | `False` | 是否在 `.writer/agents/` 镜像 shipped agents |

## 10.3 `create_new_workspace()` — `writer new` 路径

```python
def create_new_workspace(name, base_dir, *, genre="other", genres=None, force=False) -> NovelWorkspace:
    """`writer new <书名>` 专用路径:打开所有 meta 选项。"""
    return create_workspace(
        name, base_dir,
        force=force,
        genre=genre,
        genres=genres,
        with_ideas_dir=True,
        with_writer_meta=True,
        seed_agents=True,
    )
```

**差异**:

| 维度 | `create_workspace`(低层 API) | `create_new_workspace`(`writer new`) |
| ---- | ---------------------------- | -------------------------------------- |
| 创意目录 | 取决于 `with_ideas_dir` | 总是 True |
| `.writer/` 元数据 | 取决于 `with_writer_meta` | 总是 True |
| 镜像 shipped agents | 取决于 `seed_agents` | 总是 True |

**向后兼容**:`create_workspace` 不带任何 meta 选项时,行为与最初版本完全一致。

## 10.4 题材脚手架 `_genre_scaffolding()`

```python
def _genre_scaffolding(root: Path, genre: str) -> list[Path]:
    """题材特定脚手架,叠在基础布局之上。"""
    if genre == "历史":
        # 历史:史实校验
        return _ensure_files(root, {
            "史实/README.md": "# 史实库\n\n存放真实历史人物、事件、年份的考证。\n",
            "史实/时间线.md": "# 史实时间线\n\n",
        })
    if genre == "玄幻":
        # 玄幻:伏笔 + 境界表
        return _ensure_files(root, {
            "伏笔/README.md": "# 伏笔库\n\n",
            "伏笔/伏笔.yaml": "# 伏笔 ledger\n",
            "world/境界表.md": "# 境界表\n\n境界1:炼气\n境界2:筑基\n境界3:金丹\n境界4:元婴\n境界5:化神\n",
        })
    if genre == "言情":
        # 言情:人设 + 感情线
        return _ensure_files(root, {
            "人设/README.md": "# 人设库\n\n",
            "characters/感情线时间轴.md": "# 感情线时间轴\n\n",
        })
    return []  # other:无额外脚手架
```

**关键设计**:题材差异以**目录 + 文件**显式表达,LLM 工具循环用 `safe_glob` 探测题材特定目录。

## 10.5 `writer_meta_scaffolding()` — `.writer/` 元数据

```python
_WRITER_CONFIG_TEMPLATE = """\
# 项目级 LLM 配置(优先级高于 .env)
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=
WRITER_BASE_URL=https://api.openai.com/v1
WRITER_TEMPERATURE=0.7
"""


def _writer_meta_scaffolding(root: Path, *, force: bool, seed_agents: bool) -> list[Path]:
    """在 .writer/ 下建 skills / agents / config。"""
    files = {
        root / ".writer" / "config": _WRITER_CONFIG_TEMPLATE,
    }
    if seed_agents:
        # 镜像 shipped agents(让项目级可改)
        for src_md in (Path(__file__).parent.parent / "agents" / "_shipped").glob("*.md"):
            dst = root / ".writer" / "agents" / src_md.name
            if force or not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(src_md.read_text(encoding="utf-8"), encoding="utf-8")
                files[dst] = None  # 标记已建
    # 镜像 shipped skills
    from writer.skills.builtin_sources import BUILTIN_SKILL_SOURCES
    for entry in BUILTIN_SKILL_SOURCES:
        # 每个 shipped skill 一个子目录,含 SKILL.md + .py
        ...
    return list(files.keys())
```

**`.writer/` 的三个子区**:

- `.writer/config` —— 项目级 env 风格 LLM 配置(优先级高于 `.env`)
- `.writer/skills/<command>/SKILL.md` + `instructions.md` —— 项目级 skill 覆盖
- `.writer/agents/<name>.md` —— 项目级 agent 覆盖

镜像 shipped 是为了让用户能「fork 然后改」。

## 10.6 题材白名单与规范化

> 对应代码:`src/writer/project/genre.py`

```python
_GENRE_ALIASES: dict[str, str] = {
    "历史": "历史", "history": "历史", "historical": "历史",
    "言情": "言情", "romance": "言情",
    "玄幻": "玄幻", "xuanhuan": "玄幻", "fantasy": "玄幻",
    "other": "other", "其他": "other", "其它": "other",
}


def normalize_genres(genres: list[str]) -> list[str]:
    """规范化所有 genre 字符串;不在白名单的视为 other。"""
    normalized = []
    for g in genres:
        key = (g or "").strip().lower()
        canonical = _GENRE_ALIASES.get(key, "other")
        normalized.append(canonical)
    # 去重保序
    seen = set()
    result = []
    for g in normalized:
        if g not in seen:
            seen.add(g)
            result.append(g)
    return result


def primary_genre(genres: list[str]) -> str:
    """主题材(列表第一项;空列表返回 other)。"""
    return genres[0] if genres else "other"


def format_genre_line(genres: list[str]) -> str:
    """AGENT.md 题材行的格式:「题材: 历史, 言情」。"""
    return ", ".join(genres)
```

**关键约束**:**任何不在白名单的值视为 `other`**(包括用户自定义「科幻」「悬疑」等)。`AGENT.md` 写 `题材: other, 科幻` 即可。

## 10.7 `AGENT.md` — 项目元数据与状态字段

> 对应代码:`src/writer/project/state.py::render_agent_file`

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
    if project_root is None or not (project_root / "AGENT.md").exists():
        return ProjectState.UNINITIALIZED
    if _has_drafts(project_root):
        return ProjectState.DRAFTING
    if (project_root / "outline" / "toc.md").exists():
        return ProjectState.FRAMING
    if (project_root / "outline" / "大纲.md").exists():
        return ProjectState.OUTLINING
    return ProjectState.INITIALIZED


def read_genre_from_agent(agent_md_path: Path) -> str:
    if not agent_md_path.exists():
        return "other"
    text = agent_md_path.read_text(encoding="utf-8")
    # 匹配「题材: 历史, 言情」或「题材: 历史」
    match = re.search(r"^题材:\s*(.+)$", text, re.MULTILINE)
    if not match:
        return "other"
    raw = match.group(1).strip()
    # 取主题材(逗号分隔的第一项)
    primary = raw.split(",")[0].strip()
    return primary or "other"
```

### `AGENT.md` 3-stage guard

`safe_write_file` 写入 `AGENT.md` 时强制三道关卡:

1. **必须 `mode="overwrite"`** —— 避免 LLM 用 `append` 拼接错乱
2. **内容必须含 `## 当前状态`** —— 防止 LLM 把整个 AGENT.md 改空
3. **旧题材行自动 merge** —— `_merge_genre_line` 从旧文件抽出 `题材:` 行,合并到新内容,避免被覆盖

```python
def _merge_genre_line(old_content: str, new_content: str) -> str:
    """从旧 AGENT.md 抽出 题材: 行,合并到新内容。"""
    old_match = re.search(r"^(题材:.+)$", old_content, re.MULTILINE)
    new_match = re.search(r"^(题材:.+)$", new_content, re.MULTILINE)
    if old_match and not new_match:
        return old_match.group(1) + "\n" + new_content
    return new_content
```

### 字段语义

| 字段 | 谁读 | 谁写 |
| ---- | ---- | ---- |
| `题材:` | `EngineSession.refresh_project_genre()` | `create_workspace` / `safe_write_file` merge |
| `## 当前状态` | `detect_state()` | `safe_write_file` 强制要求存在 |
| `基本要求` | LLM 读 | `create_workspace` 初始 |
| `当前卷` / `当前章节` / `当前进度` | LLM 读;`/状态` 显示 | 未来 `/创作` 写 |

## 10.8 状态转移的「副作用」

状态机本身**不主动写文件**,而是由命令触发:

| 命令 | 副作用文件 | 状态变化 |
| ---- | ---------- | -------- |
| `/init <name>` | 建项目目录 | S0 → S1 |
| `/大纲` | 写 `outline/大纲.md` | S1 → S2 |
| `/目录` | 写 `outline/toc.md` | S2 → S3 |
| `/创作` | 写 `manuscript/*.md` | S3 → S4 |
| `/审核` | 写审核报告 + 修订 `manuscript/*.md` | S4 → S5 |

**为什么状态机不主动更新**:**派生文件**(大纲、目录)的存在已经隐含了状态;让 `detect_state` 从磁盘推导,避免状态与文件不一致。

## 10.9 `chapter_summaries.py` — 章节摘要(per `chg-remove-rag`)

RAG 删除后,章节摘要是 LLM 长程上下文的唯一来源。

```python
def load_chapter_summaries(project_root: Path) -> list[ChapterSummary]:
    """读 <project_root>/manuscript/chapter_summaries.json。"""
    path = project_root / "manuscript" / "chapter_summaries.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ChapterSummary(**entry) for entry in data]


def append_chapter_summary(project_root: Path, summary: ChapterSummary) -> None:
    path = project_root / "manuscript" / "chapter_summaries.json"
    existing = load_chapter_summaries(project_root)
    existing.append(summary)
    path.write_text(json.dumps([asdict(s) for s in existing], ensure_ascii=False, indent=2), encoding="utf-8")
```

**`_build_canon_block`**(per `chg-remove-rag`)—— 4 层文件拼装:

```python
def _build_canon_block(project_root: Path, *, current_chapter: int) -> str:
    block = []
    # 1. outline/大纲.md(全文)
    if (project_root / "outline" / "大纲.md").exists():
        block.append("## 大纲\n" + (project_root / "outline" / "大纲.md").read_text(encoding="utf-8"))
    # 2. characters/main.md(全文)
    if (project_root / "characters" / "main.md").exists():
        block.append("## 人物\n" + (project_root / "characters" / "main.md").read_text(encoding="utf-8"))
    # 3. chapter_summaries.json 切片(最近 N 章)
    summaries = load_chapter_summaries(project_root)
    if summaries:
        recent = summaries[-3:]  # 最近 3 章摘要
        block.append("## 最近章节摘要\n" + "\n\n".join(s.summary for s in recent))
    # 4. 最近一章原文(mansucript/chapter_<current-1>.md)
    prev_chapter = project_root / "manuscript" / f"chapter_{current_chapter - 1}.md"
    if prev_chapter.exists():
        block.append(f"## 上一章({current_chapter - 1})原文\n" + prev_chapter.read_text(encoding="utf-8")[:8000])
    return "\n\n---\n\n".join(block)
```

**为什么 4 层**:LLM 需要 ①全局结构(大纲)+ ②角色(人物)+ ③情节连贯(摘要)+ ④细节(上一章原文),全部来自纯文件拼装,不依赖向量检索。

## 10.10 `init_brief.py` — `/init <brief>` 入口

> 对应代码:`src/writer/project/init_brief.py`

`/init <brief>` 的入口是 `apply_init_brief()`,它内部调 `writer.agents.process_init_brief`:

```python
def apply_init_brief(project_root: Path, brief: str, *, settings: Settings, llm=None) -> InitBriefResult:
    """/init <brief> 入口。

    1. 判断是否在 S1(已 init 项目但还没 brief)
    2. 用 LLM 展开 brief 为完整创意访谈(无 API key 时直接用 brief)
    3. 写入 创意/核心创意.md
    4. 更新 AGENT.md 的基本要求
    """
    from writer.agents import process_init_brief
    return process_init_brief(project_root, brief, settings=settings, llm=llm)


def should_run_init_brief(user_input: str, *, project_root: Path | None, project_state: str) -> bool:
    """判断 /init <brief> 是否应触发 init_brief 流程。

    条件:
    1. project_root 已绑定(S1+)
    2. project_state == S1(INITIALIZED)
    3. user_input 不是 init <name>(无 brief 的 init 不算)
    """
    if project_root is None:
        return False
    if project_state != ProjectState.INITIALIZED.value:
        return False
    rest = extract_init_brief_text(user_input)
    return bool(rest) and looks_like_creative_brief(rest)


def extract_init_brief_text(user_input: str) -> str:
    """从 '/init <brief>' 抽出 brief 文本。"""
    rest = user_input.removeprefix("/init").strip()
    if rest.startswith("--brief "):
        rest = rest.removeprefix("--brief").strip()
    return rest


def looks_like_creative_brief(text: str) -> bool:
    """启发式判断:看起来像创意梗概(>10 字,不含项目名特征)。

    避免把 '/init 我的小说' 误判为 brief(项目名通常 < 10 字)。
    """
    text = text.strip()
    if len(text) < 10:
        return False
    return True
```

**关键设计**:`should_run_init_brief` + `looks_like_creative_brief` 双闸门,避免 `/init 我的小说`(建项目)和 `/init 一个穿越到唐朝的程序员`(写 brief)混淆。

## 10.11 完整数据流:`writer new 长安程序员 -g 历史`

```
CLI: writer new 长安程序员 -g 历史
   ↓
Typer command new(name="长安程序员", genre=["历史"]):
    if not genre: prompt_genres()  # 交互式 prompt
    workspace = create_new_workspace("长安程序员", Path("."), genre="历史")
        ├─ create_workspace(name, base_dir, genre="历史",
        │                    with_ideas_dir=True, with_writer_meta=True, seed_agents=True)
        ├─ 建基础目录:manuscript/ outline/ characters/ world/ notes/ 创意/
        ├─ 写基础文件:AGENT.md(含 题材: 历史, 当前状态: S1) + README.md + 5 个 stub
        ├─ _genre_scaffolding(root, "历史"):
        │     └─ 写 史实/README.md + 史实/时间线.md
        ├─ _writer_meta_scaffolding(root, force=False, seed_agents=True):
        │     ├─ 写 .writer/config(env 模板)
        │     ├─ 镜像 agents:other.md / 历史.md / 言情.md / 玄幻.md → .writer/agents/
        │     └─ 镜像 skills:大纲/ 目录/ → .writer/skills/<name>/{SKILL.md, .py}
        └─ return NovelWorkspace(root=./长安程序员, created_files=[...])
   ↓
console.print(f"已创建: {workspace.root}")
   ↓
用户 cd 长安程序员 && uv run writer
   ↓
REPL 启动:
    EngineSession(project_root=./长安程序员)
        ├─ discover_project_root() → ./长安程序员(有 AGENT.md)
        ├─ production_deps(project_root=./长安程序员)
        │     ├─ built_directive_registry(project_root=./长安程序员)
        │     │     ├─ discover_shipped_directives() → [大纲, 目录]
        │     │     └─ discover_project_directives() → [] (空,项目级未改)
        │     └─ built_agent_registry(project_root=./长安程序员)
        │           ├─ discover_shipped_agents() → [other, 历史, 言情, 玄幻]
        │           └─ discover_project_agents() → [] (空)
        └─ session.project_state = "S1"
        └─ session.project_genre = "历史"(从 AGENT.md 读)
```

---

## 10.12 进一步阅读

- [03-会话与状态机](03-会话与状态机.md) —— 状态机与 `detect_state`
- [08-题材与Agent层](08-题材与Agent层.md) —— 题材差异在 agent Markdown 中的表达
- [备忘 02-正典文件与多源写入一致性](../../技术难点与解决方案备忘/02-正典文件与多源写入一致性.md)