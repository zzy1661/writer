---
command: /改
description: 修改章节内容
requires_states: [WRITING]
---

# 改 (Revise)

你是长篇小说项目的**章节修改助手**。当用户输入 `/改 <章节> <修改指令>` 时，按以下步骤应用自然语言修改指令到指定章节。

## 输入

- `/改 <chapter_id> <修改指令>` 格式的输入
- 项目根目录下 `manuscript/chapter-<chapter_id>.md` 当前内容
- 项目根目录下 `outline/toc.md` 当前章节目录
- 角色卡 `characters/` 与世界设定 `world/`

## 输出

- 在 `manuscript/chapter-<chapter_id>.md` 原地修改（in-place rewrite）或生成 side-by-side diff（用户可选）。
- 更新 `manuscript/chapter_summaries.json` 当前章节摘要。
- 不改变章节文件名与目录结构。

## 执行步骤

1. 用 `safe_read_file` 读取指定章节当前内容。
2. 用 `safe_read_file` 读取 `outline/toc.md` 该章节的大纲摘要。
3. 调 `story_agent.revise_chapter(chapter_text, edit_instruction, project_root=ctx.project_root)` 拿到修订后文本或 diff。
4. 根据用户偏好（默认 in-place rewrite）：
   - in-place：先用 `safe_edit_file(old_string=<原段>, new_string=<新段>, dry_run=True)` 让用户在 TextChunk 里预览 diff；用户确认后改 `dry_run=False` 落盘。
   - 完全重写：用 `safe_write_file(path="manuscript/chapter-<chapter_id>.md", content=<新全文>, mode="overwrite")`。
   - diff 旁路：写入 `manuscript/chapter-<chapter_id>.diff.md`（用户显式选择时）。
5. 更新 `chapter_summaries.json` 当前章节摘要。
6. yield `TextChunk` 显示变更摘要（前 N 字 + 后 N 字 + 修改点列表）。
7. yield `Done(reason="answered", payload={"chapter": <id>, "diff_lines": N, "output_path": ...})`。

## diff 输出格式参考

参考 @reference references/diff-format.md 取得 unified diff 与简洁变更摘要的输出格式。

## 边界与异常

- 指定章节不存在时 yield `SkillError("未找到章节 <chapter_id>")`。
- `revise_chapter` 抛出 `LLMRefusedError` 时（LLM 拒绝修改），回退到 in-place rewrite + 在事件流里 yield 一条警告。
- 用户只输入 `/改` 不带章节与指令时, yield 提示用户输入格式。

## 可调点

- 大改 vs 微调：可通过参数 `mode: in_place | diff` 切换。
- 修改范围：`range: <start_line>:<end_line>` 可指定行号范围。
- 锁定原文：用户可设 `--preserve-pov` 强制保持原视角。

## 当前状态

**占位** —— 等 LLM 接入 `StoryAgent.revise_chapter` 后启用。本 SKILL.md 提供完整指令模板。