# 07 · 技能 directive 层(SKILL.md)

> 对应代码:`src/writer/skills/{protocol,registry,directive_discovery,errors,builtin_sources,loader}.py` + `src/writer/skills/_shipped/`
> 设计备忘:[`备忘 16-Agent架构模式`](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)

---

## 7.1 设计动机

**问题**:业务规则(「/大纲 应该做什么」)应该放在哪里?

| 方案 | 缺点 |
| ---- | ---- |
| 硬编码在 `RuleBasedIntentRouter` 里 | 命令多了 router 臃肿;非程序员改不了 |
| 写在 Python Skill 类里 | 改一次要重新打包;Python 类不适合放「文本指令」 |
| **Markdown SKILL.md**(本项目) | 文本指令,可直接编辑,LLM 读得懂;同时支持项目级覆盖 |

**核心范式**:**业务规则 = Markdown 文件**。SKILL.md 的 frontmatter(`command` / `description` / `requires_states`)驱动多个下游表面:

1. `/帮助` 命令表
2. Tab 补全词表
3. 命令 × 状态矩阵(自动派生)
4. Engine 分派(从 registry 拿 directive)

**新增一个 directive** = 写一份 Markdown 文件 + reload,**不需要改 Python 代码**。

## 7.2 `SkillDirective` 数据模型

> 对应代码:`src/writer/skills/protocol.py`

```python
@dataclass(frozen=True)
class SkillDirective:
    """一个 SKILL.md 加载后的内存形态。"""
    command: str                              # /大纲 / 目录 / ...
    name: str                                 # "生成大纲"
    description: str                          # 一句话说明
    requires_states: frozenset[ProjectState]  # 哪些状态可用
    body: str                                 # Markdown body(给 LLM 的指令)
    references: dict[str, str] = field(default_factory=dict)  # {relpath: content}
    scripts: list[str] = field(default_factory=list)          # 关联脚本路径
    source_path: Path | None = None                           # 加载来源(便于错误提示)
```

### `extra_instructions` — 项目级 Markdown 覆盖(per `chg-project-skills`)

```python
@dataclass(frozen=True)
class SkillDirective:
    ...
    extra_instructions: str = ""  # 项目级 .md 注入,叠加在 body 末尾
```

**用法**:项目可以在 `<project_root>/.writer/skills/大纲/instructions.md` 写自己的提示,自动拼到 `_shipped/大纲/SKILL.md` body 末尾,**不影响** builtin。

## 7.3 shipped SKILL.md 示例:`_shipped/大纲/SKILL.md`

```markdown
---
command: /大纲
name: 生成大纲
description: 根据用户给的故事梗概,生成四幕结构的写作大纲,写入 outline/大纲.md
requires_states:
  - S1
  - S2
  - S3
  - S4
  - S5
body: |
  你是一位资深小说编辑。用户会给你一个故事梗概,你的任务是:

  1. 先用 safe_read_file 读取项目 AGENT.md 了解题材与设定。
  2. 用 safe_glob 确认 outline/ 是否存在,如不存在就建目录。
  3. 输出一份四幕大纲:
     - 第一幕:铺垫
     - 第二幕:第一转折
     - 第三幕:中盘深化
     - 第四幕:终局落幕
  4. 用 safe_write_file 写入 outline/大纲.md。
  5. 最后用 answer_directly 告诉用户大纲已生成。

references:
  - 4-act-template.md
  - examples.md
scripts: []
---
```

**关键设计**:`body` 是给 LLM 的**指令文本**,不是 Python 代码;LLM 读完后,根据指令里的提示,自己用 tool registry 完成工作。

## 7.4 `DirectiveRegistry` — 注册表

> 对应代码:`src/writer/skills/registry.py`

```python
class DirectiveRegistry:
    def __init__(self) -> None:
        self._directives: dict[str, SkillDirective] = {}

    def register(self, directive: SkillDirective, *, replace: bool = True) -> None:
        """注册一个 directive。

        last-write-wins:重复 command 不再 raise;允许项目级覆盖 builtin。
        旧 raise SkillError 的行为已删除(per chg-markdown-skills)。
        """
        if not replace and directive.command in self._directives:
            raise SkillError(f"directive {directive.command!r} 已注册且 replace=False")
        self._directives[directive.command] = directive

    def get(self, command: str) -> SkillDirective | None:
        return self._directives.get(command)

    def commands(self) -> list[str]:
        return sorted(self._directives.keys())

    def help_entries(self) -> list[tuple[str, str]]:
        """(/命令, 说明) 列表,用于 /帮助 与 Tab 补全。"""
        return [(d.command, d.description) for d in sorted(self._directives.values(), key=lambda d: d.command)]

    def state_matrix(self) -> dict[str, frozenset[ProjectState]]:
        """从每条 directive 的 requires_states 自动派生。"""
        return {d.command: d.requires_states for d in self._directives.values()}
```

### `last-write-wins` vs 显式 raise

- **last-write-wins**(默认):项目级覆盖 builtin / entry-point 覆盖项目级,直接 replace
- **显式 raise**(`replace=False`):用于不希望被覆盖的内部 directive

### 加载优先级

1. `_shipped/*.md`(builtin) → 2. 项目级 `<root>/.writer/skills/*.md` → 3. `entry_points(group="writer.skills")` 插件

**后注册覆盖先注册**,实现自然优先级。

## 7.5 `directive_discovery` — 从磁盘加载 SKILL.md

> 对应代码:`src/writer/skills/directive_discovery.py`

```python
def discover_shipped_directives() -> list[SkillDirective]:
    """扫描 src/writer/skills/_shipped/ 下的所有 SKILL.md。"""
    shipped_dir = Path(__file__).parent / "_shipped"
    return [_parse_skill_md(p / "SKILL.md") for p in shipped_dir.iterdir() if (p / "SKILL.md").exists()]


def discover_project_directives(project_root: Path) -> list[SkillDirective]:
    """扫描 <project_root>/.writer/skills/ 下的所有 SKILL.md。

    每个子目录视为一个 directive:
        .writer/skills/大纲/SKILL.md  →  command=/大纲
        .writer/skills/大纲/instructions.md  →  extra_instructions
    """
    skills_dir = project_root / ".writer" / "skills"
    if not skills_dir.exists():
        return []
    directives = []
    for sub in skills_dir.iterdir():
        skill_md = sub / "SKILL.md"
        if not skill_md.exists():
            continue
        d = _parse_skill_md(skill_md, command_prefix="/")
        # 项目级 instructions.md 注入
        instr_md = sub / "instructions.md"
        if instr_md.exists():
            d = replace(d, extra_instructions=instr_md.read_text(encoding="utf-8"))
        directives.append(d)
    return directives


def discover_entry_point_directives() -> list[SkillDirective]:
    """通过 importlib.metadata.entry_points 加载插件 directive。

    失败/异常只 log.warning,不阻断 REPL。
    """
    directives = []
    for ep in entry_points(group="writer.skills"):
        try:
            obj = ep.load()
            if isinstance(obj, SkillDirective):
                directives.append(obj)
        except Exception as exc:
            log.warning("跳过 entry_point %s: %s", ep.name, exc)
    return directives


def _parse_skill_md(path: Path, *, command_prefix: str = "/") -> SkillDirective:
    """解析 frontmatter + body + references。"""
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    refs_meta = meta.pop("references", [])
    refs = {}
    for ref in refs_meta:
        ref_path = (path.parent / ref).resolve()
        if not ref_path.is_relative_to(path.parent.resolve()):
            raise SkillError(f"reference {ref} 越界")
        refs[ref] = ref_path.read_text(encoding="utf-8")
    command = command_prefix + path.parent.name
    return SkillDirective(
        command=command,
        name=meta.get("name", path.parent.name),
        description=meta.get("description", ""),
        requires_states=frozenset(ProjectState(s) for s in meta.get("requires_states", [])),
        body=body,
        references=refs,
        scripts=meta.get("scripts", []),
        source_path=path,
    )
```

### 关键设计

- **每个 directive 一个子目录**:`<command>/SKILL.md` + `<command>/references/*.md` + `<command>/instructions.md`(项目级)
- **中文 command 名**:`<command>` 可以是中文(文件系统 UTF-8 跨平台),Python 3.14 + pytest tmp_path 下 `Path.glob` 行为正确
- **reference 路径越界检查**:`is_relative_to(path.parent)` 防 LLM 通过 reference 读项目外文件

## 7.6 `built_directive_registry()` — 默认装配

```python
def built_directive_registry(project_root: Path | None = None) -> DirectiveRegistry:
    registry = DirectiveRegistry()
    # 1. shipped builtin
    for d in discover_shipped_directives():
        registry.register(d)
    # 2. 项目级覆盖
    if project_root is not None and str(project_root) != "/__no_project__":
        for d in discover_project_directives(project_root):
            registry.register(d)
    # 3. entry-point 插件
    for d in discover_entry_point_directives():
        registry.register(d)
    return registry
```

**项目切换时 `EngineSession.set_project_root()` 重新调它**,让项目级覆盖在下一轮生效。

## 7.7 加载优先级图

```
┌──────────────────────────────┐
│ _shipped/*.md (builtin)      │  ← 基础能力(2 个:/大纲 /目录)
└──────────────┬───────────────┘
               │ register(last-write-wins)
               ▼
┌──────────────────────────────┐
│ <root>/.writer/skills/*.md   │  ← 项目级覆盖(可选)
└──────────────┬───────────────┘
               │ register
               ▼
┌──────────────────────────────┐
│ entry_points(group="writer.  │  ← 插件(可选,importlib.metadata)
│   skills")                   │
└──────────────────────────────┘
```

后注册覆盖先注册 → 项目级覆盖 builtin。

## 7.8 `_run_directive` — Engine 怎么消费 SKILL.md

> 对应代码:`src/writer/engine/loop.py::_run_directive`

```python
async def _run_directive(directive, ctx, deps, cfg):
    from writer.skills.directive_discovery import resolve_references
    resolved = resolve_references(directive.body, directive.references)

    if deps.tool_loop is not None:
        # 1. 把 directive body 喂给 LLM
        action = AgentAction(
            action_type="answer_directly",
            command=directive.command,
            answer=directive.body,
        )
        # 2. LLM 读 body 后,用 tool registry 完成任务
        async for event in deps.tool_loop.run(action, ctx, deps, cfg):
            yield event
    else:
        # 纯规则部署(无 API key):只输出 preview
        yield TextChunk(text=f"[engine] directive body (preview, no LLM configured):\n...")
        yield Done(reason="answered", payload={"directive": directive.command, "llm_available": False})
```

**关键设计**:LLM 收到 `directive.body` 作为 system identity(由 `_initial_messages` 拼接),user input 作为 human message。LLM 看到指令后,自己决定调哪个 tool、调用顺序。

### `_initial_messages` 中 directive 注入

> 对应代码:`src/writer/llm/agent.py::_initial_messages`

```python
def _initial_messages(self, action, user_input, *, deps):
    system_parts = [self._system_prompt()]

    # 1. directive body
    if action.action_type == "answer_directly" and action.command:
        directive_meta = deps.directive_registry.get(action.command)
        if directive_meta is not None:
            refs = "\n\n".join(f"--- {relpath} ---\n{body}" for relpath, body in directive_meta.references.items())
            section = f"[directive body: {directive_meta.command}]\n{directive_meta.body}"
            if refs:
                section += f"\n\n[directive references]\n{refs}"
            if directive_meta.extra_instructions:
                section += f"\n\n[project-level extra instructions]\n{directive_meta.extra_instructions}"
            system_parts.append(section)

    # 2. agent identity
    if action.target_agent:
        agent_meta = deps.agent_registry.get(action.target_agent)
        if agent_meta is not None:
            system_parts.append(f"[agent identity: {agent_meta.name}]\n{agent_meta.body}")

    # 3. router hint
    if action.answer:
        system_parts.append(f"[router hint]\n{action.answer}")

    return [
        SystemMessage(content="\n\n".join(system_parts)),
        HumanMessage(content=user_input),
    ]
```

**Bug 02 修复**:2026-07-09 增补 directive body 注入;之前 LLM 收不到 SKILL.md 内容,直接当普通 `answer_directly` 处理。

## 7.9 SKILL.md 加载完整路径

```
CLI 启动:
    EngineSession(project_root=auto_discovered)
        └─ production_deps(project_root=...)
            └─ built_directive_registry(project_root=...)
                ├─ discover_shipped_directives() → [大纲, 目录]
                ├─ discover_project_directives(project_root) → []
                └─ discover_entry_point_directives() → []
                └─ DirectiveRegistry: {"/大纲": ..., "/目录": ...}

用户输入 "/大纲 穿越到唐朝":
    deps.route() → AgentAction(action_type="run_command", command="/大纲")
    engine 分派 → directive = deps.directive_registry.get("/大纲")
    _run_directive(directive, ctx, deps, cfg)
        ├─ resolve_references(body, references) → 4-act-template.md / examples.md 内容
        ├─ 构造 agent_action (answer_directly, command="/大纲", answer=body)
        └─ async for event in deps.tool_loop.run(agent_action, ctx, deps, cfg):
            ReActAgent.run():
                _initial_messages(): 拼 system prompt = base + directive body + refs + extra_instructions
                LLM 读到 directive body,按指令调 safe_read_file / safe_write_file
```

## 7.10 关键设计约束

### 1. SKILL.md 不应该做的事

- ❌ 写大段 Python 代码(LLM 读得动但不执行)
- ❌ 描述整个项目(那是 `CLAUDE.md` 的活)
- ❌ 写 prompt engineering 教科书(放 `prompts/`)

### 2. SKILL.md 应该做的事

- ✅ 一句话说明这个命令做什么
- ✅ 给 LLM 步骤(读 AGENT.md → 写 outline.md)
- ✅ 引用 reference 模板(4-act-template.md / examples.md)
- ✅ 列出可用状态(`requires_states`)

### 3. 加新 directive 不需要改 Python

```bash
# 1. 创建新目录
mkdir -p src/writer/skills/_shipped/伏笔

# 2. 写 SKILL.md
cat > src/writer/skills/_shipped/伏笔/SKILL.md <<'EOF'
---
command: /伏笔
name: 添加伏笔
description: 在 伏笔.yaml 中新增一条伏笔
requires_states:
  - S1
  - S2
  - S3
  - S4
  - S5
body: |
  你在维护一份伏笔 ledger。用 safe_read_file 读 伏笔.yaml(如存在),
  追加用户给的新伏笔条目,再用 safe_write_file 写回。
references: []
scripts: []
---
EOF

# 3. reload 即可生效(下次 REPL 启动自动发现)
uv run writer
> /伏笔 F003 玉佩真实来历
```

## 7.11 进一步阅读

- [08-题材与Agent层](08-题材与Agent层.md) —— 类似的 Markdown 范式,用在题材身份上
- [15-演进与备忘体系](15-演进与备忘体系.md) —— `chg-markdown-skills` 与 `chg-project-skills` 的演进
- [备忘 16-Agent架构模式](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)