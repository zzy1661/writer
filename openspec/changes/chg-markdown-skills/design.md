## Context

`chg-project-skills`（已 apply 但 2026-07-09 归档时跳过 sync）走的是 Python + Markdown 混合路线,4 个内置 skill 是 Python class (`OutlineSkill` / `TocSkill` / `ContinueWritingSkill` / `ReviseSkill`),项目级 `.writer/skills/<command>.py` 是 Python 镜像。

`chg-markdown-skills`（本次新方向）整体转向纯 Markdown SKILL.md 范式,与 Claude Code `~/.claude/skills/<name>/SKILL.md` 1:1 对齐。**4 个内置 Python class 全部删除**,改成 ship `src/writer/skills/_shipped/<command>/SKILL.md`(下划线表示内部 packaging),`create_new_workspace` 时拷贝到 `<root>/.writer/skills/<command>/`。拷贝后 shipped 与用户自加**不可区分**,用户可自由编辑。

Engine dispatch 从 `async for event in skill.run()`(Python async generator)改为 LLM-driven directive injection:engine 把 directive body + `@reference` 引用的内容塞进 LLM system message,LLM 调 tools 完成实际工作。

## Goals / Non-Goals

**Goals:**
- 全 Markdown SKILL.md 范式——零 Python 编写门槛
- 项目级与 shipped skill 在 `.writer/skills/` 不可区分,用户可编辑
- engine 把 directive 内容注入 LLM,LLM 用现有 tools 完成工作
- 不动 router / engine loop 主线 / LLM 工具循环 / 4 个 builtin tool
- 4 个内置 skill 仍是项目级 `.writer/skills/` 的固定可见项(写章节时 `/大纲` 永远可用)

**Non-Goals:**
- 不做 SKILL.md hot-reload(改完重启 REPL)
- 不做 references/ 自动检索(用显式 `@reference path` 语法)
- 不做 scripts/ 自动注册 tool
- 不做 body 预解析 sections
- 不为 advanced user 保留 Python Skill escape hatch

## Decisions

### 1. Skill format = `<command>/SKILL.md` 目录布局

**决定**:`<project>/.writer/skills/<command>/SKILL.md` 是入口,加可选 `references/` + `scripts/`。**不是** `<command>.md` 单文件。

**理由**:Claude Code `~/.claude/skills/<name>/SKILL.md` 1:1 对齐;`references/` 提供模块化补充文档;`scripts/` 给愿意写脚本的 LLM 友好的辅助代码。

**SKILL.md frontmatter**:
```yaml
---
command: /大纲
description: 生成或查看大纲
requires_states: [INITIALIZED, HAS_OUTLINE]
---
```

**SKILL.md body**:Markdown 正文,LLM 指令。

### 2. `SkillDirective` Protocol 替换 `Skill` Protocol

**决定**:删 `Skill` Protocol,新建 `SkillDirective` Protocol:

```python
@dataclass(frozen=True)
class SkillDirective:
    command: str
    description: str
    requires_states: frozenset[ProjectState]
    body: str  # SKILL.md 正文(已 strip frontmatter)
    references: dict[str, str]  # {relpath: file_content}; 全量读,LLM 按需检索
    scripts: list[str]  # scripts/*.py 相对路径列表;不读内容,LLM 用 Bash 调
    root: Path  # `<command>/` 目录路径,scripts 实际执行时用 safe_path 兜底
```

**理由**:`Skill` 的 `run()` async generator 不再需要——Markdown 范式下"skill 执行"是 LLM 调 tools,不是 Python 代码。`body` 是单 string(per Open Question 2)。`references` 整目录读但 LLM 按 `@reference` 选(per Open Question 3)。

**替代方案 A**:保留 `Skill` Protocol 作为 Python escape hatch。**否决**——增加表面复杂度,违背"全 Markdown"决策。

**替代方案 B**:`references` 懒加载,只在 LLM 请求时读盘。**否决**——LLM 不主动请求,反而要 engine 预解析 body 找 `@reference` 字符串;全量读 + 后过滤更简单。

### 3. DirectiveRegistry 替换 SkillRegistry

**决定**:`SkillRegistry` 改名 `DirectiveRegistry`,内部 dict value 类型从 `Skill` 改 `SkillDirective`。接口 `get()` / `commands()` / `help_entries()` / `state_matrix()` 不变。

**理由**:语义对齐("registry of directives")。4 个 surface API 不变,下游 CLI help / 补全 / 状态机拦截不用改。`state_matrix()` 仍然从 `directive.requires_states` 派生。

### 4. 加载机制:目录扫描 + frontmatter 解析

**决定**:`discover_directives(project_root: Path) -> list[SkillDirective]`:
1. 扫 `<project>/.writer/skills/*/SKILL.md`
2. 每个 SKILL.md 解析 YAML frontmatter + body
3. 读 `references/` 所有 `*.md` 进 `references: dict`
4. 列 `scripts/*.py` 相对路径进 `scripts: list`
5. 失败 `log.warning + 跳过`,不阻断 REPL

**frontmatter 解析**:用 stdlib `yaml.safe_load`(PyYAML 已在依赖)。手写一个 30 行的小解析器避免 `python-frontmatter` 新依赖——SKILL.md frontmatter 模式简单,没必要引入完整 frontmatter 包。

**理由**:`re` 解析 frontmatter(只匹配 `---\n...\n---\n`) + `yaml.safe_load(frontmatter_str)` 是最少代码路径。

**替代方案 A**:用 `python-frontmatter` 包。**否决**——多一个依赖,SKILL.md 格式简单。

### 5. Engine dispatch:directive injection 路径

**决定**:在 `engine/loop.py` 的 `case "run_command"` 分支加 directive dispatch:

```python
case "run_command":
    if action.command and (directive := deps.directive_registry.get(action.command)) is not None:
        # LLM-driven path: inject directive body + references into system
        async for event in _run_directive(directive, ctx, deps, cfg):
            yield event
    elif action.command and (skill := deps.skill_registry.get(action.command)) is not None:
        # legacy Python path (preserved during migration)
        async for event in skill.run(ctx, deps, cfg):
            yield event
    else:
        yield Done(reason="command_pending", payload={"command": action.command})
```

`_run_directive` 实现:
1. 解析 `directive.body` 里的 `@reference path/to/file.md` 语法,把内容塞进 system message
2. 把 `directive.body` 整体作为 system 消息的"skill instructions"部分
3. 走 `LLMToolLoop` 一样的工具循环;LLM 用现有 tools(safe_read_file / safe_write_file / project_search / etc.)完成工作
4. 收尾 yield `TextChunk` 流 + `Done(reason="answered", payload={"directive": command, "tokens": ...})`

**理由**:`LLMToolLoop` 已经存在,只复用其"工具调用 + JSON 输出解析"机制;directive 只是给它一个"先看 SKILL.md 指令,再做事"的 system prompt。

**替代方案 A**:directive 不复用 LLM tool loop,engine 自己流式产出 TextChunk + 让 LLM 在 background 跑。**否决**——破坏现有 engine 流式契约。

**替代方案 B**:删 directive dispatch 的 async 路径,改成 sync + yield all events at once。**否决**——用户体验差。

### 6. shipped skills = 数据文件(importlib.resources)

**决定**:`src/writer/skills/_shipped/{大纲,目录,续写,改}/SKILL.md` + `references/` + `scripts/` 作为 package data(用 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel.force-include]` 或 `importlib.resources.files()`)。

**调用路径**:
- `create_new_workspace` 调 `_seed_directives(writer_root)`,用 `importlib.resources.files("writer.skills._shipped")` 遍历 4 个目录,逐文件 `read_text()` + `write_text()` 到 `<root>/.writer/skills/<command>/`
- 拷贝后原 shipped 路径与项目级路径不可区分

**理由**:Python 打包"shipped templates"的标准模式(setuptools `package_data`,hatchling `force-include`)。`importlib.resources.files()` 是 stdlib,无需额外依赖。

### 7. 4 个 shipped SKILL.md 内容骨架

每个 shipped skill 的 SKILL.md frontmatter 同(命令名 + description + requires_states),body 不同:

| command | body 大纲 |
| --- | --- |
| `/大纲` | 角色("你是长篇小说大纲生成助手"),输入(用户故事梗概),输出大纲文件路径,执行步骤(读 outline/premise.md → 调 StoryConsultant.draft_outline → 写 outline/大纲.md → 刷 AGENT.md → yield TextChunk 显示章节列表) |
| `/目录` | 同模式:读 outline/大纲.md → 调 StoryConsultant.draft_toc → 写 outline/toc.md → 刷 AGENT.md |
| `/续写` | 占位("LLM 读取 manuscript/ 最新章节,调 StoryConsultant.continue_chapter,追加到当前 draft") |
| `/改` | 占位("LLM 读取章节 draft,接收自然语言修改指令,调 StoryConsultant.revise_chapter") |

**每个 shipped skill 都附 `references/`**:
- `大纲/references/`: `4-act-template.md`(四幕模板), `examples.md`(示例输出)
- `目录/references/`: `chapter-format.md`(章节编号规则)
- `续写/references/`: `style-guide.md`(文风提示)
- `改/references/`: `diff-format.md`(diff 输出格式)

**scripts/** 是可选项(本期可能为 0 个),`_shipped/大纲/scripts/format_outline.py` 留给后续。

### 8. working tree 清理

**apply 时执行**:
- 删 `src/writer/skills/{outline,toc,continue_writing,revise}.py`(4 个 Python class)
- 删 `src/writer/skills/loader.py`(Python importlib loader)
- 删 `src/writer/skills/builtin_sources.py`(mirror 元组)
- 改 `src/writer/skills/protocol.py`: `Skill` Protocol → `SkillDirective` dataclass
- 改 `src/writer/skills/registry.py`: `SkillRegistry` → `DirectiveRegistry`
- 改 `src/writer/skills/__init__.py`: re-export 改名
- 删 `src/writer/project/workspace.py` 里的 `_seed_skill_mirrors` / `_render_skill_mirror` / `_resolve_source_path`,换成 `_seed_directives`
- 改 `src/writer/engine/loop.py`: `case "run_command"` 加 directive dispatch 分支
- 改 `src/writer/engine/deps.py`: `skill_registry` 字段名 → `directive_registry`,`rebind_skill_registry` 方法 → `rebind_directive_registry`
- 改 `src/writer/session/engine_session.py`: `set_project_root` 重建 directive_registry
- 删 `tests/test_skill_loader.py`(整个文件)
- 删 `tests/test_skill_registry.py`(整个文件),新建 `tests/test_directive_registry.py`
- 新建 `tests/test_directive_dispatch.py`(engine dispatch 测试)
- 改 `tests/test_engine_session.py`: PlainDeps stub 字段重命名
- 改 `tests/test_engine_deps.py`: 字段名改
- 新建 `src/writer/skills/_shipped/{大纲,目录,续写,改}/SKILL.md` × 4 + `references/` × 4

## Risks / Trade-offs

[High:核心架构变更——dispatch 从 Python async generator 改为 LLM directive injection] → **Mitigation**:
(1) engine directive 分支先复用 `LLMToolLoop` 已有逻辑,新代码量小;
(2) 写完整 acceptance test 覆盖 4 个 shipped directive 各跑一遍,验证 end-to-end 行为不变;
(3) 保留旧 `Skill` Python 路径作为 legacy fallback(虽然本 change 不保留外部 Python Skill 用户,但 4 个内置 skill 删之前可以并行验证)。

[Medium:失去 Python 单测覆盖] → **Mitigation**:
(1) SKILL.md 内容有 markdown 结构 assertion 测试(frontmatter 正确 / body 不空 / `@reference` 路径存在);
(2) engine directive dispatch 路径有 end-to-end test(LLM mock 返回 expected TextChunk 序列);
(3) 后续可加"SKILL.md lint"工具确保 shipped 内容质量。

[Medium:中文目录名作为 filesystem path] → **Mitigation**:已有 chg-project-skills 验证 OK;新增 shipped 也用中文目录名。

[Low:`rebind_skill_registry` 改名打破现有 fake `EngineDeps` stub] → **Mitigation**:PlainDeps 是唯一手写 stub,apply 阶段一起改。

[Low:`LLMToolLoop` 复用可能要求 directive 提供 tool list] → **Mitigation**:第一版 directive 不引入新 tool,复用 builtin tool registry;后续按需扩展。

## Migration Plan

**部署步骤**(apply 阶段按 tasks.md 顺序):
1. 写 `SkillDirective` Protocol + dataclass
2. 写 `directive_discovery.py` + `DirectiveRegistry`
3. 写 4 个 shipped SKILL.md + references/
4. 改 workspace seeding (delete mirror, add seed_directives)
5. 改 engine loop 加 directive dispatch
6. 改 EngineDeps / EngineSession
7. 删旧 Python 4 个 class + loader.py + builtin_sources.py
8. 改 tests (删除旧 test_skill_*, 新建 test_directive_*)
9. validate + archive

**回滚策略**:`git revert` 整个 commit。删除的 4 个 Python class 可从 git 历史恢复;shipped SKILL.md 内容若回滚丢失需要重写。**用户感知**:无破坏性,所有 4 个 slash command 行为不变(从 Python 实现改成 LLM 指令实现,LLM 输出应该相同)。

**兼容窗口**:无 main spec 改动(没有 sync,因 `chg-project-skills` 归档时跳过了)。

## Open Questions

无 — 上一轮 4 个 Open Questions 已确认(见 proposal.md)。