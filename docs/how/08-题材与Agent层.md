# 08 · 题材与 Agent 层(Markdown 身份范式)

> 对应代码:`src/writer/agents/{protocol,registry,agent_discovery,builtin_sources,capability}.py` + `src/writer/agents/_shipped/`
> 设计备忘:[`备忘 16-Agent架构模式`](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)

---

## 8.1 设计动机

**问题**:不同题材(历史 / 言情 / 玄幻 / 其他)需要不同的「LLM 身份」—— 历史要史实校验、玄幻要境界推进、言情要 GMC(Goal/Motivation/Conflict)。

**传统做法**(在 `chg-remove-roles` 之前):Python 类 `HistoryAgent(XuanhuanAgent(RomanceAgent(StoryAgent)))`,每个类有自己的 `_draft_outline` 方法。

**当前做法**(**`chg-remove-roles` 之后**):**LLM 身份 = Markdown 文件**。`writer/agents/_shipped/*.md` 4 份文件,每份一个 `name` / `description` / `genre` frontmatter + body,LLM 在 dispatch 时按 `description` 自选。

### 为什么删 Python 类?

| 维度 | Python 类(旧) | Markdown 范式(新) |
| ---- | -------------- | ------------------ |
| 加新题材 | 写 Python 类,继承,改 `production_deps._agent_for_genre` | 写 .md,放进 `_shipped/` |
| 改 prompt | 找代码,改字符串,重新打包 | 改 .md,reload |
| 测试 | mock 类方法 | 解析 .md,断言 frontmatter |
| 非程序员参与 | ✗ | ✓ |
| LLM 读 prompt | 间接:Python 拼字符串 | 直接:读 .md body |

**结论**:LLM 身份是「给 LLM 看的文本」,放 Markdown 比放 Python 直观得多。

## 8.2 `Agent` 数据模型

> 对应代码:`src/writer/agents/protocol.py`

```python
@dataclass(frozen=True)
class Agent:
    """一个 agent Markdown 加载后的内存形态。"""
    name: str                                 # "历史题材 Agent"
    description: str                          # "擅长史实校验 / 史实: / 虚构: 前缀"
    genre: str                                # "历史" / "言情" / "玄幻" / "other"
    body: str                                 # Markdown body(给 LLM 的 system identity)
    source_path: Path | None = None
```

### 与 `SkillDirective` 的关系

| 维度 | `SkillDirective` | `Agent` |
| ---- | ---------------- | ------- |
| 触发方式 | 用户输入 `/command` | Router 派发 `kind="agent"` action |
| 数量 | 2 shipped | 4 shipped(other / 历史 / 言情 / 玄幻) |
| 用途 | 命令的工作流 | LLM 的「身份 / 角色」 |
| 注入位置 | system prompt 的 `[directive body]` 段 | system prompt 的 `[agent identity]` 段 |

两者**正交**:同一轮 turn 可以同时有 directive + agent(system prompt 两段拼接)。

## 8.3 4 份 shipped agent Markdown

### `_shipped/other.md`

```markdown
---
name: 通用小说 Agent
description: 兜底身份,适合未指定题材或自定义题材,使用四幕结构。
genre: other
body: |
  你是一位通用小说写作助手,擅长四幕结构:

  - 第一幕:铺垫(Setup)
  - 第二幕:第一转折(Inciting Incident)
  - 第三幕:中盘深化(Rising Action)
  - 第四幕:终局落幕(Resolution)

  你的大纲按这四幕组织,每幕 3-5 章。
---
```

### `_shipped/历史.md`

```markdown
---
name: 历史题材 Agent
description: 史实校验;输出大纲使用「史实:」/「虚构:」前缀区分真实历史与小说虚构。
genre: 历史
body: |
  你是一位历史小说写作助手,精通中国古代史:

  ## 史实校验原则
  1. 任何历史人物、事件、年份必须真实
  2. 主角的行动不能改变真实历史走向
  3. 虚构情节用「虚构:」前缀标注

  ## 大纲格式
  你的大纲每章标题前加前缀:
  - 史实:玄武门之变(贞观元年)
  - 虚构:主角救下李世民

  ## 5 段推进
  - 前期铺垫
  - 第一转折
  - 中盘深化
  - 代价升级
  - 终局落幕
---
```

### `_shipped/言情.md`

```markdown
---
name: 言情题材 Agent
description: GMC 推进;输出大纲使用「节拍<N>」前缀。
genre: 言情
body: |
  你是一位言情小说写作助手,擅长 GMC(Goal/Motivation/Conflict)推进:

  ## 9 段 GMC 推进
  节拍1:相遇(Goal:相遇 / Motivation:命运 / Conflict:时空错位)
  节拍2:吸引
  节拍3:第一吻
  节拍4:误解
  节拍5:分离
  节拍6:重逢
  节拍7:真相
  节拍8:抉择
  节拍9:终成眷属

  ## 大纲格式
  你的大纲每章标题前加「节拍<N>」前缀。
---
```

### `_shipped/玄幻.md`

```markdown
---
name: 玄幻题材 Agent
description: 境界推进;输出大纲使用「境界<N>」前缀。
genre: 玄幻
body: |
  你是一位玄幻小说写作助手,擅长境界推进体系:

  ## 5 段境界推进
  境界1:炼气
  境界2:筑基
  境界3:金丹
  境界4:元婴
  境界5:化神

  ## 大纲格式
  你的大纲每章标题前加「境界<N>」前缀,体现主角的实力层级。
---
```

## 8.4 `AgentRegistry` — 注册表

> 对应代码:`src/writer/agents/registry.py`

```python
class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent, *, replace: bool = True) -> None:
        if not replace and agent.name in self._agents:
            raise AgentRegistryError(f"agent {agent.name!r} 已注册且 replace=False")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def require(self, name: str) -> Agent:
        agent = self._agents.get(name)
        if agent is None:
            available = sorted(self._agents.keys())
            raise AgentRegistryError(f"未知 agent {name!r}; available: {available}")
        return agent

    def by_genre(self, genre: str) -> Agent | None:
        """根据题材找 agent。"""
        for agent in self._agents.values():
            if agent.genre == genre:
                return agent
        return None
```

### `AgentRegistryError`

```python
class AgentRegistryError(ValueError):
    """agent 注册 / 查找错误。"""
```

`_run_agent` 在 `agent_registry.require(name)` 抛 `AgentRegistryError` 时产 `ErrorEvent + Done(aborted)`。

## 8.5 `agent_discovery` — 从磁盘加载

> 对应代码:`src/writer/agents/agent_discovery.py`

```python
def discover_shipped_agents() -> list[Agent]:
    """扫描 src/writer/agents/_shipped/*.md。"""
    shipped_dir = Path(__file__).parent / "_shipped"
    return [_parse_agent_md(p) for p in shipped_dir.glob("*.md")]


def discover_project_agents(project_root: Path) -> list[Agent]:
    """扫描 <project_root>/.writer/agents/*.md 项目级覆盖。"""
    agents_dir = project_root / ".writer" / "agents"
    if not agents_dir.exists():
        return []
    return [_parse_agent_md(p) for p in agents_dir.glob("*.md")]


def _parse_agent_md(path: Path) -> Agent:
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    return Agent(
        name=meta["name"],
        description=meta.get("description", ""),
        genre=meta.get("genre", "other"),
        body=body.strip(),
        source_path=path,
    )
```

### 加载优先级

1. `_shipped/*.md`(builtin) → 2. 项目级 `<root>/.writer/agents/*.md` → 3. **没有 entry_point**(Agent 不支持插件)

后注册覆盖先注册 → 项目级覆盖 builtin。

## 8.6 `built_agent_registry()` — 默认装配

```python
def built_agent_registry(project_root: Path | None = None) -> AgentRegistry:
    registry = AgentRegistry()
    for a in discover_shipped_agents():
        registry.register(a)
    if project_root is not None and str(project_root) != "/__no_project__":
        for a in discover_project_agents(project_root):
            registry.register(a)
    return registry
```

**项目切换时 `Engine.set_project_root()` 重新调它**(与 DirectiveRegistry 对称)。

## 8.7 `_run_agent` — Engine 怎么派发 agent

> 对应代码:`src/writer/engine/engine.py::Engine._run_agent`

```python
class Engine:
    async def _run_agent(self, action, ctx):
        from writer.agents import AgentRegistryError
        deps = self._deps
        cfg = self._cfg
        agent_name = action.target_agent or ""
        try:
            agent = deps.agent_registry.require(agent_name)
        except AgentRegistryError as exc:
            yield ErrorEvent(message=f"Agent 错误: {exc}", traceback=str(exc))
            yield Done(reason="aborted", payload={"error": str(exc), "command": agent_name})
            return

        if deps.tool_loop is not None:
            # 把 agent body 作为 system identity,user input 作为 human message
            agent_action = AgentAction(
                action_type="answer_directly",
                command=None,
                kind="agent",
                target_agent=agent_name,
                answer=f"[agent {agent_name!r} system identity]\n{agent.body}\n\n[user input]\n{ctx.user_input}",
            )
            async for event in deps.tool_loop.run(agent_action, ctx, deps, cfg):
                yield event
        else:
            # 纯规则部署:输出 agent 预览
            yield TextChunk(text=f"[agent {agent_name!r} preview, no LLM configured]\n...")
            yield Done(reason="answered", payload={"agent": agent_name, "llm_available": False})
```

**关键**:`answer` 字段拼成 `[agent identity]\n{body}\n\n[user input]\n{user_input}`,LLM 在 `_initial_messages` 里把它当 system hint 提取(`action.answer` 进 `[router hint]` 段)。

## 8.8 `_initial_messages` 中 agent 注入

> 对应代码:`src/writer/llm/agent.py::_initial_messages`

```python
# 2. agent identity:仅当 action.target_agent 非空
if action.target_agent:
    agent_meta = deps.agent_registry.get(action.target_agent)
    if agent_meta is not None:
        system_parts.append(
            f"[agent identity: {agent_meta.name}]\n{agent_meta.body}"
        )
```

System prompt 拼接顺序:

```
1. [base system prompt]   ← 工具循环说明 + 工具目录
2. [directive body: /大纲]  ← 若 directive 命中
3. [directive references]   ← 若有 references
4. [project-level extra instructions]  ← 若项目级 instructions.md 存在
5. [agent identity: 历史题材 Agent]  ← 若 action.target_agent 非空
6. [router hint]          ← 若 action.answer 非空
```

LLM 同时看到「循环说明 + 当前命令指令 + agent 身份 + 路由器 hint」。

## 8.9 唯一 Python-side capability:`process_init_brief`

虽然 `chg-remove-roles` 删了所有 `*Agent` 类,但有**一个 Python-side 能力保留**——`process_init_brief`。它是 `/init <梗概>` 的核心逻辑:把用户的一句话梗概展开成完整创意访谈。

> 对应代码:`src/writer/agents/capability.py`

```python
def process_init_brief(
    project_root: Path,
    brief: str,
    *,
    settings: Settings,
    llm: BaseChatModel | None = None,
) -> InitBriefResult:
    """处理 /init <brief>:
    1. 用 LLM 把 brief 展开为完整创意访谈
    2. 写入 创意/核心创意.md
    3. 更新 AGENT.md 的基本要求字段
    4. 返回 InitBriefResult(source="llm"|"fallback", ...)
    """
    if llm is None and settings.has_api_key:
        llm = get_llm(settings)

    if llm is None:
        # 纯规则部署:把 brief 直接写入,加 fallback 标记
        expanded = brief
        source = "fallback"
    else:
        expanded = _expand_with_llm(llm, brief)
        source = "llm"

    (project_root / "创意").mkdir(exist_ok=True)
    (project_root / "创意" / "核心创意.md").write_text(_render_creative_doc(expanded), encoding="utf-8")
    _update_agent_md(project_root / "AGENT.md", expanded)

    return InitBriefResult(source=source, expanded=expanded)
```

**为什么保留 Python 实现而不走 directive**:这个能力**直接调 settings 与 LLM**,不依赖 tool registry,跨题材通用,放 directive 反而绕弯。

### 调用入口:`apply_init_brief`

> 对应代码:`src/writer/project/init_brief.py`

```python
def apply_init_brief(
    project_root: Path,
    brief: str,
    *,
    settings: Settings,
    llm: BaseChatModel | None = None,
) -> InitBriefResult:
    """对外入口,转调 writer.agents.process_init_brief。"""
    from writer.agents import process_init_brief
    return process_init_brief(project_root, brief, settings=settings, llm=llm)
```

Engine 在 `_run_init_brief_command` 里调它:

```python
from writer.config import get_settings
result = apply_init_brief(ctx.project_root, brief, settings=get_settings())
```

## 8.10 历史档案:`chg-remove-roles` 之前的设计

```python
# 2026-07-09 之前的旧代码(已删除,作为留档)
class StoryAgent:
    def __init__(self, genre: str = "other"):
        self.genre = genre

    def draft_outline(self, brief: str) -> OutlineResult:
        if self.genre == "历史":
            return self._draft_history_outline(brief)
        elif self.genre == "玄幻":
            return self._draft_xuanhuan_outline(brief)
        elif self.genre == "言情":
            return self._draft_romance_outline(brief)
        return self._draft_four_act_outline(brief)

    def _draft_history_outline(self, brief: str) -> OutlineResult:
        ...
        chapters = [
            "史实:玄武门之变",
            "虚构:主角救李世民",
            ...
        ]
```

**为什么删**:
- `draft_outline` 在 `fea-agent-mirror` 之后变成死代码(Markdown 范式接管)
- `_draft_outline_with_llm` 同样死代码
- 唯一非死代码的方法是 `process_init_brief`(保留)
- 三个子类 `HistoryAgent / XuanhuanAgent / RomanceAgent` 全是 dead code

**删除后**:
- `RunnerDeps.story_agent` 字段删除
- `production_deps()` 不再需要 `genre=` kwarg
- `Engine.set_project_root()` 不再 rebind story_agent
- 题材差异完全由 `AgentRegistry` Markdown 范式承担

## 8.11 完整数据流:用户输入"按玄幻题材生成大纲"

```
用户输入 "/大纲 主角修仙" + 项目 AGENT.md 的题材: 玄幻
   ↓
LLM IntentRouter 产出 AgentAction(action_type="run_command", command="/大纲", kind="agent", target_agent="玄幻题材 Agent")
   ↓
session.run_turn(user_input) → 构造 RunnerContext + 委派给 session.engine.run(ctx)
   ↓
Engine._engine_loop:
    if action.kind == "agent":
        async for event in self._run_agent(action, ctx):
            yield event
   ↓
self._run_agent:
    agent = self._deps.agent_registry.require("玄幻题材 Agent")
    # 把 agent body 作为 system identity
    agent_action = AgentAction(
        action_type="answer_directly",
        command="/大纲",  # 仍然携带 directive command
        kind="agent",
        target_agent="玄幻题材 Agent",
        answer=f"[agent identity]\n{agent.body}\n\n[user input]\n主角修仙",
    )
    async for event in self._deps.tool_loop.run(agent_action, ctx, self._deps, self._cfg):
        yield event
   ↓
ReActAgent.run():
    _initial_messages(): 拼 system prompt = base + directive body + agent body + router hint
    LLM 看到:
        1. 工具循环说明
        2. /大纲 directive body(四幕结构 + 步骤)
        3. 玄幻题材 Agent body(境界<N> 前缀 + 5 段推进)
        4. router hint(user_input "主角修仙")
    LLM 决策:调 safe_read_file("AGENT.md") 读题材确认 → 调 safe_write_file("outline/大纲.md", ...)
    yield Done("answered")
```

## 8.12 关键设计约束

### 1. agent Markdown 不应该做的事

- ❌ 写 Python 代码或 import(LLM 读不懂)
- ❌ 写完整的世界观设定(那是 `world/setting.md` 的活)
- ❌ 写大纲模板(那是 SKILL.md 的活)

### 2. agent Markdown 应该做的事

- ✅ 一句话说明这个 agent 是什么
- ✅ 题材特定的输出格式约定(如「境界<N>」前缀)
- ✅ 题材特定的注意事项(史实校验 / GMC 推进 / 境界推进)
- ✅ body 控制在 1-3 页 Markdown(LLM context 不能爆)

### 3. 加新 agent 不需要改 Python

```bash
# 1. 创建新 .md
cat > src/writer/agents/_shipped/科幻.md <<'EOF'
---
name: 科幻题材 Agent
description: 硬科幻设定;输出大纲使用「纪元<N>」前缀。
genre: 科幻
body: |
  你是一位硬科幻小说写作助手...
---
EOF

# 2. reload 即可生效
uv run writer
> /大纲 火星殖民
```

---

## 8.13 进一步阅读

- [07-技能directive层](07-技能directive层.md) —— 同样范式,用在命令指令
- [15-演进与备忘体系](15-演进与备忘体系.md) —— `chg-remove-roles` 与 `fea-agent-mirror` 的演进
- [备忘 16-Agent架构模式](../../技术难点与解决方案备忘/16-Agent架构模式与本项目选型.md)