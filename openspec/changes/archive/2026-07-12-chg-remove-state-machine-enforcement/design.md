## Context

本项目 `ProjectState` 状态机有两层用途,目前耦合在 `src/writer/project/state.py` 同一个模块里:

- **展示层**: `detect_state()` / `inspect_project()` / `STATE_DESCRIPTIONS` / `ProjectSnapshot` 给 `/状态` 命令、CLI 渲染、AGENT.md 写入用——`/状态` 显示当前在 S1 还是 S4 等。**这是 UX 资产,保留**。
- **拦截层**: `COMMAND_ALLOWED` / `validate_command_available()` / `SkillDirective.requires_states` / `DirectiveRegistry.state_matrix()` 给 engine 在每轮开头判断"这个命令现在能不能跑"。**这是 UX 障碍,删除**。

**核心张力**: `docs/命令与用户流程.md:233-247` 的"命令 × 状态矩阵"明确设计意图是 **软确认语义**(△¹=rewrite/view、△²=需确认、△³=默认只写当前卷),但 SKILL.md frontmatter 的 `requires_states` 是 **hard wall**——文档承诺的 UX 在实现里没落地。

**真实写作流的非递归性**: 长篇创作里,"写到第 8 章回头改大纲补伏笔"、"写到第 10 章发现要加新反派卷"、"审完第 1 卷回头看大纲"都是高频操作。这些都被 `requires_states` 拦死,而 SKILL.md body 本身(已检查 `_shipped/大纲/SKILL.md:26-37` 和 `_shipped/目录/SKILL.md:26`)已经写好"读现有文件 → 判断追加 vs 覆盖"逻辑——只是永远进不去。

**`_maybe_run_init_brief_or_block` 的 state 检查**(`engine/loop.py:296-311`)是一个独立的、`/init <brief>` 子命令的"S1-only"硬检查,不属于通用命令拦截。它**保留**:这是 `/init` 命令自己的业务规则(只有新建项目时才能填创意),不是状态机通用拦截。

**`Done(aborted, payload={"project_state": ...})` 在 init flow 的发出**(`loop.py:304-310`、`354`、`382` 三处)是 CLI 渲染"当前状态: S3(正文编辑中)"诊断信息的数据源。**保留**:与拦截机制解耦,只是 enum 值的字符串展示。

## Goals / Non-Goals

**Goals:**

- 删除项目状态机的命令拦截机制(`COMMAND_ALLOWED` + `validate_command_available` + `SkillDirective.requires_states` + `DirectiveRegistry.state_matrix`)
- 删除 shipped SKILL.md frontmatter 的 `requires_states:` 行,让 `/大纲` / `/目录` 在所有状态下都可调用
- 保留 `ProjectState` enum + `detect_state` + `STATE_DESCRIPTIONS` 等展示层符号,继续给 `/状态` 显示用
- 保留 `EngineContext.project_state` 字符串字段(独立的"缓存字段冗余"重构,后续 change)
- 保留 `IntentRouter.route()` 的 `project_state: str` 参数(LLM 路由器还在用)
- 让"已存在 vs 新建 / 追加 vs 覆盖"判断**完全下沉**到 SKILL.md body,由 LLM 在 directive 执行时根据实际文件状态自主判断

**Non-Goals:**

- 不删除 `ProjectState` enum 本身(展示用)
- 不删除 `EngineContext.project_state: str`(独立重构,可在后续 change 起)
- 不删除 `EngineSession.project_state: str` + `refresh_project_state()`
- 不删除 `LlmIntentRouter` 把 `project_state` 注入 prompt 的行为
- 不删除 init flow 三处 `payload={"project_state": ...}` 的诊断信息
- 不删除 `_maybe_run_init_brief_or_block` 里 `/init <brief>` 的 S1-only 检查(那是 `/init` 子命令的业务规则,不是通用拦截)
- 不实现"软确认 △¹ △² △³"(路径 B,需要 Interrupt + LLM 二次消费,复杂度高)
- 不实现"能力声明"(`ProjectCapabilities`,路径 C,工作量大)
- 不为用户已存在的 `.writer/skills/<command>/SKILL.md` 副本自动迁移 `requires_states` 行(若仍存在,只是被 loader 忽略,不报错)

## Decisions

### Decision 1: 把"已存在 vs 新建 / 追加 vs 覆盖"判断完全下沉到 SKILL.md body

**为什么**: shipped SKILL.md body 已经有完整逻辑:
- `_shipped/大纲/SKILL.md:26-27`: "用 `safe_read_file` 读取 `outline/premise.md` 和 `outline/volume-plan.md`(若存在)... 用 `safe_read_file` 读取当前 `outline/大纲.md`(若存在),检查是否要覆盖或追加。"
- `_shipped/目录/SKILL.md:26`: "基于大纲结构在 LLM 响应里**直接生成**章节目录"

LLM 完全有能力判断"用户说补充 / 续写 → 追加模式", "用户说重写 / rewrite → 覆盖模式"。Python 层拦截反而挡掉了用户的真实意图。

**替代方案**: 引入"软确认"机制(路径 B,Interrupt 流)——评估认为,对于 `/大纲 rewrite` 这类命令,LLM 在 directive body 内部直接读文件判断比走 Interrupt 流程更自然,后者会打断心流。

### Decision 2: 保留 `_maybe_run_init_brief_or_block` 的 S1-only 检查

**为什么**: `/init <brief>` 创意访谈是 `/init` 命令的子命令模式,业务规则是"只有新建项目时才能填创意"——这是 `/init` 命令**自己的**约束,不是通用"命令可用性矩阵"。它是 in-line check,不是 `validate_command_available` 拦截。

**保留位置**: `engine/loop.py:296-311` 整段保留(含 `detect_state(ctx.project_root) != ProjectState.INITIALIZED` 判断)。**不动**。

**替代方案**: 把 `/init brief` 也下沉到 SKILL.md body——评估认为不合适,因为这是命令**前置条件**而不是"已存在 vs 新建"的判断。S2+ 项目里 `/init 一些想法` 真的不该进入创意访谈流程(已经有大纲了)。

### Decision 3: 保留 init flow 三处 Done payload 的 `project_state` 键

**为什么**: `cli/repl.py:303-313` 和 `cli/main.py:303-313` 都依赖这个键渲染 `当前状态: S3(正文编辑中)` 诊断。这是 CLI 渲染契约的一部分,与拦截机制无关。

**保留位置**: `engine/loop.py:304-310` / `354` / `382` 三处 payload 构造**不动**。

**注意**: 这是 `ProjectState` enum 值的字符串表示,不是 `EngineContext.project_state` 字段(后者是另一回事)。本 change 让 `ProjectState` enum 继续存在,就是为了这些渲染键还能工作。

### Decision 4: `EngineContext.project_state: str` 字段独立处理

**为什么**: 该字段的实际消费者只剩两个:
- `LlmIntentRouter` 在 prompt 里把它作为 `{project_state}` 模板变量(意图路由决策)
- `IntentRouter.route()` Protocol 把它作为参数(其他实现可忽略,见 `intent_router.py:91` 的 `del project_state`)

`validate_command_available` 在 S0 路径下也读它作为输入(state.py:215 的 `_coerce_state(project_state)`)。但 validate_command_available **本 change 要删除**,所以该字段在 engine 拦截层的消费点一并消失。

LLM 路由器仍然是合法消费方。但**这个字段本身是不是冗余**、能不能让 LlmIntentRouter 从 `project_root` 内部 `detect_state`——这是另一个独立重构(可能要改 `IntentRouter` Protocol 签名)。

**本 change 处理**: 不动 `EngineContext.project_state` 字段。`LlmIntentRouter` 继续消费它。`validate_command_available` 删除后,S0 路径下没有代码再读这个字段——这意味着从 apply 起,`ctx.project_state` 在 S0 路径下**完全 dead**;在 S1+ 路径下被 LLM 路由器消费。**这不影响功能**,只是把"缓存字段冗余"的范围扩大了一点,留给后续 change 处理。

**替代方案**: 本 change 也删 `EngineContext.project_state` 字段——评估认为会让本 change scope 扩大,因为要改 `IntentRouter` Protocol + 3 个 router 实现 + ~25 个 test fixture + LlmIntentRouter 内部改为从 `project_root` 调 `detect_state`。**独立 change 更干净**。

### Decision 5: `AGENT.md` 的 `state: S1` 字段继续写入

**为什么**: `/状态` 命令依赖 `inspect_project()` 读 `AGENT.md` 拿 state 标签(`STATE_DESCRIPTIONS` 用 enum key 查中文标签)。**展示层完整保留**,意味着 `render_agent_file()` / `refresh_agent_file()` 继续写 `state:` 行。

**字段语义变化**: apply 后,`AGENT.md` 里的 `state: S1` 对 LLM 不再有"硬墙"含义——只是 `/状态` 显示用的数据源。LLM 不会被 engine 拦截,但 directive body 内的 LLM 仍然会读 `AGENT.md` 看到 `state:`,这只是上下文信息。

### Decision 6: 用户级 `.writer/skills/<command>/SKILL.md` 的 `requires_states` 行处理

**决定**: 不为用户的项目级副本自动迁移。`discover_directives()` 解析 frontmatter 时只读 `command` / `description` / `body` / `references` / `scripts` 等,多余的 `requires_states` 键会被 Python 忽略(`yaml.safe_load` 容错)。**apply 后即使 `requires_states:` 行还在,也只是无效字段,不报错**。

**apply 阶段清理范围**:
- `src/writer/skills/_shipped/大纲/SKILL.md` 和 `src/writer/skills/_shipped/目录/SKILL.md` frontmatter 的 `requires_states:` 行删掉
- `src/writer/skills/_shipped/` 下的镜像逻辑(如 `_seed_skill_mirrors` / `_render_skill_mirror` / `builtin_sources` 元组)同步删 `requires_states` 字段
- 用户项目级副本不动(那是用户的文件)

**迁移告知**: `docs/命令与用户流程.md:233-247` 第 5.2 节改为说明"无命令拦截,语义判断下沉到 SKILL.md body",并在备忘文件里追加"用户项目级 SKILL.md frontmatter 残留的 `requires_states:` 行无害,无需手动清理"。

### Decision 7: 测试 fixture 处理

**改动**:
- `tests/test_project_state.py`:`validate_command_available` / `COMMAND_ALLOWED` / `_skill_hint` 相关 case 全部删除(预计 ~15 case)
- `tests/test_directive_dispatch.py`:`state_matrix` 相关 case 删除(预计 ~3 case)
- `tests/test_directive_registry.py`:`requires_states` 校验失败相关 case 删除(预计 ~3 case)
- `tests/test_directive_discovery.py`:`_resolve_requires_states` / 未知 ProjectState 值 / 缺失 `requires_states` 相关 case 删除(预计 ~8 case)
- 新增 case:`/大纲` 在 S4 项目下可正常执行(模拟 SKILL.md body 读 `outline/大纲.md` 走追加模式)
- 新增 case:`/目录` 在 S4 项目下可正常加新卷(模拟 SKILL.md body 读 `toc.md` 走扩展模式)

**不动**:
- `tests/test_engine.py` / `tests/test_cli.py` / `tests/test_workflows_*.py` / `tests/test_prompts_router.py` 中 ~25 处 `project_state="S0"` fixture——这些是 `EngineContext` 字段的 stub,本 change 不动 `EngineContext.project_state`。等"缓存字段冗余"那个独立 change 再处理。
- `tests/test_routing_*.py` 中 router 测试的 `state="S0"` 等参数——继续有效。

### Decision 8: 不写 `OpenSpec change::skills-directive-requires-states-migration`

**为什么**: `requires_states` 是 skill frontmatter 字段,不是产品契约的 spec——它是项目内部 Python 层的硬墙机制。本 change 把它从 `SkillDirective` Protocol 字段中删除后,所有 spec 的"requires_states 是必填"要求一起失效,**不需要单独的 spec migration 文件**。`shipped-skills` 和 `skill-directives` 两个 spec 的修改以 delta 形式直接在该 spec 文件里改即可。

## Risks / Trade-offs

- [Risk] **失去"误打命令"的安全网** → [Mitigation] 工具层兜底——S0 用户跑 `/创作 第 1 章` 时,`ToolRuntime.project_root` 是 sentinel,工具返回 `metadata.error="no_project_root"`,LLM 在 directive body 内部会看到这个错并告诉用户。**行为正确,UX 不如显式拦截但可接受**;若未来想回归,可加 warning 级 `/状态` 软提示(非 hard wall)。

- [Risk] **`SkillDirective` 删字段破坏 fake stub** → [Mitigation] apply 阶段 grep `requires_states` 全量清理 fake / 测试 stub,预计 ~8 处机械改动。

- [Risk] **`/大纲` 在 S4 下行为从"被拦死"变成"LLM 处理"** → [Mitigation] 新增测试覆盖"读 `outline/大纲.md` 已存在 → 走追加模式"和"读 `toc.md` 已存在 → 走扩展模式"。SKILL.md body 的指令明确说了"已有 story premise 时优先复用",LLM 应当遵循。

- [Risk] **LLM 在 directive body 内部误判模式**(用户说"重写"但 LLM 走了"追加") → [Mitigation] 这是 LLM 本身的能力问题,不是拦截机制的回归——同样的 LLM 在其他场景(无拦截时)也会有这个问题。**不在本 change scope**;若 LLM 误判率上升,可在 directive body 加重写模式的精确规则。

- [Risk] **CLI 渲染依赖 `payload["project_state"]` 键**(`repl.py:303-313` / `main.py:303-313`)→ [Mitigation] 本 change 保留 init flow 三处 `project_state` 键(payload 来源仍存在),所以渲染契约不破。apply 阶段会 grep 验证"没有其他路径删了 `project_state` 键"。

- [Risk] **`discover_directives` 容错处理用户项目级 SKILL.md 残留 `requires_states:`** → [Mitigation] 已验证 `yaml.safe_load` 会把额外字段当 dict 项,不影响 `command` / `description` / `body` 解析。**无害残留,无需迁移**。

- [Risk] **`AGENT.md` 的 `state: S1` 对 LLM 不再有硬墙含义,只是显示数据** → [Mitigation] 这是显示层与拦截层解耦的副产物,符合本 change 目标——`ProjectState` 应该是 UX 资产而非拦截武器。在备忘文件 `技术难点与解决方案备忘/01-项目状态机与命令可用性.md` 里追加"apply 后状态机退化为展示层"的说明。

## Migration Plan

**应用步骤**(由 `tasks.md` 详细分解):
1. 删 `state.py` 拦截符号(`COMMAND_ALLOWED` / `COMMAND_HINTS` / `validate_command_available` / `SkillRegistryView` / `_skill_hint` / `CommandCheck`)
2. 删 `SkillDirective.requires_states` 字段 + `DirectiveRegistry` 相关方法
3. 删 `directive_discovery._resolve_requires_states` + meta 字段构造 + 校验
4. 删 `engine/loop.py:124-140` 拦截块 + 关联 import
5. 删 2 个 shipped SKILL.md frontmatter 的 `requires_states:` 行
6. 同步改 `_seed_skill_mirrors` / `_render_skill_mirror` / `builtin_sources` 元组(若涉及)
7. 删/改对应测试 fixture
8. 新增测试 case 覆盖"LLM 在 S4 下处理已存在文件"
9. 改 `docs/命令与用户流程.md:233-247` 第 5.2 节说明
10. 改备忘 `01-项目状态机与命令可用性.md` 追加"状态机退化为展示层"段

**回滚策略**: 由于本 change 是纯删除,回滚 = `git revert <commit>`。无数据迁移(磁盘文件无变更)。

**验证**:
- ruff + mypy clean
- pytest 全过(基线 339 → apply 后 ~310,删除 ~29 case)
- e2e:`printf "/大纲 补充伏笔\n" | .venv/bin/writer` 在 S4 项目(已有 `outline/大纲.md`)下正常进入 SKILL.md body,LLM 走追加模式
- e2e:`printf "/大纲\n" | .venv/bin/writer` 在 S0 项目下进入 LLM 工具循环,工具层兜底返回 `no_project_root` 错误
- `/状态` 显示照常工作(`inspect_project` 不变)

## Open Questions

1. **`AGENT.md` 的 `state:` 字段未来是否要加 `last_modified_at` 等元数据?** 这是独立需求,本 change 不引入。
2. **若用户希望看到"命令可用性软提示"(例如 S4 跑 `/大纲` 时提示"已检测到 outline,你想补充还是重写?"),是后续 change 路径 B 的范畴**——不在本 change scope。
3. **`EngineContext.project_state: str` 字段的最终归宿**——是删除、是改名 `project_root` 入参、还是保持现状,等本 change apply 后再开独立 change 评估。