# writer-agent Bug 索引

> 一次性记录 2026-07-09 系统性 code-review 发现的 5 个 bug。每篇按统一 8 节模板描述"现象—根因—影响—修复—验证—回归—风险"。
> 截至 2026-07-14,Bug 1-4 已修复(commit `8856e67` / `e040d6a` / `ad45896` / `aa89c78`),仅 Bug 5(module-global deps 注入并发串线)待修。
> **Bug 1-4 文档保留**作为历史档案:记录"为什么 baseline 漏检""修复前的影响""测试盲区"——防止未来回归时重蹈覆辙。

## 元信息

| 项 | 值 |
|---|---|
| 创建日期 | 2026-07-09 |
| 最后更新 | 2026-07-14(Bug 1-4 修复后状态同步) |
| 关联基线 | 483 测试全过 + ruff clean + mypy clean(per 2026-07-14,_plan_chapter_node LLM 驱动后) |
| 关联 OpenSpec | Bug 1-4 修复均未走 OpenSpec(独立 commit,改动局部);Bug 5 待定 |
| 维护者约定 | 命名沿用 `技术难点与解决方案备忘/01-17` 编号体系;中文文档,与 `docs/` 现有风格一致 |
| 文档目的 | bug 修复前的工程共识沉淀 + 测试盲区追溯 + 历史回归防御 |

## 一句话定位

5 个 bug 在 2026-07-09 baseline (339/339) 测试盲区下漏检 — **测试通过率 + lint clean ≠ 无 bug**。截至 2026-07-14 (483/483),Bug 1-4 已修,Bug 5 待修。本目录沉淀盲区分析的元数据,让"为什么 baseline 漏检"在文档里可追溯。

## 主索引表

| # | 标题 | 严重程度 | 状态 | 修复 commit | 主要根因位置 | 文档 |
|---|---|---|---|---|---|---|
| 1 | `tool_loop` 不重建,LLM 工具调用指向旧根目录 | 🔴 Blocker | ✅ 已修 | [`8856e67`](https://github.com/anthropic-...(略)/commit/8856e67) | `src/writer/session/engine.py::set_project_root` | [01](./01-tool-loop-not-rebound.md) |
| 2 | `_initial_messages` 完全忽略 `AgentAction.answer`,directive body 不进 LLM | 🟠 Major | ✅ 已修 | [`e040d6a`](https://github.com/anthropic-...(略)/commit/e040d6a) | `src/writer/llm/agent.py::_initial_messages` | [02](./02-action-answer-ignored-by-tool-loop.md) |
| 3 | `review_chapter` 几乎永远走 deterministic,API key 配了也无效 | 🟠 Major | ✅ 已修 | [`ad45896`](https://github.com/anthropic-...(略)/commit/ad45896) | `src/writer/workflows/review_chapter.py::_aggregate_reviews_node` | [03](./03-review-chapter-always-deterministic.md) |
| 4 | 写入白名单字面值(`.writer/cache`)与匹配规则(`rel.parts[0]`)不一致 | 🟠 Major | ✅ 已修 | [`aa89c78`](https://github.com/anthropic-...(略)/commit/aa89c78) | `src/writer/tools/builtin/file_tools.py::_check_whitelist` + `src/writer/tools/runtime.py` | [04](./04-whitelist-vs-first-segment.md) |
| 5 | 工作流用 module-global 注入 deps,并发场景串线 | 🟠 Major | ⏳ 待修 | (无) | `src/writer/workflows/write_chapter.py::_WORKFLOW_DEPS` + `src/writer/workflows/review_chapter.py::_REVIEW_DEPS` | [05](./05-workflow-module-globals.md) |

> **修复 commit 锚点**:每个"已修"行带 commit SHA;回归测试在 `tests/` 下,可用 `git log --grep "per Bug N"` 反查。

## 优先级修复顺序(历史)

~~4 → 3 → 1 → 2 → 5~~ — 截至 2026-07-14 实际按 `Bug 1 → 2 → 3 → 4 → 5` 顺序修复(Bug 1 早于 Bug 4;Bug 4 反而最晚)。原计划与实际差异是正常的"在压力下修了最痛的那个";不影响修复结果,留作教训:**别把"修复顺序"当作 SLA 承诺**。

## 关联基线表

| 项 | 创建时 (2026-07-09) | 当前 (2026-07-14) | Bug 1-4 净影响 |
|---|---|---|---|
| 测试总数 | 339 | 483 | +144 (Bug 1-4 修复期新增:rebind_tool_loop 5 / _initial_messages 4 / review_llm 早返 6 / _check_whitelist 5 + 共享 fixture + e2e) |
| ruff | clean | clean | — |
| mypy | clean | clean | — |
| 已删 SKILL.md | `/续写` `/改` | 保持已删 | — |
| shipped SKILL.md | 2 (`/大纲` `/目录`) | 保持 2 | — |
| builtin Tool 数 | 9 | 9 | — (Bug 4 仅改 `_check_whitelist` 实现,不增减 Tool) |
| `RunnerDeps` Protocol 字段 | 8 (router / agent_registry / tool_registry / tool_runtime / directive_registry / tool_loop / prose_client / review_llm) | 8 + 1 method (新增 `rebind_tool_loop()`) | Bug 1 增方法不增字段 |
| `_WORKFLOW_DEPS` / `_REVIEW_DEPS` 模块级变量 | 存在(写死的 module global) | 存在 | Bug 5 待修移除 |

## 与其他文档的关系

- **架构图 / 命令流** → `docs/技术架构总览.md`(高层架构 + LangGraph 状态图)
- **历史决策备忘** → `技术难点与解决方案备忘/01-17/*.md`(选型理由 + 不做什么清单)
- **RAG 历史** → `docs/技术架构细节.md`(已归档,被 `技术架构总览.md` 取代)
- **OpenSpec 历史** → `openspec/changes/archive/*/`(已 apply 的变更,可参考任务拆分粒度)

## 命名 / 引用约定

- 代码引用:`src/writer/llm/agent.py:281-292` 反引号 + 行号区间
- 跨文档链接:`[Bug 3](./03-review-chapter-always-deterministic.md)` 短 slug,相对路径 + `./`
- 备忘引用:`备忘 07-工具注册与文件权限安全.md` 沿用 MEMORY.md 简称
- 代码块:` ```python ` 标签 + `# fix proposal` 注释
- 数据流图:ASCII box-arrow 风格,统一 `✓` / `✗` / `←` / `→` 符号,无 ANSI 颜色
- 测试用例表:类型列固定三选一 `NEW / MODIFY / DELETE`,末行必有 `e2e`

## 验证门槛

每篇 §7 末行要求手动验证:`uv run pytest` 全过 + `uv run ruff check src tests` clean + `uv run mypy src/writer` clean。
已修 Bug 在对应 commit 上验证通过;待修 Bug 在 PR 时同样要求。

## 不在本目录范围

- ❌ 实际修复代码编写(Bug 1-4 已落 commit;Bug 5 实现另起 OpenSpec change)
- ❌ 创建 OpenSpec change proposal(后续 `/opsx:propose` 走流程)
- ❌ 修改 `openspec/specs/*` 的 delta(只在每篇 §8 风险与遗留里 cross-ref)
- ❌ 文档英文翻译(保持中文)