# Bug 02: `_initial_messages` 完全忽略 `AgentAction.answer`,directive/agent body 不进 LLM

## 元信息

| 严重程度 | 🟠 Major |
|---|---|
| 状态 | 待修 |
| 发现日期 | 2026-07-09 |
| 关联文件 | `src/writer/llm/agent.py:281-292`、`src/writer/engine/loop.py:191-204`、`src/writer/routing/intent_router.py`(`AgentAction` 定义) |
| 测试盲区 | 测试断言 `_system_prompt()` 返回固定文本(`"你是 Writer Agent 的工具循环..."`),从未断言 directive body 或 agent body 是否拼入 |

## 1. 现象(Symptom)

### 可复现步骤

1. REPL + `/init 项目题材 --genre 其他` → 创建项目,自动 mirror shipped `/大纲` SKILL.md
2. REPL 输入 `/大纲 一个穿越到唐朝的程序员` → router 解析为 `AgentAction(action_type="run_command", command="/大纲")`,engine 进入 dispatch
3. `_dispatch_command` 命中 shipped `大纲/SKILL.md` 的 directive → 取 directive `body` 字段(包含四幕模板等大段指令)
4. ❌ **Bug 当前**:engine 把 directive 标为 `answer_directly` 走 LLM 工具循环,但 `_initial_messages` 不把 directive body 拼入 system prompt,LLM 只看到通用工具循环说明
5. 实际结果:LLM 不知道有"四幕模板",随机生成大纲,质量远低于 SKILL.md 设计预期
6. 期望结果:LLM 看到 `[directive body]\n<四幕模板全文>`,按指令生成大纲

### 代码引用

```python
# src/writer/llm/agent.py:281-292 (_initial_messages 当前实现)
def _initial_messages(
    self, action: AgentAction, user_input: str
) -> list[BaseMessage]:
    """Seed the conversation with system prompt + user turn."""
    system = self._system_prompt()        # ← 固定的工具循环说明
    return [
        SystemMessage(content=system),
        HumanMessage(content=user_input),  # ← 只有用户输入
    ]
    # ✗ Bug: 完全不读 action.answer / action.target_agent / action.command
    # ✗ 完全不查 deps.directive_registry / deps.agent_registry

# src/writer/llm/agent.py:294-323 (_system_prompt 当前实现)
def _system_prompt(self) -> str:
    catalog = json.dumps([...工具目录...], ensure_ascii=False)
    return (
        "你是 Writer Agent 的工具循环(ReAct-style)。\n"
        "你的任务是:\n"
        "1. 阅读用户输入与对话历史...\n"
        "2. 决定下一步...\n"
        f"可用工具目录:\n{catalog}\n"
    )
    # ✗ 没有任何 directive / agent 内容
```

### `AgentAction` 字段参考

```python
# src/writer/routing/intent_router.py (字段定义)
class AgentAction(BaseModel):
    model_config = {"frozen": True}
    action_type: Literal["answer_directly", "call_tool", "run_command", "run_workflow"]
    command: str | None = None                # ← /大纲、/目录 等
    target_agent: str | None = None          # ← agent dispatch 时填
    answer: str | None = None                # ← router 拼好的 prompt 后缀 / hint
    tool_name: str | None = None
    arguments: dict[str, Any] = {}
```

## 2. 根因(Root Cause)

`_initial_messages` 设计与 directive/agent 范式不兼容。

**历史背景**:`writer.skills` 是 2026-07-08 实装的"SKILL.md 是 markdown 范式指令"(`chg-markdown-skills`),`writer.agents` 是 2026-07-09 实装的"AgentRegistry 是 markdown 范式身份"(`fea-agent-mirror`)。这两个 markdown 范式身份都依赖"system prompt 拼入 body 字段",但 `_initial_messages` 在它们之前(2026-07-08 LLM 工具循环实装)设计,**未考虑后续 directive/agent 注册表的接入路径**。

### 数据流图

```
User: /大纲 一个穿越到唐朝的程序员
                ↓
Router: AgentAction(action_type="run_command", command="/大纲", answer=None)
                ↓
Engine dispatch: 命中 shipped 大纲/SKILL.md
                ↓
run_command → action.action_type 改为 "answer_directly"
                ↓
LLM Tool Loop: _initial_messages(action, user_input)
                ↓ ✗ Bug: action.answer / action.command 都被忽略
                ↓ ✗ Bug: deps.directive_registry.get("/大纲").body 完全不读
                ↓
SystemMessage(content="你是 Writer Agent 的工具循环(ReAct-style)...")
                ↓
LLM: 不知道有四幕模板,自由发挥生成大纲
```

## 3. 影响范围(Blast Radius)

| 受影响表面 | 触发条件 | 严重性 | 当前绕过方式 |
|---|---|---|---|
| `/大纲` SKILL.md directive | 用户跑 `/大纲` 命令 | 🟠 高(LLM 看不到四幕模板) | **已通过 Bug 修复完成**(per 2026-07-08 的 LLM 工具循环实装日志,实际生产路径可能走了别的 fallback) |
| `/目录` SKILL.md directive | 用户跑 `/目录` 命令 | 🟠 高(LLM 看不到目录生成模板) | 同上 |
| 任何 shipped / project-level SKILL.md directive | 用户用任何 directive 命令 | 🟠 高(全部 directive body 失效) | SKILL.md 的 `references` 同理失效 |
| Agent dispatch(`target_agent="历史"`) | 父 LLM 选择走子 agent 身份 | 🟠 高(子 agent 的 identity body 不进 system) | agent body 完全失效,等价于父 LLM 凭空调用工具 |
| Rule-only 部署(`tool_loop=None`) | API key 未配 | — (不走 LLM) | 无 |
| `_parse_ai_message` 解析路径 | 不受影响 | — | — |

**注**:此 bug 与 LLMToolLoop 的"工具循环消费 body"机制形成对照 — 后续 LLM 工具循环(实装日志中)声明"消费 SKILL.md body + references + builtin Tool 写 outline/大纲.md",但**实际 system prompt 拼装代码缺失**,理论上 directive body 没传过去。这与基线"339 测试全过"形成矛盾,推测当前的 339 测试要么(a)走 rule-only 部署根本不触发 LLM 路径,要么(b)用 mock 注入 system prompt 不走 `_initial_messages`。**两种假设都需要在 §6 测试覆盖下被证伪或确认**。

## 4. 修复方案(Fix)

### 方案 A(★ 主推):`_initial_messages` 重写为双来源 system prompt 拼接

把 directive body 和 agent body 显式拼入 system prompt。

```python
# fix proposal — src/writer/llm/agent.py:_initial_messages

def _initial_messages(
    self, action: AgentAction, user_input: str, *, deps: EngineDeps
) -> list[BaseMessage]:
    """Seed conversation: base system prompt + directive/agent body + user turn.

    双来源拼接规则:
    1. base system prompt(工具循环说明 + 工具目录)— 保留
    2. 当 action.command 命中 directive_registry:追加 [directive body] 段
    3. 当 action.target_agent 命中 agent_registry:追加 [agent identity] 段
    """
    system_parts: list[str] = [self._system_prompt()]

    # 1. directive body:仅当 action 是 answer_directly 且有 command
    if action.action_type == "answer_directly" and action.command:
        directive_meta = deps.directive_registry.get(action.command)
        if directive_meta is not None:
            refs = "\n\n".join(
                f"--- {relpath} ---\n{body}"
                for relpath, body in directive_meta.references.items()
            )
            section = (
                f"[directive body: {directive_meta.command}]\n"
                f"{directive_meta.body}"
            )
            if refs:
                section += f"\n\n[directive references]\n{refs}"
            system_parts.append(section)

    # 2. agent identity:仅当 action.target_agent 非空
    if action.target_agent:
        agent_meta = deps.agent_registry.get(action.target_agent)
        if agent_meta is not None:
            system_parts.append(
                f"[agent identity: {agent_meta.name}]\n{agent_meta.body}"
            )

    # 3. router 拼好的 answer(用作 hint,不是指令)
    if action.answer:
        system_parts.append(f"[router hint]\n{action.answer}")

    return [
        SystemMessage(content="\n\n".join(system_parts)),
        HumanMessage(content=user_input),
    ]
```

**改动文件清单**:
1. `src/writer/llm/agent.py` — `_initial_messages` 签名加 `deps` + 重写
2. `src/writer/engine/loop.py:584` / `:669` / `:685` — 调用点 `deps.tool_loop.run(action, ctx, deps, cfg)` → `deps.tool_loop._initial_messages(action, ctx.user_input, deps=deps)`(loop.py 已有 `deps` 变量,直接传)
3. `tests/conftest.py`(如有)— 测试 stub `PlainDeps` 补 `directive_registry` / `agent_registry` 字段
4. `tests/test_llm_tool_loop.py` — 新增 2 个测试
5. `tests/test_engine_loop.py` — 新增 1 个测试
6. `tests/test_directive_dispatch.py` — 新增 1 个测试

### 方案 B(备选):在 engine 层拼 directive body 后传给 tool_loop

```python
# src/writer/engine/loop.py (engine 层)
def _build_initial_messages(action, ctx, deps):
    system_parts = [base_system_prompt]
    if action.command:
        d = deps.directive_registry.get(action.command)
        if d:
            system_parts.append(d.body)
    # ...
    return [SystemMessage("\n\n".join(system_parts)), HumanMessage(ctx.user_input)]

# 然后传给 LLMToolLoop.run(initial_messages=...)
```

**否决理由**:
1. 把 directive 拼装逻辑从 llm 包搬到 engine 包,**违反分层**(llm 包不再独立可测)
2. 方案 A 的"LLM 工具循环内部拼装"才是对称的(loop.py 调用 `tool_loop.run(action, ctx, deps, cfg)`,其中 `deps` 已在签名里 — 让循环内部读 deps 自然)
3. 方案 B 在 agent dispatch 路径上需要额外注入(agent identity 不来自 directive)

### 方案 C(备选):`LLMToolLoop` 加 `system_prompt_extras: list[str]` 构造参数

```python
LLMToolLoop(..., system_prompt_extras=[
    directive.body, agent.body,
])
```

**否决理由**:`system_prompt_extras` 在构造时固定,但 `EngineSession.set_project_root` 后 directive_registry 重建 → extras 变 stale。需额外加 `set_system_prompt_extras()` 方法,复杂度不亚于方案 A 但 API 不优雅。

## 5. 验证步骤(Manual Reproduction)

```bash
# 1. 创建项目
printf "/init 穿越题材 --genre 其他\n" | uv run writer
cd /tmp/test-bug02

# 2. 看 shipped SKILL.md 的 body(应有四幕模板)
cat .writer/skills/大纲/SKILL.md | head -40

# 3. 跑 /大纲,观察 LLM 是否使用四幕模板
echo "OPENAI_API_KEY=sk-your-key" > .env
printf "/大纲 一个穿越到唐朝的程序员\n" | uv run writer

# 期望(buggy):
#   生成的大纲没有清晰的"第一幕/第二幕/..."结构
#   或者 LLM 在对话中说"我不知道你想要的格式" / 自由发挥

# 期望(修复后):
#   生成的大纲明显按四幕模板分章节,术语与 SKILL.md 一致
```

直接观察 system prompt(测试 mock 注入):

```python
# uv run python - <<'PY'
import asyncio
from langchain_core.messages import SystemMessage
from writer.config import Settings
from writer.llm.agent import LLMToolLoop
from writer.routing import AgentAction
from writer.tools import built_tool_registry, ToolRuntime

async def main():
    # mock LLM that records the messages it received
    class RecordingFakeLLM:
        _llm_type = "recording"
        received_messages = []
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages, **kw):
            type(self).received_messages = messages
            from langchain_core.messages import AIMessage
            return AIMessage(content='{"action_type":"answer_directly","answer":"ok"}')

    from pathlib import Path
    runtime = ToolRuntime(project_root=Path("/tmp/test-bug02"))
    loop = LLMToolLoop(
        settings=Settings(),  # 假设 has_api_key=True
        registry=built_tool_registry(),
        runtime=runtime,
        llm=RecordingFakeLLM(),
    )
    deps = ...  # 构造 stub EngineDeps,带 directive_registry
    action = AgentAction(action_type="answer_directly", command="/大纲")
    async for _ in loop.run(action, ctx, deps, cfg):
        pass
    sys_msg = RecordingFakeLLM.received_messages[0]
    assert "[directive body: /大纲]" in sys_msg.content
    print("✓ directive body 已拼入 system prompt")
PY
```

## 6. 回归测试用例清单

| 测试文件 | 测试名 | 关键断言 | 类型 |
|---|---|---|---|
| `tests/test_llm_tool_loop.py` | `test_initial_messages_includes_directive_body` | mock `deps.directive_registry.get("/大纲")` 返回 mock SkillDirective,断言 `SystemMessage.content` 含 `"[directive body: /大纲]"` + directive body 全文 | NEW |
| `tests/test_llm_tool_loop.py` | `test_initial_messages_includes_agent_identity` | mock `deps.agent_registry.get("历史")` 返回 mock Agent,断言 SystemMessage 含 `"[agent identity: 历史]"` + agent body | NEW |
| `tests/test_llm_tool_loop.py` | `test_initial_messages_includes_references` | mock SkillDirective 带 `references={"template.md": "..."}`,断言 SystemMessage 含 `[directive references]` 段 | NEW |
| `tests/test_llm_tool_loop.py` | `test_initial_messages_no_command_no_body` | `action.command=None` 时不查 directive_registry,SystemMessage 只含 base prompt | NEW |
| `tests/test_llm_tool_loop.py` | `PlainDeps` | 测试 stub 补 `directive_registry` + `agent_registry` 字段(可不 mock,只要 `get()` 返回 None 即可) | MODIFY |
| `tests/test_directive_dispatch.py` | `test_directive_body_reaches_tool_loop` | 端到端:`/大纲` 输入 → engine 命中 directive → 调用 `LLMToolLoop._initial_messages` → mock LLM 收到拼好的 system prompt | NEW |
| `tests/test_engine_loop.py` | `test_agent_body_reaches_tool_loop` | 端到端:agent dispatch 路径同样断言 SystemMessage 含 agent identity | NEW |
| e2e | `tests/e2e/test_repl_dogma_uses_template.py` | 配 API key 后 REPL `/大纲 <题材>`,断言生成的 outline/大纲.md 包含 SKILL.md 中规定的术语("第一幕"/"幕"/"节拍"等) | NEW e2e |

## 7. 风险与遗留(Risks & Follow-ups)

### 修复后仍未解决的相邻问题

- **`AgentAction.answer` 字段语义不明**:当前定义是 router 拼好的 hint,但实际 router 代码基本不填这个字段。需在 router 层也补充文档:`answer` 是"router 想给 LLM 的额外上下文",而非 LLM 的最终输出。
- **`tools_allowlist` 不强制**:`Agent.tools_allowlist` 字段已声明但未 enforce(`agents/protocol.py:21-24` 注释明示),LLM 仍可调任意工具。留给未来 change。
- **directive `references` 内容大小**:若 references 很大(如多份模板拼起来),system prompt token 可能爆。需在 `_initial_messages` 加 token 截断,留给未来。
- **AgentRegistry 与 DirectiveRegistry 的 priority**:`fea-agent-mirror` 项目级覆盖 builtin,但 SKILL.md 与 Agent 各自的覆盖语义独立。两者同时存在时 system prompt 拼接顺序由 `_initial_messages` 决定,需文档化。

### 与 OpenSpec 的关系

- **未来 change 提案建议名**:`fix-initial-messages-include-directive-and-agent-body`
- **需要 spec delta**:`intent-routing` spec 的 `#### Scenario: LLM tool loop receives directive context` 需新增 scenario;`engine-loop` spec 的 `#### Scenario: Directive body reaches LLM` 需新增
- **文档同步**:`备忘 13-核心Tool设计.md` 中"LLM 工具循环"段需补"system prompt 由 base + directive body + agent identity + router hint 四段拼接"
- **`agents/protocol.py` 注释更新**:`# Body: ... Becomes the system identity for the agent's LLM call.` — 需在 `_initial_messages` 实现后才有意义

### 关联 bug

- 与 [Bug 1](./01-tool-loop-not-rebound.md) **间接相关**:rebind tool_loop 后,新的 tool_loop 实例的 `self._runtime` 正确,但 `LLMToolLoop._initial_messages` 仍需要 `deps` 才能读到 directive/agent — 两个 bug 协同修复
- 与 [Bug 5](./05-workflow-module-globals.md) **正交**:workflow module globals 是另一类 stale reference 问题,不影响 directive body 注入
- **未来与 chg-project-skills 联动**:`chg-project-skills` 在 `agents/protocol.py` 加 `extra_instructions: str` 字段(已 apply,2026-07-08),`_initial_messages` 修复时应一并读取该字段,免得二次返工