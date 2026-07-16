## Why

真实写作流是递归回流的:S4 作者回头改大纲(`S4 → S2`)、加新卷(`S4 → S3`)、回看大纲(`S5 → view`)。但本项目命令拦截用的是 `requires_states: frozenset[ProjectState]` hard wall,把合法的回流操作全数拦死。

更糟的是:**项目自己的设计文档(`docs/命令与用户流程.md:233-247` 第 5.2 节)和实现不一致**。文档承诺 `△¹ / △² / △³` 的"软确认"语义(`rewrite / view / 默认只写当前卷`),但代码层只实现了"硬拒绝"。三个真实反例:

1. **S4 作者回头改大纲**:`/大纲 补充第 5 章伏笔` 被 `requires_states: [INITIALIZED, HAS_OUTLINE]` 拦死,但 `_shipped/大纲/SKILL.md` body 第 26-37 行已经写好"读现有 outline/大纲.md → 检测追加 vs 覆盖"的完整逻辑——意图永远进不去 SKILL.md body。
2. **S4 作者加新卷**:`/目录 把反派觉醒卷加入` 被 `requires_states: [HAS_OUTLINE, HAS_TOC]` 拦死,但 SKILL.md body 第 26 行明确处理"已有 toc.md 时"的场景。
3. **S5 作者看大纲**:`/大纲 view` 被拦死,但 SKILL.md description 第一行就是"生成或查看大纲",明确支持 view 模式。

**结论**:命令可用性的拦截机制**本身**与真实写作流冲突,且 SKILL.md body 已经具备判断"已存在 vs 新建"的能力。让 LLM 在 directive body 内部处理这类判断,远比 Python 层硬墙更贴近用户实际意图。

`detect_state` / `inspect_project` / `STATE_DESCRIPTIONS` 本身**保留**给 `/状态` 显示用——状态标签是 UX 资产,不是拦截武器。

## What Changes

- **删除** `src/writer/project/state.py` 的拦截相关符号:
  - `COMMAND_ALLOWED` 静态表 (lines 72-86)
  - `COMMAND_HINTS` 字典 (lines 88-96)
  - `CommandCheck` dataclass (lines 42-49)
  - `validate_command_available()` 函数 (lines 195-247)
  - `SkillRegistryView` Protocol (lines 250-261)
  - `_skill_hint()` 函数 (lines 264-275)
- **删除** `SkillDirective` 上的 `requires_states: frozenset[ProjectState]` 字段(`src/writer/skills/protocol.py:62`)。
- **删除** `DirectiveRegistry._validate()` 中 requires_states 校验块(`src/writer/skills/registry.py:60-68`)。
- **删除** `DirectiveRegistry.state_matrix()` 方法(`src/writer/skills/registry.py:121-129`)。
- **删除** `_resolve_requires_states()` 解析函数(`src/writer/skills/directive_discovery.py:~345-385`)以及 meta dict 里的 `requires_states` 字段构造(lines 244, 299)和 directive 校验(lines 398-399)。
- **删除** `engine/loop.py:_engine_loop` 中 `validate_command_available()` 拦截块(lines 124-140)。
- **删除** shipped SKILL.md frontmatter 中的 `requires_states:` 行:
  - `src/writer/skills/_shipped/大纲/SKILL.md` line 4
  - `src/writer/skills/_shipped/目录/SKILL.md` line 4

**保留**(只用于 `/状态` 显示):
- `ProjectState` enum(展示用,S0-S5 标签)
- `STATE_DESCRIPTIONS` 字典
- `detect_state()` / `inspect_project()` / `ProjectSnapshot`
- `find_outline_path()` / `discover_project_root()` / `count_chapters()` / `safe_cwd()`
- `render_agent_file()` / `refresh_agent_file()` / `append_agent_requirements()` / `read_genre_from_agent()`
- `CURRENT_STATE_SECTION_HEADER`
- `AGENT.md` 里 `state: S1` 字段继续写入

**不动**(独立于本 change):
- `EngineContext.project_state: str` 字段(独立的"缓存字段冗余"重构,可后续 change)
- `EngineSession.project_state: str`
- `IntentRouter.route()` 第二个 `project_state` 参数(LLM 路由器仍在 prompt 里用)
- `LlmIntentRouter` 的 prompt 模板里的 `项目状态: {project_state}` 行
- `Done(aborted, payload={"project_state": ...})` 在 init flow 的发出(`_maybe_run_init_brief_or_block` / `_run_init_command` / `_run_init_brief_command` 三处的诊断信息)

## Capabilities

### New Capabilities

无。这是纯删除。

### Modified Capabilities

- **`shipped-skills`**: 删除"requires_states 是 frontmatter 必填字段"的契约;`大纲/SKILL.md` 和 `目录/SKILL.md` 不再写 `requires_states`。
- **`skill-directives`**: 删除 `SkillDirective.requires_states` 字段及其校验场景;`DirectiveRegistry.state_matrix()` 方法删除;`discover_directives` 的失败模式列表里去掉"`requires_states` 有未知 ProjectState 值"这一条。

**不修改**:
- `engine-loop`: 不涉及——`validate_command_available` 是实现细节,该 spec 当前未规定命令拦截语义。
- `intent-routing`: 不涉及——`project_state` 参数保留,`state_matrix` 是注册表查询而非路由决策。

## Impact

**影响文件**(src 5 + test 4 + spec 2 + docs 1):
- `src/writer/project/state.py`(删 ~100 行拦截代码,保留展示 helper)
- `src/writer/skills/protocol.py`(删 `requires_states` 字段)
- `src/writer/skills/registry.py`(删 `_validate` 中 requires_states 块 + `state_matrix()` 方法)
- `src/writer/skills/directive_discovery.py`(删 `_resolve_requires_states()` + 2 处 meta 字段构造 + 1 处校验)
- `src/writer/engine/loop.py`(删 lines 124-140 拦截块 + 关联 import)
- `src/writer/skills/_shipped/大纲/SKILL.md`(frontmatter 删 1 行)
- `src/writer/skills/_shipped/目录/SKILL.md`(frontmatter 删 1 行)
- `tests/test_project_state.py`(删 `validate_command_available` 相关 case)
- `tests/test_directive_dispatch.py`(删 `state_matrix` 相关 case)
- `tests/test_directive_registry.py`(删 `requires_states` 校验相关 case)
- `tests/test_directive_discovery.py`(删 `_resolve_requires_states` 相关 case)
- 新增测试:`/大纲` 在 S4 项目下可正常执行(view 模式 + 追加模式);`/目录` 在 S4 项目下可正常加新卷
- `openspec/specs/shipped-skills/spec.md`(改 ~6 行)
- `openspec/specs/skill-directives/spec.md`(改 ~10 行)
- `docs/命令与用户流程.md`(第 5.2 节"命令 × 状态矩阵"表删除 △¹/△²/△³ 说明,改为说明"无命令拦截,语义判断下沉到 SKILL.md body")

**不动的部分**(架构稳定区):
- LLM 工具循环(`LLMToolLoop`)
- 4 个 router 实现(`RuleBasedIntentRouter` / `LlmIntentRouter` / `CompositeRouter` / router Protocol)— `project_state` 参数仍保留
- `EngineContext.project_state: str` 字段
- `EngineSession.project_state: str` + `refresh_project_state()`
- `EngineDeps.route()` 协议
- 9 个 builtin tools
- chapter 工作流(`write_chapter` / `review_chapter`)
- `safe_path()` / `ToolRuntime`
- 4 层架构 + 兼容层
- `AGENT.md` 渲染函数族(`render_agent_file` / `refresh_agent_file` 等)— state 字段继续写入

**迁移路径**:
- 旧 `validate_command_available` 的下游用户:不存在。`COMMAND_ALLOWED` / `COMMAND_HINTS` / `validate_command_available` / `CommandCheck` / `SkillRegistryView` 都是项目内部符号,无外部消费者。
- 旧 `DirectiveRegistry.state_matrix()` 的下游用户:不存在。同上,只有内部 `validate_command_available` 用。
- 旧 `SkillDirective.requires_states` 字段的下游用户:不存在。fake / stub `DirectiveRegistry` 实现(`tests/test_*.py`)需要把 `requires_states` 字段从构造参数移除(机械改动)。
- 已存在的项目 `.writer/skills/<command>/SKILL.md` 不受影响:frontmatter 多余的 `requires_states` 行只是被 loader 忽略——但**为了干净**,apply 阶段会一并清理 `_shipped/` 下 2 个 SKILL.md;用户项目级副本若仍有此行也只是被忽略,不报错。

**风险**:
- **Low**:`SkillDirective` 删字段会破坏所有手写 stub——apply 时全量 grep 补删(预计 ~8 处 fake)。
- **Low**:`engine/loop.py` 删 ~17 行拦截块——需要确认没有其他路径隐式依赖 `Done(aborted, payload={"project_state": ...})` 中的 `project_state` 键。apply 时 grep 渲染侧(`cli/main.py:303-313`, `cli/repl.py:303-313`)确认。
- **Low**:`/大纲` / `/目录` 在 S4 项目下行为变化——从"被拦死"变成"进入 SKILL.md body 由 LLM 处理"。SKILL.md body 已经有"读现有文件 → 判断追加 vs 覆盖"逻辑,LLM 在 S4 项目下会进入"补充/扩展"语义而非"全量新建"。需要新增测试覆盖这个 case。
- **Low**:`AGENT.md` 的 `state: S1` 字段继续写,但 state 字段对 LLM 已无拦截意义——保留仅作为 `/状态` 显示数据源。
- **Medium(可接受)**:**失去"误打命令"的安全网**——例如 S0 用户打字 `/创作 第 1 章`,过去会被拦截提示"请先 /init",现在直接进入 LLM 工具循环,LLM 会因 `ToolRuntime.project_root = sentinel` 返回 `no_project_root` 错误——这是工具层的兜底,**行为正确但 UX 不如显式拦截**。评估认为可接受:这个 case 在真实写作流程中极少出现(用户已经走到 /创作 阶段基本都已绑定项目);若未来需要回归拦截,可以加 warning 级的软提示(`/状态` 给出来),不是 hard wall。