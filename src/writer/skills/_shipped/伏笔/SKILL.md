---
command: /伏笔
description: 在伏笔表中添加一条伏笔(写入 伏笔/伏笔表.md)
---

# 伏笔 (Foreshadow)

你是长篇小说项目的**伏笔管理助手**。当用户输入 `/伏笔 <描述>` 时，**在 `伏笔/伏笔表.md` 末尾追加一条新的 Markdown 表格行**，自动分配下一个 `F<N>` 编号与 `laid`（已埋伏但尚未回收）状态。

> per 2026-07-17 落地：`伏笔/` 目录与 `伏笔表.md` 现在是**所有题材共有**基础脚手架（不再专属玄幻）；`/伏笔` directive 是它的写入入口，与 `tools/builtin/foreshadow_search.py` 使用的结构化 `伏笔.yaml` ledger 是**两套并行**：本 directive 写人类可编辑的 Markdown 表，工具读 YAML 结构化查询。

## 输入

- 用户在 `/伏笔` 后输入的自然语言伏笔描述（一句话到一段话均可）；可附带「埋伏章节 / 回收章节 / 标签」提示。
- 项目根目录下 `伏笔/伏笔表.md` 现有 Markdown 表格（用于查 `F<N>` 最大编号）。
- 项目根目录下 `伏笔.yaml` ledger（per 备注：本 directive **不读** YAML,也不会**写** YAML —— 用户后续可手编 YAML 与本表对齐）。
- 项目根目录下 `大纲/大纲.md` + `大纲/章节目录.md`（用于章节锚点校验：「埋伏章节」必须用 `第 X 章` / `第 X 卷 Y 章` 格式）。

## 输出

- 在 `伏笔/伏笔表.md` 末尾追加一行 Markdown 表格行，6 字段顺序：`| ID | 描述 | 埋伏章节 | 回收章节 | 标签 | 状态 |`
- 写入完成后 yield `Done(reason="answered", payload={"foreshadow_id": "F<N>", "row": "...", "path": "伏笔/伏笔表.md"})`。

## 执行步骤

1. 用 `safe_read_file("伏笔/伏笔表.md")` 取现有表内容；若文件缺失或没表（项目刚创建仅有 stub），视为仅有表头，从 `F1` 起步。
2. 用正则 `^F(\d+)\s+\|` 或 `\|\s+F(\d+)\s+\|` 扫描找出**最大 `F<N>` 编号**；新条目编号 = `F<N+1>`。
3. 解析用户描述抽取 6 字段：
   - `描述`（必填）：用户原文即可；若空则提示用户补充。
   - `埋伏章节`（必填）：用「第 X 章」/「第 X 卷 Y 章」格式；若用户没说,写 `未知`,但提示用户在事件流里建议补。
   - `回收章节`（可选）：未指定写 `未知`。
   - `标签`（可选）：逗号分隔关键词,例如 `男主,身世,伏剑`；未指定写 `未分类`。
   - `状态`（默认 `laid`）：用户说「已回收」/「回收完毕」用 `paid`；否则默认 `laid`。
4. ID（`F<N+1>`）按规范生成，与 YAML 那边 `F\d+` regex 兼容（人类手编 YAML 时也能 link）。
5. 用 `safe_edit_file` 在 `伏笔/伏笔表.md` 末尾追加一行（**禁止用 `safe_write_file` 整段覆写** —— 与 chg-remove-state-machine-enforcement 同款）：
   - 先 `safe_read_file` 取现有最后一行,确保换行符正确（表头后第一行用空行隔开；append 模式只追加新行）。
6. 在事件流 yield TextChunk 显示新行 + 提示「可同时编辑 `伏笔.yaml` 与之对齐」。
7. yield `Done(reason="answered", payload={"foreshadow_id": "F<N+1>", "row": "<new markdown row>", "path": "伏笔/伏笔表.md", "action": "create"})`。

## 输出模板

新追加的一行模板（单行,无尾换行问题）：

```
| F<N+1> | <描述> | 第 X 章 | 第 Y 章 / 未知 | <tag1,tag2> | laid |
```

完整 `伏笔/伏笔表.md` 后续样例（由本 directive + 用户多次调用累积）：

```markdown
# 伏笔表

| ID | 描述 | 埋伏章节 | 回收章节 | 标签 | 状态 |
|----|------|---------|---------|------|------|
| F1 | 张三左手伤疤来历 | 第 3 章 | 未知 | 男主,身世 | laid |
| F2 | 神秘玉佩到底是哪一派的 | 第 7 章 | 第 25 章 | 信物,女主 | laid |
| F3 | 老皇帝驾崩真相 | 第 12 章 | 第 30 章 | 朝局,权谋 | laid |
| F4 | 张三深夜独自写日记 | 第 18 章 | 第 18 章 | 男主,自省 | paid |
```

## 字段填写指南

参考 @reference foreshadow-schema.md 取得 6 字段的详细规则：
- id 编号规则（连续 + F\d+ 模式兼容 YAML）
- 章节锚点格式要求（与 `_build_canon_block` rglob 整篇一致）
- 标签推荐（与已有 YAML ledger 的 `tags` 字段对齐）
- 状态值 `laid` / `paid` 与 YAML 同款
- 附加信息（双线 / 重复使用 / 推迟回收等场景）

## 边界与异常

- **同 chg-remove-state-machine-enforcement 语义**：禁止整段覆写 `伏笔/伏笔表.md`,update 路径必须先 `safe_read_file` 读原文再 append 新行。
- `project_root` 为 None 时 yield `SkillError("未绑定项目，无法写入伏笔表")`。
- ID 冲突：`safe_read_file` 找出的最大 `F<N>` 已包含刚写过的行号时,本 directive 应当幂等（每次重扫描,不影响);冲突时（人工手编了同 ID）让 LLM 自动跳过到下一个未占用 ID。
- 没有 LLM（rule-only 部署）走 preview 路径：TextChunk 显示 directive 元信息（command、description、body 长度、references 列表),不真正落盘。
- 不写 `伏笔.yaml` ledger —— 该 YAML 由 `foreshadow_search` 工具消费,本 directive 不接管；用户手编 YAML 时建议与本表对齐（YAML 的 id 与本表 ID 列保持一致）。
- 重复关键词:同一描述伏笔不应存在两次；若 `safe_read_file` 扫描时发现已有 90% 文本相似的描述,提示用户「可能重复」并在 TextChunk 里给出已有 ID,让用户走 update 路径（手动通过 `safe_edit_file` 改状态）。

## 可调点

- 用户后续回收伏笔：手动编辑 `伏笔/伏笔表.md` 把状态列改 `paid` 并填回收章节,或待未来 `/回收 <F-id>` directive 上线。
- 项目想自定义 6 字段(增加 "引用章节 / 重要程度" 等列),在表格 header 与每条 row 同步修改即可,不影响本 directive 主路径（LLM 工具循环读 body 适配新列）。
- 多题材项目共用 `伏笔/伏笔表.md` —— 本 directive 不区分题材;题材标签写到「标签」列即可。
- 索引文件 `人物/主要人物.md` 同款:`伏笔/伏笔表.md` 是**人类编辑层**;`伏笔.yaml` 是**工具查询层**;两者由用户手编对齐。
