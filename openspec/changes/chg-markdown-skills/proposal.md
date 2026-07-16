## Why

`chg-project-skills`（已 apply 但未归档,2026-07-09）走的是 Python + Markdown 混合路线：`<command>.py` Python 镜像 + `<command>.md` 副文。4 个内置 skill（`OutlineSkill` / `TocSkill` / `ContinueWritingSkill` / `ReviseSkill`）继续保留为 Python class,只是把 `.py` 复制到 `<project>/.writer/skills/`,用户改 .py 来覆盖。

但是:**真正的项目 skill 范式参考是 Claude Code**,不是 Python 包加载。Claude Code 用 `~/.claude/skills/<name>/SKILL.md` + `references/` + `scripts/` + `VERSION` 的纯文件结构——用户编辑 .md 即可,引擎只读不编译。`.py` 路线要求用户懂 Python import / Class / dataclass / `Skill` Protocol,门槛远高于 Markdown。

而且本项目 4 个内置 skill 的 Python 实现（调 `deps.story_consultant.draft_outline()` 等）本质上是**给 LLM 看的执行指令**:`读 outline 文件 → 调 story_consultant → 写 outline/大纲.md → 刷 AGENT.md`。LLM 完全能自己用 `safe_read_file` / `safe_write_file` / 调 `story_consultant` tool 完成这件事,不需要中间这层 Python wrapper。

所以**整体转向纯 Markdown SKILL.md + Claude Code 风格目录布局**,4 个内置 skill 全部以 SKILL.md packages 形式 ship 出。这是方向调整,不是补丁。

## What Changes

- **删除** `src/writer/skills/{outline,toc,continue_writing,revise}.py`(4 个 Python class 实现)。**BREAKING**——任何依赖这些 class 名字的代码路径都要改。
- **删除** `src/writer/skills/loader.py`(Python importlib 加载器)和 `src/writer/skills/builtin_sources.py`(mirror 元组)。不再需要 Python 加载逻辑。
- **新增** `src/writer/skills/shipped/{大纲,目录,续写,改}/SKILL.md` 4 个内置 skill 包;每个含 `references/` 子目录(模板/示例/规范)+ `scripts/` 子目录(可选,辅助脚本,如 `format_outline.py`)。
- **新增** `src/writer/skills/directive.py`:`SkillDirective` Protocol + `MarkdownDirective` 实现。`MarkdownDirective` 在加载时读 `<command>/SKILL.md` 的 YAML frontmatter 提元数据,body + references 内容作为 `body` 字段缓存。`ScriptDirective` (备选) 支持 `scripts/` 里直接挂 Python 脚本(给愿意写脚本的用户用)。
- **修改** `src/writer/skills/registry.py`:把 `SkillRegistry` 改名为 `DirectiveRegistry`(语义对齐);内部存储 `SkillDirective` 而不是 `Skill`。`commands()` / `help_entries()` / `state_matrix()` 接口形状不变,只是底层类型换了。
- **新增** `src/writer/skills/discovery.py`:`discover_directives(project_root: Path) -> list[SkillDirective]`。扫 `<project_root>/.writer/skills/*/SKILL.md` 目录布局;YAML frontmatter 用 `python-frontmatter` 或手写小解析器(避免新依赖)。
- **修改** `src/writer/project/workspace.py`:`_writer_meta_scaffolding` 不再 mirror .py/.md,而是 ship 4 个 SKILL.md packages 到 `<root>/.writer/skills/{大纲,目录,续写,改}/`(每个目录含 SKILL.md + 内置 references/ + scripts/ 模板)。`_seed_skill_mirrors` 改名 `_seed_skill_directives`。
- **修改** `src/writer/engine/loop.py`:在 `case "run_command"` 分支新增 directive dispatch——识别 action.command 命中 `DirectiveRegistry` 时,把 directive.body + references 内容注入 system message(通过 `EngineContext` 扩展或新 helper),然后走正常 LLM 流程(让 LLM 用 tools 完成工作)。Python `Skill` 分支保留作为"高级用户可挂 Python directive 的 escape hatch"。
- **修改** `src/writer/session/engine_session.py` / `src/writer/engine/deps.py`:`rebind_skill_registry` 改名为 `rebind_directive_registry`,`skill_registry` 字段名改 `directive_registry`。**BREAKING**——任何外部 stub / fake `EngineDeps` 实现都要改字段名。
- **删除** `extra_instructions: str` Protocol 字段(原来的混合方案需要,纯 Markdown 方案不需要——body 已经在 directive.body 里)。
- **修改** 测试:删除 `test_skill_loader.py` / `test_skill_registry.py`(Python 加载器相关),新建 `test_directive_discovery.py` / `test_directive_dispatch.py`(Markdown 加载 + engine 分发)。

## Capabilities

### New Capabilities

- `skill-directives`: 纯 Markdown SKILL.md skill 范式——`<command>/SKILL.md` 目录布局 + YAML frontmatter 元数据 + body/references/scripts 内容;LLM-driven dispatch;engine 把 directive 注入 system prompt。这是**新 capability**,完全替代之前的 `project-skills`(Python+Markdown 混合)。
- `shipped-skills`: 4 个内置 skill packages,以 SKILL.md + references/ + scripts/ 形式 ship 在 `src/writer/skills/shipped/`。是 `skill-directives` 的一个子特性(shipped set 的发现机制)。

### Modified Capabilities

无现有 spec 需要修改——之前的 `project-skills` spec(在 `chg-project-skills/specs/` 里)从未 sync 到 main,所以 main specs 仍然干净。

## Impact

**影响文件**(src ~14 + test ~6):
- `src/writer/skills/{outline,toc,continue_writing,revise}.py`(**删除**)
- `src/writer/skills/loader.py`(**删除**)
- `src/writer/skills/builtin_sources.py`(**删除**)
- `src/writer/skills/protocol.py`(改:`Skill` Protocol 改名 `SkillDirective`,删 `extra_instructions` 字段,加 `body/references/scripts` 字段)
- `src/writer/skills/registry.py`(改:`SkillRegistry` → `DirectiveRegistry`,改 dict value 类型)
- `src/writer/skills/__init__.py`(re-export 改名)
- `src/writer/skills/discovery.py`(**新增**):`MarkdownDirective` class + `discover_directives(project_root)`
- `src/writer/skills/shipped/{大纲,目录,续写,改}/SKILL.md`(**新增 4 个**)
- `src/writer/skills/shipped/{...}/references/*.md`(**新增**:每 skill 2-3 个 reference)
- `src/writer/skills/shipped/{...}/scripts/*.py`(**新增**:每 skill 0-1 个辅助脚本,可选)
- `src/writer/project/workspace.py`(改:`_writer_meta_scaffolding` 走 ship 目录布局)
- `src/writer/engine/loop.py`(改:`case "run_command"` 加 directive 分支)
- `src/writer/engine/deps.py`(改:`skill_registry` → `directive_registry`,`rebind_skill_registry` → `rebind_directive_registry`)
- `src/writer/session/engine_session.py`(改:set_project_root 重建 directive_registry)
- `src/writer/cli/main.py`(改:`build_repl_commands` / `print_repl_help` 调 directive_registry 接口)
- `tests/test_skill_loader.py`(**删除**)
- `tests/test_skill_registry.py`(**改名** `test_directive_registry.py`,内容重写)
- `tests/test_directive_dispatch.py`(**新增**):engine loop directive 分发测试
- `tests/test_engine_session.py`(改:PlainDeps stub 字段名 `directive_registry` + `rebind_directive_registry`)
- `tests/test_engine_deps.py`(改:断言 `directive_registry` 字段)
- `tests/test_tools.py`(删 `ForeshadowQuery` 相关,加 `ForeshadowSearch` 验证——这个上一轮已做)
- `tests/test_engine.py`(改:dispatch 路径测试改 directive 形式)

**不动的部分**(架构稳定区):
- LLM 工具循环(`LLMToolLoop`)
- router 路由规则
- 4 个内置 tool(foreshadow_search / project_search / wordcount / safe_read_file / safe_list_dir / chapter_locate)
- `EngineContext` 输入契约
- `EngineConfig` / `EngineDeps.route` / `run_workflow`
- `safe_path()` / `ToolRuntime`
- `chapter_summaries.json` 已有 schema
- 4 层架构 + 兼容层

**迁移路径**:
- 旧 `Skill` Python class 的下游用户(如有):需要改用 `SkillDirective` 抽象;但本项目所有 skill 实现都是内置的,无外部用户。
- 旧 fake `EngineDeps` stub:`skill_registry` 字段改名为 `directive_registry`,`rebind_skill_registry` 改名为 `rebind_directive_registry`。
- 已存在的项目 `.writer/skills/*.py` mirror 文件:不再被加载;apply 后用户需要 `writer new` 重新生成 SKILL.md packages(或自己写)。

**风险**:
- High:**核心架构变更**——dispatch 从 Python async generator 改为 LLM directive injection。这影响 engine loop、LLM tool loop 集成、ToolResult → Done 事件流。需要细致的 acceptance test。
- Medium:**失去 Python 单测覆盖**——4 个内置 skill 的 Python 行为没有单测保护,LLM-driven dispatch 的正确性靠 end-to-end 测试覆盖。
- Medium:中文目录名作为 filesystem path——和 `chg-project-skills` 同样的边界已验证 OK。
- Low:`rebind_skill_registry` 改名打破现有 fake `EngineDeps` stub(已在 `chg-project-skills` apply 期间补过 `rebind_skill_registry`,apply 时再补 `rebind_directive_registry` 即可)。

## Open Questions (已确认 2026-07-09)

1. **`scripts/` 作用**——scripts 仅供 LLM 参考(SKILL.md 里说"参考 scripts/format_outline.py"),不注册为 tool。LLM 想跑时用 Bash tool 调,`safe_path()` 继续兜底。
2. **`SkillDirective.body` 结构**——作为单 string 整体发,不做 section 预解析。
3. **`references/` 发送策略**——按需检索:SKILL.md body 里支持 `@reference path/to/file.md` 语法,engine 解析后只把被引用的文件内容塞进 LLM context。Unreferenced 文件不发送。
4. **shipped skills 路径**——package 内部用 `src/writer/skills/_shipped/`(下划线开头标记私有,仅作 packaging 用途);项目级一律 `.writer/skills/<command>/SKILL.md`。`create_new_workspace` 从 `_shipped` 拷贝到 `.writer/skills/` 后,**shipped 与用户自加不可区分**——用户可自由编辑/删除原 shipped 内容。