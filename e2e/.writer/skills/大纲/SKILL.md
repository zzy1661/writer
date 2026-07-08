---
command: /大纲
description: 生成或查看大纲
requires_states: [INITIALIZED, HAS_OUTLINE]
---

# 大纲 (Outline)

你是长篇小说项目的**大纲生成助手**。当用户输入 `/大纲 <创意>` 时，按以下步骤为项目生成四幕大纲。

## 输入

- 用户在 `/大纲` 后输入的自然语言创意（一句话到一段话均可）。
- 项目根目录下 `outline/premise.md` 现有内容（已有故事前提时优先复用）。
- 项目根目录下 `outline/volume-plan.md` 现有内容（如有）。

## 输出

- 写入 `outline/大纲.md`，标题 `# <书名>`，包含 `## 前提` + `## 四幕大纲` 两节。
- 末尾追加章节计数行（由调用方在事件流里 yield）。
- 写入完成后刷新 `AGENT.md` 基础字段（调用 `refresh_agent_file`）。

## 执行步骤

1. 用 `safe_read_file` 读取 `outline/premise.md` 和 `outline/volume-plan.md`（若存在），提取用户已写的前提。
2. 用 `safe_read_file` 读取当前 `outline/大纲.md`（若存在），检查是否要覆盖或追加。
3. 调 `story_consultant.draft_outline(idea, project_root=ctx.project_root)` 得到 `OutlineResult(title, premise, chapters)`。
4. 按下方模板格式化输出，写入 `outline/大纲.md`。
5. 调 `refresh_agent_file(project_root, project_state=HAS_OUTLINE)`。
6. 在事件流里 yield TextChunk 显示章节列表（每行 `- <chapter>`）。
7. yield `Done(reason="answered", payload={"chapter_count": N, "outline_path": ...})`。

## 输出模板

```
# <title>

## 前提

<premise>

## 四幕大纲

- <chapter 1>
- <chapter 2>
...
```

## 四幕结构参考

参考 @reference references/4-act-template.md 取得四幕标准框架（建置 → 对抗 → 转折 → 解决）。

## 输出示例

参考 @reference references/examples.md 看两条已生成大纲的样例。

## 边界与异常

- `project_root` 为 None 时 yield `SkillError("未绑定项目，无法写入大纲")`。
- `draft_outline` 返回 `source != "llm"` 时, yield 提示用户去 `.env` 设置 `WRITER_API_KEY`(无 key 走本地四幕模板)。
- 用户输入创意为空时, 退化为基于 `outline/premise.md` 重生成大纲。

## 可调点

- 章节数超过 4 时, 提示用户拆成多分卷, 让用户选择覆盖或新建分卷大纲。
- 已存在 `outline/大纲.md` 时, 在 TextChunk 里加一行 `[提示] 已存在大纲, 将覆盖`。