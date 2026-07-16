# 伏笔表 Schema 指南

`/伏笔` directive 写入的目标文件 `伏笔/伏笔表.md` 的 6 字段 Markdown 表 schema。每条伏笔一行,ID 列兼容下游结构化 ledger(`foreshadow_search` 工具读的 `伏笔.yaml`)。

## 标准表头与一行模板

```markdown
# 伏笔表

| ID   | 描述             | 埋伏章节       | 回收章节       | 标签             | 状态   |
|------|------------------|----------------|----------------|------------------|--------|
| F1   | 张三左手伤疤来历 | 第 3 章        | 未知           | 男主,身世        | laid   |
| F2   | 神秘玉佩出处     | 第 7 章        | 第 25 章       | 信物,女主        | laid   |
```

## 6 字段填写规则

| 字段 | 类型 | 规则 | 与 YAML 对齐 |
|---|---|---|---|
| `ID` | `F<N>` | 连续编号 `F1, F2, ...`;新条目 = 当前最大 ID + 1;`safe_read_file` 后正则扫描(`^F(\d+)\s+\|`) | YAML 同款 `id: F\d+`;`query_ledger(id=...)` 过滤 |
| `描述` | 字符串(必填) | 一句话讲清伏笔是什么;不允许"待补"占位 | YAML `notes` 字段(本表粒度更短) |
| `埋伏章节` | 章节锚点 | `第 X 章` 或 `第 X 卷 Y 章`;未指定写 `未知`(用户后续在 TextChunk 提示) | YAML `laid_chapter` 字段(类型 int,本表用文本是为了人类可读) |
| `回收章节` | 章节锚点 | 同上;未回收写 `未知`,已回收填具体章节 | YAML `paid_chapter` 字段(None / int) |
| `标签` | 逗号分隔 | 例:`男主,身世,信物,伏剑`;未指定写 `未分类` | YAML `tags: list[str]`;**必须保持拼写一致**(`query_ledger(tags=[...])` 用 EXACT 匹配) |
| `状态` | 枚举 | `laid` (已埋伏) / `paid` (已回收);`/伏笔` 默认 `laid`;回收时手编为 `paid` | YAML `status: "laid"|"paid"`(同时 `paid_chapter` 字段配合) |

## 章节锚点格式要求(强制)

- **必须**用「第 X 章」或「第 X 卷 Y 章」格式;**禁止**写 `2024-03-15` / `三十五` / `五` 等日历 / 数字 / 汉字数字单独形式
- 章节锚点是为了和 `_build_canon_block` (rglob `大纲/*.md`) 配合,让下游 `_plan_chapter_node` / `_draft_chapter_node` 把伏笔回收点与章节正文对齐
- 章节不存在(剧情尚未写到):写 `未知`,提示用户在后续章节补
- 多卷项目用「第 X 卷 Y 章」(X = 卷号,Y = 卷内章号);单卷项目只用「第 X 章」

## 标签推荐清单(摘自 YAML 实战标签)

| 类别 | 常见标签 |
|---|---|
| 角色 | `男主`, `女主`, `反派`, `导师`, `配角`, `群像` |
| 主题 | `身世`, `感情`, `权谋`, `复仇`, `传承`, `觉醒` |
| 物件 | `信物`, `武器`, `秘籍`, `遗物`, `神器` |
| 节奏 | `爽点`, `虐点`, `反转`, `钩子`, `高潮` |
| 写作 | `铺垫`, `回收`, `双线`, `延迟` |

建议每条伏笔 2-4 个标签;太多反而失去检索意义。

## 状态机:laid → paid

```text
laid (已埋伏,回收章节 = 未知)
  ↓ 用户在写作过程中回收伏笔
  ↓ 把状态列改 paid,回收章节填实际章节
paid (已回收,回收章节 = 第 N 章)
```

`/伏笔` directive 默认 `laid`;状态 `paid` 切换通过用户手编 Markdown 表(或未来 `/回收 <F-id>` directive)完成。

## 与 `伏笔.yaml` 结构化 ledger 的双轨制

| 维度 | `伏笔/伏笔表.md` (Markdown) | `伏笔.yaml` (YAML) |
|---|---|---|
| **写者** | `/伏笔` directive + 人类编辑 | 人类手编(也可 `yaml.safe_load` 出错则 fallback) |
| **读 者** | 人类阅读 / `_build_canon_block` rglob 消费 | `foreshadow_search` 工具结构化查询 |
| **格式** | Markdown 表格 | YAML 列表 `foreshadows: [{id, tags, status, ...}]` |
| **schema 校验** | LLM 工具循环自校验(不是强校验) | `foreshadow_ledger.py` 强 schema 校验 |
| **元数据** | 6 字段(id, 描述, 埋伏章, 回收章, 标签, 状态) | 6 必填字段(id, tags, status, laid_chapter, paid_chapter, notes) |

**语义对齐**:两边 ID 列必须匹配(如 `伏笔表` F1 ↔ `伏笔.yaml` `foreshadows[0].id: F1`);状态变更必须双向同步(手编时两边都改)。这是 additive 双轨(不是单 source of truth)—— 与 `L2 / L3 workflow` `chg-remove-rag` 后的人-机分层一致:人类视图 vs 工具视图可以并存,不强求单 source。

## 双线 / 推迟 / 重用场景

| 场景 | 字段处理 | 备注 |
|---|---|---|
| **双线伏笔**(同一事件在两条主角线分别出现) | 描述里写明 `双线: 张三线 + 李四线分别埋伏` | 一行容纳,不用拆 2 条 |
| **延迟回收**(埋伏后几十章才回收) | 回收章节填实际章节号;不写中途经过章节 | 让 `foreshadow_search` 的 `chapter_range` 过滤性能稳定 |
| **重复使用**(同一物件 / 角色反复触发伏笔) | 每条触发一次(独立行);description 写明 "N 次重复触发" | 让 `paid_chapter` 单一化,query 过滤时不歧义 |
| **跨卷伏笔**(第 1 卷埋伏,第 3 卷才回收) | 回收章节用「第 3 卷 X 章」格式 | 与 `chapter-format.md` 卷章编号约定一致 |
| **回收但隐藏**(回收后读者不知道) | 状态仍是 `paid`,描述里加 `[回收时点未明示]` | 让作者自己后续可见 |

## 反例(避免写法)

- ID 写 `F01` / `id1` / `伏笔1` —— 与 YAML `F\d+` regex 不匹配,`query_ledger(id=...)` 找不到。
- 章节写 `35` / `2024-03-15` / `第一百二十五章` —— 章节锚点必须是「第 X 章」格式。
- 标签写 `["男主", "身世"]` 列表形式 —— 必须是逗号分隔字符串,否则 YAML EXACT 匹配不到。
- 状态写 `LAID` / `已埋伏` 大写或中文 —— 必须是 YAML 同款小写枚举 `laid` / `paid`。
- 整段覆写 `伏笔/伏笔表.md`(用 `safe_write_file` 替换内容)—— 与 chg-remove-state-machine-enforcement 冲突;**必须用 `safe_edit_file` append 新行**。
- 在 `description` 字段写一整章人物小传 —— 限制 80 字以内;长背景放 `notes` / YAML 那边。
- 单一 label / 多 tag 之间空格(` 男主 , 身世 `)—— 标签解析 split 不到。

## 与下游 canon-block 的消费

- `_build_canon_block` (`prompts/context.py:119-146`) 通过 `for relative in ("大纲", "人物")` 配合 `_read_markdown_files` rglob 整篇读取 `伏笔/伏笔表.md` —— **但当前 rglob 仅在 "大纲", "人物" 两个目录里**,没有覆盖 `伏笔/`。
- 后续若要 `伏笔表.md` 进 canon-block,改 `prompts/context.py:133` 加 `"伏笔"` 即可;`/伏笔` directive 在此基础上落地后,自然打开下游使用面。

## ID 编号幂等性

- 每次 `/伏笔` 调用 = `safe_read_file` 重新扫描 → 找最大 `F<N>` → 新条目 = `F<N+1>`
- 已存在 `F1, F2, F3`,下次 `/伏笔` → `F4`
- **禁止 LLM 自行跳号**(如已有 5 条就直接给 `F6`,允许);但 LLM 应**避免**回填 / 覆盖已有 ID
- 用户手编冲突时(已有 F4 却再来个 F4 描述)LLM 应跳到下一个未占用 ID(`F5`)并在 TextChunk 提示
