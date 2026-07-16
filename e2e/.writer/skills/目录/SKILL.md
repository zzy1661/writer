---
command: /目录
description: 根据 AGENT.md 题材与架构方法及大纲生成章节目录
---

# 目录 (Table of Contents)

E2E fixture：根据 AGENT.md 题材 / 架构方法 / 总字数 + 大纲.md 生成章节目录。完整指令见 `src/writer/skills/_shipped/目录/SKILL.md`，本 fixture 用于 pipe-mode e2e 验证管道路由，不重复长 body 以避免污染源文件大小。

## 输入

- `/目录 [可选 <预计字数> [可选 <N>卷]]`。
- `AGENT.md` 五条字段（题材 / 架构方法 / 预计总字数 / 预计总章数 / 分卷）。
- `大纲/大纲.md`（前置依赖，由 `/大纲` 落地）。

## 输出

- 写入 `大纲/章节目录.md`，按题材 + 架构方法骨架展开。
- 回写 `AGENT.md`：`预计总字数:` / `预计总章数:` / `分卷:` 三行（局部更新）。
- 调 `refresh_agent_file(project_root)` 推进状态到 `HAS_TOC`。

## 执行步骤

1. `safe_read_file` 同时读 `AGENT.md` 与 `大纲/大纲.md`；缺失大纲直接 `SkillError` 报错。
2. 提取五条 AGENT.md 字段；缺题材 / 架构方法 / 总字数 → `TextChunk` 询问用户。
3. `总章数 = ceil(预计总字数 / 3000)`；`预计总章数:` 已设定则跳过。
4. 按题材 + 架构方法骨架展开章节 → 写入 `大纲/章节目录.md`。
5. 调 `update_agent_total_words_line` / `update_agent_total_chapters_line` / `update_agent_volumes_line`（state.py 新 helper）写回。
6. 调 `refresh_agent_file(project_root)`。

## references

- 章节标题格式与卷-章排版：@reference chapter-format.md。
- 分卷策略速查表（题材 + 字数 → 卷数 + 卷长）：@reference volume-strategy.md。
- 架构方法骨架速选：复用 `/大纲` 的 `references/architecture-methods.md`。

## 边界与异常

- `大纲/大纲.md` 缺失 → `SkillError("未找到大纲文件，请先执行 /大纲 <创意>")`。
- 用户拒绝分卷 / 留空 → 单卷展开，不写 `分卷:` 行。
- 既有 `章节目录.md` 存在 → `TextChunk` 提示将覆盖。
- rule-only 部署 → preview 路径，**不**真正落盘 AGENT.md 三行。
