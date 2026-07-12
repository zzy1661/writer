---
command: /目录
description: 生成或查看章节目录
---

# 目录 (Table of Contents)

你是长篇小说项目的**章节目录生成助手**。当用户输入 `/目录` 时，按以下步骤基于已有大纲生成细化的章节列表。

## 输入

- 项目根目录下 `outline/大纲.md` 的当前内容（前置依赖）。
- 项目根目录下 `outline/volume-plan.md`（如有，用于分卷）。
- 项目根目录下 `AGENT.md` 中的 `题材:` 行（决定章节细分粒度；本次重构后题材分支完全在 directive body 内表达）。

## 输出

- 写入 `outline/toc.md`，标题 `# <书名>`，包含 `## 章节目录` 一节。
- 每行一条章节（`# 第N章 标题` 或 `- 第N章 标题`）。
- 写入完成后刷新 `AGENT.md` 基础字段（调用 `refresh_agent_file`）。

## 执行步骤

1. 用 `safe_read_file` 读取 `outline/大纲.md`，提取四幕结构与章节标题。
2. 基于大纲结构在 LLM 响应里**直接生成**章节目录：
   - 把每条四幕拆成 3 章：开端 / 冲突 / 收束（即每个 act 标题 → "第N章 <act> · 开端 / 冲突 / 收束"）
   - 若大纲自带更细的章节，保留原章节粒度，不强行按 3 章拆分
   - **不要**调用任何 Python 端的 `draft_toc` 之类的方法——`writer.roles.StoryAgent.draft_toc` 已随 `chg-remove-roles`（2026-07-09）一起删除；LLM 是唯一的目录生成路径
3. 按下方模板格式化输出，写入 `outline/toc.md`。
4. 调 `refresh_agent_file(project_root, project_state=HAS_TOC)`。
5. yield `TextChunk` 显示前几章示例 + `Done(reason="answered", payload={"chapter_count": N})`。

## 输出模板

```
# <title>

## 章节目录

- 第 1 章：<章节标题>
- 第 2 章：<章节标题>
...
```

## 章节格式参考

参考 @reference references/chapter-format.md 取得章节标题命名规则（中文书名章节、卷-章结构等）。

## 边界与异常

- 项目根目录无 `outline/大纲.md` 时 yield `SkillError("未找到大纲文件，请先执行 /大纲 <创意>")`。
- 大纲内容为空时，提示用户重新生成大纲。
- 已存在 `outline/toc.md` 时提示用户将覆盖。

## 可调点

- 项目想用"分卷"结构（卷 1 / 卷 2）时，可在 toc.md 头部加 `## 分卷` 节。
- 玄幻/历史题材常用"卷-章"（如"卷一·崛起 第1章 退婚"），可在生成章节后用 regex 加工。
- 没有 LLM（rule-only 部署）时也照常按"每幕 3 章：开端/冲突/收束"模板产出，章节标题由 LLM 工具循环与用户输入共同决定。