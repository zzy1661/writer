# fea: 让 /init 接收题材，按题材选 Consultant + 生成题材子目录

## Why

当前 `StoryConsultant.draft_outline()` 对任何输入都返回固定四幕结构，丢失了"言情 / 玄幻 / 历史"这一最重要的写作分叉维度。备忘 09（历史史实校验）和两份外部方法论材料都建议按题材分化结构、产物、审核；备忘 16 / 17 已经为多角色做好了 Protocol 槽位。

## What Changes

- **CLIa 子命令 `/init`** 接受 `--genre` 选项（`历史 | 言情 | 玄幻 | other`）；缺失时通过 Typer 交互问询（提供三个预设 + "其他"自定义输入）。
- **`/init` 在交互模式 / REPL `/init` 双路径** 走同一份初始化逻辑（统一通过 `EngineSession.init_project()` 入口）。
- **`AGENT.md` 增加 `题材:` 行**，作为题材的持久化事实来源（与现有 `project_state` 同级）。
- **`EngineSession` 增加 `project_genre` 字段**，每次 `set_project_root` 时从 `AGENT.md` 重新加载；同时也通过构造期直接注入。
- **`EngineContext` 不增加 `genre` 字段**（保持 EngineContext 仍是输入契约；genre 通过 `EngineDeps.story_consultant` 的具体类型间接体现）。
- **`EngineDeps.story_consultant` 槽位**：从单一 `StoryConsultant` 改为按 genre 派生的具体子类。
  - `HistoryConsultant(settings)` —— 输出"史实锚点 + 时序幕"
  - `XuanhuanConsultant(settings)` —— 输出"境界节点 + 分卷幕"
  - `RomanceConsultant(settings)` —— 输出"感情节拍（GMC + Romance Beat Sheet）"
  - `StoryConsultant(settings)` —— 兜底四幕（保留为生产代码，主要给"其他 / 未识别"题材）
- **`/init` 按 genre 生成不同子目录**（在 `create_workspace` 现有结构上叠加，**不破坏**现有 API）：
  - 历史：追加 `史实/年表.md / 人物.md / 事件.md / 考证.md`
  - 玄幻：追加 `伏笔/foreshadow.md` + `大纲/境界表.md`
  - 言情：追加 `人设/男主.md / 女主.md` + `大纲/感情线时间轴.md`
  - 兜底：维持现有六文件
- **`create_workspace` 扩展签名**：`genre: str = "other"` 参数；新增 `_genre_scaffolding()` 私有辅助函数，负责题材特定的额外文件；现有调用点（tests / CLI `new` 子命令）保持兼容。
- **`StoryConsultant` 协议化**（可选，便于未来 LLM 化）：`StoryConsultant` ABC 含 `draft_outline(idea) -> OutlineResult`，三个子类各自实现；`OutlineResult` 形状**不变**（`title / premise / chapters: list[str]`），题材差异通过 `chapters` 字符串内嵌约定来表达（前缀约定或 `第一幕`/`境界1`/`节拍1` 等由各 Consultant 自行决定）。

## Non-goals (明确不做)

- **history_check 工作流节点** —— 备忘 09 提议的"review_gate → history_check → END"边本次**不实现**。`史实/` 目录可以建，内容暂不被引擎消费。备忘 09 标记为 future。
- **GenreLocator 自动识别** —— 用户已经决定 `/init` 必须显式提供题材，不再做关键词自动分类。
- **`/目录 /写 /审核` 的题材分化** —— 这次只把题材嵌到 init + 大纲 + Consultant；后续命令仍按通用流程走。
- **LLM 化** —— 三 Consultant 仍是 deterministic / 网络免费，与现有 `StoryConsultant` 一致，便于 e2e 验证。
- **题材迁移 / 改题材流程** —— 项目跑到一半改题材的行为不在本次范围；`AGENT.md` 现有题材值就是事实，手改文件需重新 `/init`。
- **Prompt 模板系统** —— 不引入 jinja / langchain prompt 抽象；prompt 仍写在代码里或环境。

## 设计取舍记录

| 取舍 | 备选 | 选择 | 理由 |
|---|---|---|---|
| EngineContext 是否加 genre | 加 / 不加 | **不加** | EngineContext 是输入契约，咨询什么走 EngineDeps.story_consultant 间接表达；解耦测试和稳定 cold path |
| `OutlineResult` 形状 | 改形状 / 不改 | **不改** | 改形状要改 engine 读 result.chapters 的所有地方；用 chapters 字符串内嵌约定表达差异，零下游改动 |
| create_workspace 签名 | 加 genre 参数 / 新独立函数 | **加 genre 参数**（向后兼容 default="other"） | 既改 init 又改 init 之外的 CLI 子命令 `new` 必然会面临；一处签名最简 |
| 三 Consultant 各自文件 | 独立 modules / 单文件多 class | **独立 modules** | 历史/玄幻/言情未来各自带 1-2k 行 prompt 与决策逻辑；分文件便于 manage |
| `set_project_genre` | 加到 EngineSession / 临时变量 | **加到 EngineSession** | 题材是跨 turn 状态，与 project_root / pending_interrupt 同级 |
| 兜底 Consultant 类名 | 新建 `DefaultConsultant` / 现有 `StoryConsultant` | **现有 `StoryConsultant`** | 用户明确说"四幕兜底"，且现有类就是兜底语义；避免引入空名新类 |

## Risks

1. **`new` CLI 子命令（typer）与 `/init` REPL 命令并存**——两条入口都需支持 `--genre`。本提案让 `new` 走 `create_workspace(name, dir, force, genre)`；`/init` REPL 路径新增 `init_project()` 入口复用前者。
2. **未来 LLM 化 Consultant 的扩展点**：`StoryConsultant` 是否要 protocol 化？本次**不强制**，但预留位置（类层 + 模块层级注释）。
3. **现有 `test_create_workspace_*` 测试**：新增 `genre` 默认值参数，必须**全部继续过**；并新增 `test_create_workspace_with_genre_*` 子测试。
4. **`tests/test_roles.py` 中 `test_story_consultant_*` 测试**：保留兜底类语义不变；新增 `test_{history,xuanhuan,romance}_consultant_*` 三组。

## 验收基线

- `pytest tests/ -q` 全过（≥ 当前 121 个测试 + 本次新增）
- 覆盖率：维持 ≥98%
- `uv run ruff check src tests` + `uv run mypy src/writer` 均 clean
- e2e：`uv run writer init 我的项目 --genre 言情` 走完无报错，目录含 `人设/男主.md` 等
- e2e：`uv run writer init 我的项目`（无 --genre）触发交互 prompt
- e2e：四幕兜底仍存在，`uv run writer init test --genre "都市悬疑"` 走兜底

## 待用户拍板的子项（apply 之前确认）

- [x] 交互 prompt 的 "其他" 项**允许自由字符串输入**；任何非白名单值都落到 `other` 兜底（包括用户输入"都市悬疑"、"科幻"等）
- [x] **`--genre` 同时支持 `-g`** 短选项
- [x] `AGENT.md` 题材字段用**中文标签**：`题材: 言情`（与项目中文上下文一致；白名单值为"历史 / 言情 / 玄幻"）
- [x] 三题材 `chapters` 字符串约定采用**前缀**方案：
  - 历史 Consultant：`"<叙事阶段>: <史实锚点> | 虚构标注: <text>"` —— 如 `前期: 玄武门之变 | 虚构: 李显穿越为李承乾`
  - 玄幻 Consultant：`"<境界段>: <核心冲突 + 升级目标>"` —— 如 `炼气期: 觉醒金手指 → 入宗门`
  - 言情 Consultant：`"<节拍>: <GMC 阶段名>"` —— 如 `节拍1: 相遇 → 吸引 → 误判`
  - 兜底（`StoryConsultant`）：保留现有"第一幕/第二幕/第三幕/第四幕"格式，不改
