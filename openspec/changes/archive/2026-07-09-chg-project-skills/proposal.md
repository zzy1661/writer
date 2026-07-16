## Why

`writer new` / `/init` 生成的 `.writer/skills/` 目录目前只放一个空 `.gitkeep`（`src/writer/project/workspace.py:163`）。`src/writer/skills/` 里的 4 个内置 skill（`/大纲` `/目录` `/续写` `/改`）是写死在 Python 包里的 `Skill` Protocol 实现，用户既看不到、也改不动、也加不了自己的 skill。CLI help 文本 / REPL 补全 / 状态机拦截三个下游全部从 `SkillRegistry` 派生——但 registry 永远是包里那 4 个的固定快照。Claude Code 把 skill 设为"用户可见、可改、可加"的一等公民（`~/.claude/skills/<name>/SKILL.md`），本项目应把同样的范式搬到 `<project>/.writer/skills/`。

## What Changes

- **新增** `discover_project_skills(project_root) -> list[Skill]`：`src/writer/skills/loader.py` 新模块；扫 `<project_root>/.writer/skills/*.py`，用 `importlib.util.spec_from_file_location` 动态加载；对每个模块查找 `Skill` 实例或类（无参构造），失败一律 `log.warning` 跳过。**同时** 读同名 `<command>.md` 注入新 `extra_instructions: str` 字段。
- **扩展** `Skill` Protocol：新增 `extra_instructions: str = ""` 可选字段（`src/writer/skills/protocol.py`）。零侵入：所有 4 个内置 skill 保持原状（自动 default），项目级 .py 显式赋值时启用。
- **扩展** `SkillRegistry.__init__`：新增 keyword-only `extra_skills`（已有）语义不变；新增工厂函数 `built_skill_registry(project_root: Path | None = None)` 把"built-in + project + entry-point"三层合并按"后注册赢"（Replace 语义）装配。**BREAKING**：旧 `built_skill_registry()` 无参签名变成 deprecated 但兼容；新增 `project_root` 参数。
- **扩展** `EngineDeps` Protocol：新增 `skill_registry: SkillRegistry` 已有字段（`engine/deps.py:106`）保持；新增 `rebind_skill_registry(new: SkillRegistry) -> EngineDeps`（与已有的 `rebind_tool_runtime` / `rebind_story_consultant` 对称）。
- **扩展** `EngineSession.set_project_root()`：在 `tool_runtime` / `story_consultant` 重建之后，**也**调 `built_skill_registry(new_root)` 重建 `skill_registry`，并 `self.deps = self.deps.rebind_skill_registry(new)`。
- **扩展** `create_workspace` / `create_new_workspace`（`src/writer/project/workspace.py`）：在 `_writer_meta_scaffolding` 里 mirror 4 个内置 skill 的 Python 源到 `<root>/.writer/skills/<command>.py`（中文命令名作文件名）+ 同名 `<command>.md`（用途 + 调点说明）。**BREAKING**（行为变更）：`create_new_workspace` 现在会向磁盘写 4 个 Python + 4 个 Markdown 文件，磁盘占用从 ~1KB 涨到 ~12KB。
- **不动**：engine loop dispatch（仍 `deps.skill_registry.get(action.command)`）、router 路由规则、LLM 工具循环、4 个内置 skill 的 Python 实现（mirror 是 copy 不是 refactor）、`discover_entry_point_skills` 路径。

## Capabilities

### New Capabilities

- `project-skills`: 项目级 skill 加载器 + workspace 镜像 + session 重建接线。是新的 capability：引入新文件格式（`.writer/skills/<command>.py` + `<command>.md`）、新加载机制（动态 importlib）、新注入路径（session.set_project_root）、新 Protocol 字段（`extra_instructions`）。

### Modified Capabilities

无。现有 5 个 main spec（`engine-loop` / `engine-session` / `genre-init` / `intent-routing` / `llm-provider`）都不涉及 skill 行为契约；skill 系统在 spec 层面是首次出现。

## Impact

**影响文件**（src ~10 + test ~5 + spec 新增 1）：
- `src/writer/skills/loader.py`（新增 ~120 行）
- `src/writer/skills/protocol.py`（加 `extra_instructions` 字段，1 行 + 文档）
- `src/writer/skills/__init__.py`（re-export `discover_project_skills` + 镜像资源）
- `src/writer/skills/registry.py`（`built_skill_registry` 加 `project_root` 参数）
- `src/writer/skills/builtin_sources.py`（新增 ~10 行：列出 4 个内置 skill 的 `(class, mirror_filename, doc_path)` 元组）
- `src/writer/engine/deps.py`（`EngineDeps` Protocol 加 `rebind_skill_registry`；`production_deps` 不变，靠 `__post_init__` 间接传 `project_root`）
- `src/writer/session/engine_session.py`（`set_project_root` 重建 `skill_registry`）
- `src/writer/project/workspace.py`（`_writer_meta_scaffolding` 写 4 个 .py + 4 个 .md）
- `tests/test_skill_loader.py`（新增 ~10 case）
- `tests/test_workspace.py`（扩展 4 case：mirror 内容）
- `tests/test_skill_dispatch.py`（扩展 2 case：项目级 skill 走 engine loop）
- `tests/test_engine_session.py`（扩展 2 case：set_project_root 触发 skill_registry 重建）
- `tests/test_skills.py`（扩展 1 case：`extra_instructions` Protocol 默认空串）
- `openspec/specs/project-skills/spec.md`（新增 ~80 行）

**不动的部分**（架构稳定区）：
- `Skill` Protocol 的 `command` / `description` / `requires_states`（保持原状）
- engine loop dispatch / `EngineDeps.route` / `EngineDeps.run_workflow`
- 4 个内置 skill 的实现代码（mirror 是 1:1 copy + header 注释）
- `safe_path()` / `ToolRuntime` / tool 加载
- entry-point plugin 路径（保持第 3 层）
- `LangChain` / LLM Provider / chapter 工作流

**迁移路径**：
- 旧项目（无 `.writer/skills/` 内容）：自动行为——`discover_project_skills` 扫到空目录返回 `[]`；下次 `writer new` 时不强制迁移（用户主动 `/init` 升级才会 mirror）
- 现有 27 个 `tests/` 文件不依赖 `.writer/skills/`（除 `test_workspace.py` 的 3 个 case 测空目录生成）—— apply 后这些 case 仍 pass（mirror 在 `create_new_workspace` 才触发，旧的 `create_workspace` 不动）
- 旧 `built_skill_registry()` 无参调用方：保持兼容（`project_root` 默认 `None`，等同于旧行为）

**风险**：
- Medium：动态加载项目级 .py 等于把"项目目录里的代码"放进运行时，需要在 `discover_project_skills` 里加"只读纯 Python + 显式白名单允许的导入"的轻量安全护栏（详见 design.md Risks 段）
- Low：`extra_instructions` 是 Protocol 新字段，理论上下游 fake `Skill` 实现要补默认值；apply 时全量 grep 补 `= ""`
- Low：4 个内置 skill 的 mirror 文本与原文件漂移问题——apply 阶段 freeze mirror 文本，**未来内置 skill 升级**时不强制同步（用户主动 `writer init --upgrade-skills` 才会重新 mirror；本期不实现升级命令，留作 follow-up）
