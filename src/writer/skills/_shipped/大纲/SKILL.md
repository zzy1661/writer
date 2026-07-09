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
- 项目根目录下 `AGENT.md` 中的 `题材:` 行（决定四幕模板：`other` / `历史` / `言情` / `玄幻`）。

## 输出

- 写入 `outline/大纲.md`，标题 `# <书名>`，包含 `## 前提` + `## 四幕大纲` 两节。
- 末尾追加章节计数行（由调用方在事件流里 yield）。
- 写入完成后刷新 `AGENT.md` 基础字段（调用 `refresh_agent_file`）。

## 执行步骤

1. 用 `safe_read_file` 读取 `outline/premise.md` 和 `outline/volume-plan.md`（若存在），提取用户已写的前提。
2. 用 `safe_read_file` 读取当前 `outline/大纲.md`（若存在），检查是否要覆盖或追加。
3. 用 `safe_read_file` 读取 `AGENT.md`，提取 `题材:` 行：
   - 缺失或 `other` → 走"四幕"模板：每条章节用「第一幕/第二幕/第三幕/第四幕」格式（中间可加细分）
   - `历史` → 章节用「史实: ... | 虚构: ...」格式（5 段：前期铺垫 / 第一转折 / 中盘深化 / 代价升级 / 终局落幕）
   - `言情` → 章节用「节拍<N>」前缀（9 段：相遇 → 吸引 → 暧昧 → 误会 → 内部障碍 → 分离 → 自我觉醒 → 表白/和解 → 余韵）
   - `玄幻` → 章节用「境界<N> <境界名>: ...」前缀（5 段：炼气 → 筑基 → 金丹 → 元婴 → 化神）
4. 基于用户创意 + 项目前提 + 题材模板，**直接在 LLM 响应里生成**四幕大纲种子（不是正文）。
   - **不要**调用任何 Python 端的 `draft_outline` 之类的方法——本次重构（`chg-remove-roles`，2026-07-09）已删除 `writer.roles.StoryAgent` 等所有 Python-side 题材分支类；LLM 是唯一的大纲生成路径。
   - 若项目已有 `创意/核心创意.md`，以其中的核心创意为中心展开。
5. 按下方模板格式化输出，写入 `outline/大纲.md`。
6. 调 `refresh_agent_file(project_root, project_state=HAS_OUTLINE)`。
7. 在事件流里 yield TextChunk 显示章节列表（每行 `- <chapter>`）。
8. yield `Done(reason="answered", payload={"chapter_count": N, "outline_path": ...})`。

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
- 用户输入创意为空时, 退化为基于 `outline/premise.md` 重生成大纲。
- 没有 LLM 时（rule-only 部署）也照常按上述步骤产出 4 条章节；只是 LLM 不参与扩写，章节标题由 directive body + 用户创意在 LLM 工具循环的多次 tool 调用中共同决定。

## 可调点

- 章节数超过 4 时, 提示用户拆成多分卷, 让用户选择覆盖或新建分卷大纲。
- 已存在 `outline/大纲.md` 时, 在 TextChunk 里加一行 `[提示] 已存在大纲, 将覆盖`。
- 项目想在章节里内嵌「境界:N」「节拍:N」「史实:」等题材标记时, 直接在 `- <chapter>` 行加前缀, 不要靠 Python 端 prefix 注入——本次重构后题材分支完全在 directive body 内表达。