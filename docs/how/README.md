# 如何一步步搭出 writer-agent

> **本教程目标**:把 `writer-agent`(中文长篇小说写作 CLI)的每一层、每一包的设计与实现都讲清楚,让你即便没有读过代码,也能在一天内把整套架构重建出来。
>
> 写作日期:2026-07-16 修订(原 2026-07-11) · 对应基线:`549 passing / 1 pre-existing failing / ruff+mypy clean / Runner AsyncGenerator + IntentRouter Protocol + 9 builtin Tool + ReActAgent + 3 shipped directives (/大纲 /目录 /人物) + LangGraph write_chapter / review_chapter`。
>
> **2026-07-16 修订**:`Engine/EngineSession` 命名混淆已解决(per `chg-rename-engine-runner`)。状态机主类现叫 `Runner`(`src/writer/runner/runner.py`);会话控制层现叫 `Engine`(`src/writer/session/engine.py`,原 `EngineSession`)。`session.run_turn(text)` 委派给 `session.runner.run(ctx)`。所有 `src/writer/engine/` 路径 → `src/writer/runner/`。
>
> 阅读建议:先读 [01-总览与四层架构](01-总览与四层架构.md) 建立心智地图,然后按章节顺序读;每章都有「核心代码 + 伪代码 + 设计动机」三段式。

## 教程目录

| 章节 | 主题 | 对应源码包 |
| ---- | ---- | ---------- |
| [01](01-总览与四层架构.md) | 总览 + 四层架构 + 设计哲学 | 整个仓库 |
| [02](02-环境与CLI入口.md) | 项目结构、依赖、CLI 入口、Typer 子命令 | `pyproject.toml` + `src/writer/cli/` + `src/writer/__main__.py` |
| [03](03-会话与状态机.md) | `Engine`(会话层)跨 turn 状态 + 项目状态机 S0–S5 | `src/writer/session/` + `src/writer/project/state.py` |
| [04](04-意图路由层.md) | `IntentRouter` Protocol + 三种实现 | `src/writer/routing/` |
| [05](05-引擎核心.md) | `Runner.run` 事件流 + `RunnerDeps` DI + Done 分支 | `src/writer/runner/` |
| [06](06-Tool层与Runtime.md) | Tool 协议 + Runtime + 9 个 builtin | `src/writer/tools/` |
| [07](07-技能directive层.md) | SKILL.md + DirectiveRegistry + 项目级覆盖(3 shipped:`/大纲` `/目录` `/人物`) | `src/writer/skills/` |
| [08](08-题材与Agent层.md) | `AgentRegistry` + 4 份题材 Markdown | `src/writer/agents/` |
| [09](09-ReAct工具循环.md) | `ReActAgent` ReAct + 双 provider | `src/writer/llm/` |
| [10](10-项目workspace脚手架.md) | `create_workspace` + AGENT.md 状态字段 | `src/writer/project/` |
| [11](11-配置与设置.md) | `Settings` + env 优先级 | `src/writer/config/` |
| [12](12-工作流与审核.md) | `write_chapter` / `review_chapter` LangGraph 5 节点图 | `src/writer/workflows/` |
| [13](13-打包与发布.md) | PyInstaller + `writer.spec` | `packaging/` |
| [14](14-测试体系.md) | pytest + LangChain fake model + stub 模式 | `tests/` |
| [15](15-演进与备忘体系.md) | 17 个技术备忘 + OpenSpec changes + `docs/bugs/` | `技术难点与解决方案备忘/` + `openspec/` |

## 一句话总结整个项目

```
用户键入 → CLI → Engine(长寿命,持 runner) → Runner(短寿命,AsyncGenerator 事件流)
            │                                    │
            │                                    ├─ IntentRouter.route()  → AgentAction
            │                                    ├─ DirectiveRegistry      → LLM 工具循环消费 SKILL.md body
            │                                    ├─ ToolRegistry           → 9 个 builtin Tool
            │                                    ├─ AgentRegistry          → 4 份题材 Markdown
            │                                    └─ WorkflowRegistry       → 写章节 / 审核
            │
            └─ Engine.run_turn(text) → 构造 RunnerContext 委派给 session.runner.run(ctx)
              每个 turn yield 一个 Done,8 种 reason,REPL 据此渲染
```

## 怎么读这份教程

1. **快速建立心智地图** → 读 [01](01-总览与四层架构.md),10 分钟
2. **想了解一个具体模块** → 直接跳到对应章节
3. **想看实际代码** → 每章都有「核心代码」段,直接指向源码
4. **想知道为什么这么设计** → 读每章开头的「设计动机」段,以及 `技术难点与解决方案备忘/`
5. **想复现项目** → 按章节顺序把每一章的伪代码实现一遍即可

## 与现有文档的关系

| 文档 | 关系 |
| ---- | ---- |
| [`CLAUDE.md`](../../CLAUDE.md) | 开发指引,命令清单,包级职责概览 |
| [`docs/技术架构总览.md`](../技术架构总览.md) | 架构精修,变更记录 |
| [`docs/命令与用户流程.md`](../命令与用户流程.md) | 命令清单 + 状态机矩阵 |
| [`docs/设计文档.md`](../设计文档.md) | 产品定义,目录约定 |
| [`docs/how/`](../how/README.md) | **本文档** —— 手把手教程 |
| [`技术难点与解决方案备忘/`](../../技术难点与解决方案备忘/) | 17 个技术决策备忘,每个决策的"为什么" |
| [`openspec/changes/`](../../openspec/changes/) | 每次大变更的 proposal/design/tasks/specs |
| [`docs/bugs/`](../bugs/README.md) | bug 修复记录(per Bug N 锚点) |

## 适合谁读

- 想理解 LangChain / LangGraph / ReAct / Pydantic-settings / Typer / Rich / prompt_toolkit 在生产 CLI 里如何组合
- 想学习「Protocol + DI + 事件流」如何解耦长任务 Agent
- 想理解「Markdown 即配置」「Markdown 即身份」的范式
- 想给「中文小说写作」或类似内容创作工具做架构参考

## 阅读时长

- 通读全部 ≈ 90 分钟
- 重点章节(01 + 05 + 09) ≈ 30 分钟