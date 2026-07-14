# 07 · 技能 directive 层（SKILL.md，无状态矩阵）

> 对应代码：`src/writer/skills/{protocol,registry,directive_discovery,errors,builtin_sources,loader}.py` + `src/writer/skills/_shipped/`
> 设计备忘：[`备忘 16-Agent架构模式`](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)
>
> **2026-07-14 修订**：本文原版本仍写 `requires_states`、`SkillDirective.name/extra_instructions`、`DirectiveRegistry.state_matrix()`、命令 × 状态矩阵。
> 截至 `chg-remove-state-machine-enforcement`（2026-07-12）落地，`SkillDirective` 字段精简为 6 个（`command / description / body / references / scripts / root`），**无** `requires_states` / `name` / `extra_instructions`；`DirectiveRegistry.state_matrix()` 与引擎内 `validate_command_available()` 拦截全删；`SKILL.md` frontmatter 只需 `command` / `description` 两个必填字段。
>
> 引擎 dispatch 由 `Engine._engine_loop` 的 `run_command` 分支通过 `deps.directive_registry.get(action.command)` 动态匹配，新增 directive **不需要改 Python 代码**。

---

## 7.1 设计动机

**问题**：业务规则（「/大纲 应该做什么」）应该放在哪里？

| 方案                                | 缺点                                                |
| ----------------------------------- | --------------------------------------------------- |
| 硬编码在 `RuleBasedIntentRouter` 里 | 命令多了 router 臃肿；非程序员改不了                |
| 写在 Python Skill 类里              | 改一次要重新打包；Python 类不适合放「文本指令」      |
| **Markdown SKILL.md**（本项目）     | 文本指令，可直接编辑，LLM 读得懂；支持项目级覆盖    |

**核心范式**：**业务规则 = Markdown 文件**。SKILL.md 的 frontmatter（`command` / `description`）驱动多个下游表面：

1. `/帮助` 命令表（从 `DirectiveRegistry.help_entries()` 派生）
2. Tab 补全词表（从 `DirectiveRegistry.commands()` 派生）
3. Engine 分派（从 registry 拿 directive，动态匹配）

**新增一个 directive** = 写一份 Markdown 文件 + reload，**不需要改 Python 代码**。

> **2026-07-12 移除项**：命令 × 状态矩阵不再派生；SKILL.md 不再声明可用状态；命令在任意 `ProjectState` 均可调用。

## 7.2 `SkillDirective` 数据模型（2026-07-12 后 6 字段）

> 对应代码：`src/writer/skills/protocol.py`

```python
@dataclass(frozen=True)
class SkillDirective:
    """一个 SKILL.md 加载后的内存形态。"""

    command: str                              # /大纲 / 目录 / ...
    description: str                          # 一句话说明（YAML frontmatter）
    body: str                                 # Markdown body（给 LLM 的指令）
    references: dict[str, str] = field(default_factory=dict)  # {relpath: content}
    scripts: list[str] = field(default_factory=list)          # 关联脚本路径
    root: Path = field(default_factory=Path)                  # directive 所在目录绝对路径
```

### 已删除字段

| 删除字段                | 替代                                                    |
| ----------------------- | ------------------------------------------------------- |
| `name: str`             | 由 `command` 的中文标签承担（如 `command="/大纲"`）      |
| `requires_states: frozenset[ProjectState]` | 命令拦截矩阵已删（`chg-remove-state-machine-enforcement`） |
| `extra_instructions: str`（项目级 Markdown 覆盖） | 项目级 `instructions.md` 加载逻辑移除（per chg-markdown-skills）；项目级覆盖仍走整文件 `replace` |
| `source_path: Path | None` | 由 `root: Path` 统一承担                                 |

## 7.3 shipped SKILL.md 示例：`_shipped/大纲/SKILL.md`

```markdown
---
command: /大纲
description: 根据用户给的故事梗概生成四幕结构大纲，写入 大纲/大纲.md
---

你是资深小说编辑。用户会给你一个故事梗概，你的任务是:

1. 用 safe_read_file 读取项目 AGENT.md 了解题材与设定。
2. 用 safe_glob 确认 大纲/ 目录存在。
3. 输出四幕大纲:
   - 第一幕:铺垫
   - 第二幕:第一转折
   - 第三幕:中盘深化
   - 第四幕:终局落幕
4. 用 safe_write_file 写入 大纲/大纲.md。
5. 用 answer_directly 告诉用户大纲已生成。

@reference 4-act-template.md
@reference examples.md
```

**关键设计**：`body` 是给 LLM 的**指令文本**，不是 Python 代码。`@reference path/to/file.md` 由 `directive_discovery.resolve_references` 解析为 `(relpath, content)` 对注入 system prompt，让 LLM 可读取模板 / 示例。

> **2026-07-12 后** frontmatter 只需 `command` 与 `description` 两个必填字段。`requires_states:` 行即便残留也由 `yaml.safe_load` 容错忽略。

## 7.4 `DirectiveRegistry` —— 注册表

> 对应代码：`src/writer/skills/registry.py`

```python
class DirectiveRegistry:
    def __init__(self) -> None:
        self._directives: dict[str, SkillDirective] = {}

    def register(self, directive: SkillDirective, *, replace: bool = True) -> None:
        """注册一个 directive。

        last-write-wins：重复 command 不再 raise；允许项目级覆盖 builtin。
        旧 raise SkillError 的行为已删除（per chg-markdown-skills）。
        """
        if not replace and directive.command in self._directives:
            raise SkillError(f"directive {directive.command!r} 已注册且 replace=False")
        self._directives[directive.command] = directive

    def get(self, command: str) -> SkillDirective | None:
        return self._directives.get(command)

    def commands(self) -> list[str]:
        return sorted(self._directives.keys())

    def help_entries(self) -> list[tuple[str, str]]:
        """(/命令, 说明) 列表，用于 /帮助 与 Tab 补全。"""
        return [(d.command, d.description) for d in sorted(self._directives.values(), key=lambda d: d.command)]
```

### 已删除方法

- `state_matrix()` —— 状态矩阵已删；命令拦截由 SKILL.md body 的 LLM 自主判断。

### `last-write-wins` vs 显式 raise

- **last-write-wins**（默认）：项目级覆盖 builtin / entry-point 覆盖项目级，直接 replace
- **显式 raise**（`replace=False`）：用于不希望被覆盖的内部 directive

### 加载优先级

1. `_shipped/<command>/SKILL.md`（builtin）
2. 项目级 `<root>/.writer/skills/<command>/SKILL.md`（可选）
3. `entry_points(group="writer.skills")` 插件

**后注册覆盖先注册**，实现自然优先级。

## 7.5 `directive_discovery` —— 从磁盘加载 SKILL.md

> 对应代码：`src/writer/skills/directive_discovery.py`

```python
def discover_shipped_directives() -> list[SkillDirective]:
    """扫描 src/writer/skills/_shipped/ 下的所有 SKILL.md。"""
    shipped_dir = Path(__file__).parent / "_shipped"
    return [_parse_skill_md(p / "SKILL.md") for p in shipped_dir.iterdir() if (p / "SKILL.md").exists()]


def discover_project_directives(project_root: Path) -> list[SkillDirective]:
    """扫描 <project_root>/.writer/skills/ 下的所有 SKILL.md。

    每个子目录视为一个 directive:
        .writer/skills/大纲/SKILL.md  →  command=/大纲
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
        directives.append(d)
    return directives


def discover_entry_point_directives() -> list[SkillDirective]:
    """通过 importlib.metadata.entry_points 加载插件 directive。

    失败/异常只 log.warning，不阻断 REPL。
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
        description=meta.get("description", ""),
        body=body,
        references=refs,
        scripts=meta.get("scripts", []),
        root=path.parent,
    )
```

### 关键设计

- **每个 directive 一个子目录**：`<command>/SKILL.md` + `<command>/references/*.md`（references 内联在 SKILL.md frontmatter 的 `references:` 列表）
- **中文 command 名**：`<command>` 可以是中文（文件系统 UTF-8 跨平台），Python 3.14 + pytest tmp_path 下 `Path.glob` 行为正确
- **reference 路径越界检查**：`is_relative_to(path.parent)` 防 LLM 通过 reference 读项目外文件

## 7.6 `built_directive_registry()` —— 默认装配

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

**项目切换时 `EngineSession.set_project_root()` 重新调它**，让项目级覆盖在下一轮生效。

## 7.7 加载优先级图

```
┌──────────────────────────────┐
│ _shipped/*/SKILL.md (builtin)│  ← 基础能力（2 个：/大纲 /目录）
└──────────────┬───────────────┘
               │ register(last-write-wins)
               ▼
┌──────────────────────────────┐
│ <root>/.writer/skills/*/SKILL│  ← 项目级覆盖（可选）
└──────────────┬───────────────┘
               │ register
               ▼
┌──────────────────────────────┐
│ entry_points(group="writer.  │  ← 插件（可选，importlib.metadata）
│   skills")                   │
└──────────────────────────────┘
```

后注册覆盖先注册 → 项目级覆盖 builtin。

## 7.8 `_run_directive` —— Engine 怎么消费 SKILL.md

> 对应代码：`src/writer/engine/engine.py::Engine._run_directive`

```python
class Engine:
    async def _run_directive(self, directive: SkillDirective, ctx: EngineContext):
        from writer.skills.directive_discovery import resolve_references
        deps = self._deps
        cfg = self._cfg

        if not cfg.fast_mode:
            yield TextChunk(
                text=f"[engine] {directive.command} → directive ({directive.command})\n"
            )

        # 把 @reference path 提及解析为 (相对路径, 内容) 对。
        resolved = resolve_references(directive.body, directive.references)

        if deps.tool_loop is not None:
            # 把 directive + 解析后的引用交给现有 LLM 工具循环。
            from writer.routing import AgentAction
            action = AgentAction(
                action_type="answer_directly",
                command=directive.command,
                answer=directive.body,
            )
            async for event in deps.tool_loop.run(action, ctx, deps, cfg):
                yield event
        else:
            # 没有可用 LLM —— 产出有用的预览
            yield TextChunk(text=(
                f"[engine] directive body (preview, no LLM configured):\n"
                f"  command: {directive.command}\n"
                f"  description: {directive.description}\n"
                f"  body length: {len(directive.body)} chars\n"
                f"  references: {len(resolved)} files\n"
                f"  scripts: {len(directive.scripts)} files\n"
            ))
            if resolved:
                preview = "\n".join(
                    f"  ref: {relpath} ({len(content)} chars)"
                    for relpath, content in resolved
                )
                yield TextChunk(text=preview + "\n")
            yield Done(
                reason="answered",
                payload={
                    "directive": directive.command,
                    "body_length": len(directive.body),
                    "references": [relpath for relpath, _ in resolved],
                    "scripts": list(directive.scripts),
                    "llm_available": False,
                },
            )
```

**关键设计**：

- **Engine dispatch 动态化**（per `chg-markdown-skills`）：移除旧的 `elif action.command in {"/大纲", "/目录"}` 硬编码，改为 `elif (directive := deps.directive_registry.get(action.command)) is not None`。
- **LLM 收到 `directive.body` 作为 system identity**（由 `ReActAgent._initial_messages` 拼接），user input 作为 human message；LLM 看到指令后自己决定调哪个 tool、调用顺序。
- **无 LLM 部署**：`tool_loop=None` 时降级为 preview 输出，不真调 LLM。

### `_initial_messages` 中 directive 注入

> 对应代码：`src/writer/llm/agent.py::_initial_messages`

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

**Bug 02 修复**：2026-07-09 增补 directive body 注入；之前 LLM 收不到 SKILL.md 内容，直接当普通 `answer_directly` 处理。

## 7.9 SKILL.md 加载完整路径

```
CLI 启动:
    EngineSession(project_root=auto_discovered)
        └─ __post_init__ 构造 Engine(deps=production_deps(project_root=...))
            └─ built_directive_registry(project_root=...)
                ├─ discover_shipped_directives() → [大纲, 目录]
                ├─ discover_project_directives(project_root) → []
                └─ discover_entry_point_directives() → []
                └─ DirectiveRegistry: {"/大纲": ..., "/目录": ...}

用户输入 "/大纲 穿越到唐朝":
    session.run_turn(user_input) → 构造 EngineContext + 委派给 session.engine.run(ctx)
    Engine._engine_loop:
        self._deps.route() → AgentAction(action_type="run_command", command="/大纲")
        match action.action_type:
            case "run_command":
                if action.command == "/init":
                    async for event in self._run_init_command(ctx): yield event
                elif action.command and (directive := self._deps.directive_registry.get(action.command)) is not None:
                    async for event in self._run_directive(directive, ctx): yield event
                else:
                    yield Done(reason="command_pending", payload={"command": action.command})
        → _run_directive(directive, ctx):
            ├─ resolve_references(body, references) → 4-act-template.md / examples.md 内容
            ├─ 构造 agent_action (answer_directly, command="/大纲", answer=body)
            └─ async for event in self._deps.tool_loop.run(agent_action, ctx, self._deps, self._cfg):
                ReActAgent.run():
                    _initial_messages(): 拼 system prompt = base + directive body + refs
                    LLM 读到 directive body,按指令调 safe_read_file / safe_write_file
```

## 7.10 关键设计约束

### 1. SKILL.md 不应该做的事

- ❌ 写大段 Python 代码（LLM 读得动但不执行）
- ❌ 描述整个项目（那是 `CLAUDE.md` 的活）
- ❌ 写 prompt engineering 教科书（放 `prompts/`）
- ❌ 声明 `requires_states:`（per `chg-remove-state-machine-enforcement` 已无效）

### 2. SKILL.md 应该做的事

- ✅ 一句话说明这个命令做什么（frontmatter `description:`）
- ✅ 给 LLM 步骤（读 AGENT.md → 写 大纲/大纲.md）
- ✅ 引用 reference 模板（`@reference 4-act-template.md`）
- ✅ 让 LLM 自主判断「已存在 vs 新建 / 追加 vs 覆盖」（替代旧的 `requires_states` 拦截）

### 3. 加新 directive 不需要改 Python

```bash
# 1. 创建新目录
mkdir -p src/writer/skills/_shipped/伏笔

# 2. 写 SKILL.md
cat > src/writer/skills/_shipped/伏笔/SKILL.md <<'EOF'
---
command: /伏笔
description: 在 伏笔.yaml 中新增一条伏笔
---

你在维护一份伏笔 ledger。用 safe_read_file 读 伏笔.yaml (如存在),
追加用户给的新伏笔条目,再用 safe_write_file 写回。

@reference schema.md
EOF

# 3. reload 即可生效（下次 REPL 启动自动发现）
uv run writer
> /伏笔 F003 玉佩真实来历
```

## 7.11 进一步阅读

- [08-题材与Agent层](08-题材与Agent层.md) —— 类似的 Markdown 范式，用在题材身份上
- [15-演进与备忘体系](15-演进与备忘体系.md) —— `chg-markdown-skills` / `chg-project-skills` / `chg-remove-state-machine-enforcement` 的演进
- [备忘 16-Agent架构模式](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)