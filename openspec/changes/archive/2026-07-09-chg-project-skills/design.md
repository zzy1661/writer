## Context

`writer new` / `/init` 生成的 `<project>/.writer/` 目录目前只放 3 个空 stub（`skills/.gitkeep` / `agents/.gitkeep` / `config`），见 `src/writer/project/workspace.py:160-173`。`src/writer/skills/` 里的 4 个内置 skill（`OutlineSkill` / `TocSkill` / `ContinueWritingSkill` / `ReviseSkill`）作为 Python 类硬编码在包里，组装进 `BUILTIN_SKILLS` 列表（`src/writer/skills/registry.py:62-67`）——`built_skill_registry()` 只能从两层拿 skill：(1) 这 4 个 hardcoded，(2) `importlib.metadata.entry_points(group="writer.skills")` 发现的已安装 Python 包。

CLI help 文本 / REPL tab 补全 / 状态机拦截三个下游都从 `SkillRegistry` 派生，所以"用户可改 / 可加"在当前架构下只能通过"装一个 Python 包"这条路径——对单个长篇项目来说太重。Claude Code 范式（`~/.claude/skills/<name>/SKILL.md` 文件系统级）是用户最熟悉的 mental model，本项目应把同样的范式搬到 `<project>/.writer/skills/`。

## Goals / Non-Goals

**Goals:**
- 把项目级 `.writer/skills/` 提升为 skill 的"主场"：用户可见、可改、可加
- 保留现有 4 个内置 skill 的 Python 实现（mirror 是 1:1 copy + header 注释）
- 加载顺序按 `built-in < project < entry-point` 的"后注册赢"（Replace 语义）装配
- 项目级 skill 可附同名 `.md` 注入 LLM 补充指令（通过 Protocol 新字段 `extra_instructions: str`）
- 失败模式对齐 `discover_entry_point_skills`：语法错 / 协议不符 → `log.warning` + 跳过，**不阻断 REPL 启动**
- 不动 engine loop dispatch / router / LLM 工具循环

**Non-Goals:**
- 不做 SKILL.md 纯 Markdown skill（保留 Python 镜像——见 Decision 1）
- 不做 hot-reload（项目级 skill 改动需重启 REPL 才生效）
- 不做 `writer init --upgrade-skills` 内置升级同步命令（留作 follow-up）
- 不做项目级 skill 的命令行安装器（用户手动编辑 .py）
- 不做签名 / 校验（项目目录是受信任的用户空间）

## Decisions

### 1. Skill 格式 = Python 镜像 + Markdown 附文

**决定**：每个项目级 skill 是一个 **`.py` 主文件**（执行体）+ 同名 **`.md` 附文**（用户文档 + 可选 LLM 补充指令）。

**理由**：
- 4 个内置 skill 有真实 Python 代码（`draft_outline` / `find_outline_path` / `write_text` / async generator），换成纯 Markdown 会让 200+ 行 typed 代码退化为不可测试的 LLM prompt
- Python 镜像保持 typed `Skill` Protocol / `EngineDeps` / `ProjectState` 集成；现有 322 个测试不受影响
- `.md` 副产物承担 Claude Code 范式中"用户可读文档"的角色，并可选地被注入 LLM 上下文

**替代方案 A**（纯 Markdown SKILL.md）：4 个内置 skill 全部重写，~300 行 typed Python 退化为 LLM 指令；失去 unit test 覆盖。**否决**。

**替代方案 B**（纯 .py 不要 .md）：用户改完代码后没有任何文档说"这 skill 是干嘛的"。**否决**。

### 2. 加载机制 = importlib.util 动态加载

**决定**：`discover_project_skills(project_root)` 用 `importlib.util.spec_from_file_location("user_skill_<basename>", path)` + `module_from_spec` + `loader.exec_module(module)` 动态加载；对每个模块查找 `Skill` 实例（顶层 `MySkill` 变量）或类（顶层 `MySkill` 类，no-arg construct）。

**理由**：
- 与 entry-point plugin 路径对称（都是动态加载 + `log.warning` 容错）
- 触发用户的 `import` 语句时自动 `sys.modules["user_skill_<basename>"]` 缓存，不会重复加载
- 失败处理：语法错 / ImportError / AttributeError / `_validate_skill` 抛 `SkillError` 一律 `log.warning` + 跳过；REPL 不崩

**替代方案**（exec() 字符串）：无 sys.modules 缓存，重复 REPL turn 会反复加载。**否决**。

### 3. 文件名 = 命令名（中文保留）

**决定**：`<project>/.writer/skills/大纲.py` + `大纲.md`；中文命令名直接当文件名（与 `创意/核心创意.md` 等项目既有中文命名一致）。

**理由**：与 `workspace.py:104-118` 的 `outline/premise.md` 风格一致；Windows / macOS / Linux 文件系统都支持 Unicode 文件名。

**替代方案**（slug 化文件名 `da-gang.py` + 命令元数据）：增加一次 name → command 映射；用户改命令名要改两处。**否决**。

### 4. Mirror 文本 = 1:1 copy + header

**决定**：`<project>/.writer/skills/大纲.py` 内容 = `src/writer/skills/outline.py` 全文 + 顶部 30 行注释说明"项目级 override / 改动建议 / 与内置版的关系"。

**理由**：
- 用户拿到文件后能直接改（不需要先 import 理解）
- header 注释明确标注"这是 mirror；内置升级时不会自动同步"——避免用户误以为改完就永久生效

**实现细节**（apply 阶段）：
- `src/writer/skills/builtin_sources.py` 维护一个元组列表 `[(mirror_filename, source_path, doc_path), ...]`
- `_writer_meta_scaffolding` 在 `create_new_workspace` 时遍历这个列表，`source_path.read_text()` 后拼 header 写到目标 `mirror_filename`
- header 文本 hardcode 在 `builtin_sources.py` 里（不是模板文件，避免路径解析问题）

### 5. extra_instructions 注入路径

**决定**：项目级 skill 加载时，若同名 `<command>.md` 存在，把 `file.read_text(encoding="utf-8")` 整体塞进 `skill.extra_instructions` 字符串字段。

**理由**：
- `Skill` Protocol 加 `extra_instructions: str = ""` 字段；4 个内置 skill 留空（不需要改）
- 未来 LLM-backed skill（如 `ContinueWritingSkill` 真接 LLM 时）可把 `extra_instructions` 注入 system prompt；本期不强制使用（apply 后只读，不消费）

**替代方案**（独立 `SkillContext.extra_instructions` 属性，不进 Protocol）：消费方需要先看 context 再看 skill，割裂。**否决**。

### 6. EngineSession 重建接线

**决定**：扩展 `EngineSession.set_project_root()`，在 `rebind_tool_runtime` + `rebind_story_consultant` 之后**也**调 `built_skill_registry(new_root)` 重建 `skill_registry`，再 `self.deps = self.deps.rebind_skill_registry(new)`。

**理由**：
- 与现有 `rebind_tool_runtime` / `rebind_story_consultant` 模式完全对称
- `EngineDeps` Protocol 加 `rebind_skill_registry` 一行（与 m18 后的 symmetric 模式一致）
- 同 `project_root` 不变时（`if new_root == self.project_root: return`）不重建（保持现有 no-op 语义）

### 7. builtin_skill_registry 装配顺序

**决定**：`SkillRegistry` 构造时把 `BUILTIN_SKILLS` + `discover_project_skills(project_root)` + `discover_entry_point_skills()` 三层依次 extend 到 `items`，由 `SkillRegistry.__init__` 现有的"重复命令 raise"机制保证 project 赢 built-in（重复则 raise → 实际上需要变更：见 Decision 8）。

### 8. 加载顺序：把"重复 raise"改为"后注册赢"（Replace 语义）

**决定**：扩展 `SkillRegistry.__init__`：当 `items` 中出现重复 `command` 时，**后注册的覆盖先注册的**（dict-based 替换），而不是当前 raise `SkillError`。

**理由**：
- 当前的 raise 语义是"用户配置错误"，但 project-level skill 故意可能与 built-in 重名（mirror 内置版就是要覆盖）
- entry-point plugin 也可能故意覆盖 built-in（escape hatch）
- 三个 layer 都有"覆盖上一层"的合法场景

**兼容性影响**：
- `_validate_skill` 仍保留（必填字段必须存在）
- 唯一的语义变化：`SkillRegistry(["/大纲", OutlineSkill, "/大纲", CustomOutlineSkill])` 不再 raise，后者赢
- 测试 `tests/test_skill_registry.py::test_duplicate_commands_raise` 需要重写为 `test_later_wins_over_earlier`（apply 阶段修）

**替代方案**（保留 raise，单独加一个 `replace_duplicates=True` flag）：增加 API 表面。**否决**——Replace 是本次的核心决策，flag 化反而需要每个 caller 显式传，麻烦。

## Risks / Trade-offs

[项目级 .py 等于把"用户文件"放进运行时执行] → **Mitigation**：(1) `discover_project_skills` 在 `exec_module` 之前 `ast.parse(path.read_text())` 兜底语法错（但允许 import / 调用 `from writer.X import Y`）；(2) `log.warning` 含完整路径 + traceback，便于用户定位；(3) 文档明确说"项目目录是受信任的"——本项目不是多租户 SaaS，用户自己控制自己写的代码

[mirror 文本与内置版漂移] → **Mitigation**：本期不做自动同步；`builtin_sources.py` 元组里每条记录加 `frozen_sha: str` 注释（apply 阶段不写代码，只注释），未来 `writer init --upgrade-skills` 可基于 sha 检测漂移并提示

[Protocol 新字段 `extra_instructions` 破坏 fake Skill] → **Mitigation**：默认 `= ""`；`tests/test_skills.py` 和 `tests/test_skill_registry.py` 现有 fake skill 全部加 `extra_instructions = ""` 显式声明（apply 阶段 grep + 修）

[加载顺序变更破坏现有重复命令测试] → **Mitigation**：`tests/test_skill_registry.py` 的 `test_duplicate_commands_raise` 重写为 `test_later_wins_over_earlier`（按 Decision 8 改）；这是 spec 行为变更的一部分，archive 时通过 spec 同步

[workspace 镜像在 create_new_workspace 多写 8 个文件] → **Mitigation**：`_writer_meta_scaffolding` 用现有 `if force or not path.exists()` 模式；老项目升级时**不**自动补（用户主动调 `writer init <name> --force` 才会重新 mirror 完整版）

[中文文件名跨平台] → **Mitigation**：UTF-8 filesystem 标准在所有主流 OS 都支持；测试用 `tmp_path` (pytest 自动创建) 不会触发 OS 差异

## Migration Plan

**部署步骤**（apply 阶段按 `tasks.md` 顺序）：
1. 扩展 `Skill` Protocol 加 `extra_instructions` 字段
2. 新建 `loader.py` + `builtin_sources.py`
3. 改 `SkillRegistry.__init__` 为"后注册赢"
4. 改 `built_skill_registry` 加 `project_root` 参数
5. 改 `_writer_meta_scaffolding` mirror 4 个 skill
6. 改 `EngineDeps` Protocol 加 `rebind_skill_registry`
7. 改 `EngineSession.set_project_root` 重建 `skill_registry`
8. 改 `_DefaultEngineDeps` 加 `rebind_skill_registry` 实现
9. 跑测试；按需修 fake skill
10. `openspec validate` + archive

**回滚策略**：`git revert` 整个 commit。RAG-删除那次是纯减法，无数据迁移；本次涉及新文件生成（mirror），回滚后用户磁盘上的 `.writer/skills/*.py` 残留——用户手动 `rm -rf .writer/skills/` 即可。

**兼容窗口**：
- 旧 `built_skill_registry()` 无参调用方：仍兼容（`project_root=None` 等同旧行为）
- 旧 `SkillRegistry` 重复命令 raise 行为：**变更为后注册赢**——这是 breaking，但仅在 user 主动注册重复 command 时才触发（任何生产代码路径不会）
- 旧 fake `Skill` 测试：apply 阶段补 `extra_instructions = ""` 默认值

## Open Questions

1. **`extra_instructions` 是否需要在 LLM 路径消费？** — 倾向 NO（apply 阶段只读不消费），未来 LLM-backed skill（如 `/续写` 真接 LLM）时再注入。apply 阶段确认
2. **mirror 文件的 header 注释是否要包含内置版 sha？** — 倾向 YES（在 `builtin_sources.py` 元组里 hardcode sha256），方便未来检测漂移。apply 阶段确认是否需要写 sha 校验代码
3. **`writer new` 与 `writer init`（即 `create_new_workspace` 与 `create_workspace`）是否都加 mirror？** — 倾向只 `create_new_workspace` 加（旧 `create_workspace` 是底层 API，不应强行注入 skill 镜像）。apply 阶段确认
4. **项目级 skill 加载失败时是否在 REPL 启动时一次性显示所有错误？** — 倾向 NO（log.warning 已经够），避免启动噪音。apply 阶段确认
