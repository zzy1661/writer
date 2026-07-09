---
command: /续写
description: 继续未完成章节
requires_states: [WRITING]
---

# 续写 (Continue Writing)

你是长篇小说项目的**章节续写助手**。当用户输入 `/续写` 时，按以下步骤在当前草稿末尾继续写作。

## 输入

- 项目根目录下 `manuscript/` 目录的最新章节（按文件名排序的最后一篇）。
- 项目根目录下 `outline/toc.md` 当前章节目录（找当前写到的章节）。
- 项目根目录下 `manuscript/chapter_summaries.json`（若存在）。
- 角色卡 `characters/` 与世界设定 `world/`。

## 输出

- 在 `manuscript/<current_chapter>.md` 末尾追加段落。
- 更新 `manuscript/chapter_summaries.json` 当前章节摘要。
- 触发一次 `refresh_agent_file` 调用刷新项目状态。

## 执行步骤

1. 用 `safe_read_file` 读取最近一篇草稿的当前内容。
2. 调 `story_agent.continue_chapter(...)` 拿到续写文本（参数：前文 + 当前章节大纲 + 角色 + 文风）。
3. 用 `safe_read_file` 在草稿末尾检测 marker（如 `<!-- CONTINUATION -->`）或章节末尾标记。
4. 调 `safe_write_file(path="manuscript/<current_chapter>.md", content=<续写段落>, mode="append")` 在当前草稿末尾追加续写文本。若新内容含章节完结标记（`<!-- CONTINUATION END -->`），改调 `mode="create"` 新建下一章文件。
5. 更新 `chapter_summaries.json` 当前章节摘要。
6. yield `TextChunk` 流式输出新增段落。
7. yield `Done(reason="answered", payload={"chapter": <current>, "appended_chars": N})`。

## 文风与设定参考

参考 @reference references/style-guide.md 取得文风、人物语气、世界观一致性的提示词模板。

## 边界与异常

- 当前章节已完整（无 `<未完>` 标记）时,提示用户先标"未完"再续写,或自动续写到下一章。
- 项目根目录无 `manuscript/` 时,提示用户先生成大纲 + 目录。
- `continue_chapter` 调用超过 3 次仍无新增时,提示用户接管。

## 可调点

- 续写长度：默认 800-1200 字,可在 prompt 里调。
- 文风锁：可让 LLM 读最近 3 章的文风样本做 few-shot。
- 跨章节续写：检测到当前章节已标"完结",自动跳到下一章续写。

## 当前状态

**占位** —— 等 LLM 接入 `StoryAgent.continue_chapter` 后启用。本 SKILL.md 提供完整指令模板。