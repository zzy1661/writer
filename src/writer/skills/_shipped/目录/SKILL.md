---
command: /目录
description: 根据 AGENT.md 题材与架构方法及大纲生成章节目录
---

# 目录 (Table of Contents)

你是长篇小说项目的**章节目录生成助手**。当用户输入 `/目录` 时，**先读 `AGENT.md`** 与 `大纲/大纲.md` 拿到题材、架构方法、总字数 / 总章数、分卷与章节骨架，再按既定骨架生成细化章节目录。

> per 2026-07-16 落地：`/目录` 与 `/大纲` 同样消费 `AGENT.md` 的多行字段，并在执行过程中把总字数、总章数、分卷回写。`/目录` 是 `/大纲` 的下游衍生：必须有 `大纲.md` 才有意义。

## 输入

- 用户 `/目录` 后输入的自然语言（可夹带预计字数 / 分卷数，例如 `/目录 30万字`、`/目录 30万字 3卷`）。
- 项目根目录下 `大纲/大纲.md`（**前置依赖**，由 `/大纲` 落地；缺失时直接报错并提示先跑 `/大纲`）。
- 项目根目录下 `大纲/分卷规划.md`（如有，进一步约束分卷）。
- 项目根目录下 `AGENT.md` 的**五条关键字段**：
  - `题材:` 行 —— 决定节拍前缀（`other` / `历史` / `言情` / `玄幻`）。
  - `架构方法:` 行 —— 决定章节骨架展开方式（雪花法 / 三幕结构 / 英雄之旅等）；缺省回退到 `雪花法`。
  - `预计总字数:` 行 —— 直接决定 `总章数 = ceil(预计总字数 / 3000)`；缺省时按用户 `/目录` 后 input 推断（`30万字` → 30 万），再缺就 `SkillError` 报错。
  - `预计总章数:` 行 —— 已设定则**跳过字数计算**，直接使用现值，覆盖本次调用。
  - `分卷:` 行 —— 已设定则跳过**分卷推荐**，直接按现值生成（如 `卷一(20章)/卷二(40章)`）。

## 输出

- 写入 `大纲/章节目录.md`，按所选题材与架构方法给出单层 / 双层 / 三层卷-章结构。
- **同时写回 `AGENT.md`**：调 `update_agent_total_words_line` / `update_agent_total_chapters_line` / `update_agent_volumes_line`（`project/state.py` 新增的三个 helper）局部更新对应三行。`refresh_agent_file` 也会读这三行并在状态切换时保留下来。
- 写入完成后调用 `refresh_agent_file(project_root)` 刷新 `state:` 与 `label:`（自动保留题材/架构方法/三行新字段）。
- 末尾 yield `Done(reason="answered", payload={"chapter_count": N, "volume_split": "<text>", "total_words": <int>, "total_chapters": <int>, "genre": "<题材>", "architecture_method": "<方法>", "toc_path": "大纲/章节目录.md"})`。

## 执行步骤

### 1. 读项目现状

用 `safe_read_file` 同时读 `AGENT.md` 与 `大纲/大纲.md`：

- `大纲/大纲.md` 不存在 / 空 → 直接 yield `SkillError("未找到大纲文件，请先执行 /大纲 <创意>")` 并跳过目录生成；这是 `/目录` 的**前置依赖**。
- `AGENT.md` 不存在 / 不可读 → 与 `/大纲` 行为一致，题材回退 `other`，架构方法回退 `雪花法`，三行新字段全部为 `None`。

### 2. 处理 AGENT.md 元数据

按规则设置或读取**五条字段**：

| 字段 | 来源 | 缺失处理 |
|---|---|---|
| `题材:` | `read_genre_from_agent`；缺省回退 `other` | 用户 input 里夹带题材提示，或通过 TextChunk 询问后调 `update_agent_genre_line` 写回 |
| `架构方法:` | `read_architecture_method_from_agent`；缺省回退 `雪花法` | 同上：调 `update_agent_architecture_method_line` 写回 |
| `预计总字数:` | `read_total_words_from_agent`；缺省 `None` | 优先 user_input 末尾的 `<N>万字 / <N>千字 / <N>字`，否则 TextChunk 问，答后调 `update_agent_total_words_line` 写回 |
| `预计总章数:` | `read_total_chapters_from_agent`；缺省 `None` | 若已设定，**跳过字数计算**直接用现值；否则按 `ceil(预计总字数 / 3000)` 推算 |
| `分卷:` | `read_volumes_from_agent`；缺省 `None` | 用户 input 末尾 `<N>卷` 时按题材默认卷长均分；否则参考 @reference references/volume-strategy.md 计算推荐分卷并在 TextChunk 询问用户是否采用 |

#### 2a. 用户已经在 `/目录` 后提供了字数 / 分卷（user_input 末尾提示）

形如 `/目录 30万字`、`/目录 30万 3卷`、`/目录 600章`：

- 提取数字与单位，写入对应行后**直接进入步骤 3**，不再追问。
- 输入同时含 `<N>卷` 时，按题材默认卷长均分（如 `玄幻+三步八段式 → 7 卷×16 章 = 112 章`），跳过 2c 的"推荐分卷"提问。

#### 2b. 缺题材 / 架构方法时

yield TextChunk 询问用户：「你的作品题材是什么？历史 / 言情 / 玄幻 / other 选一，外加架构方法：雪花法（默认）/ 三幕结构 / 英雄之旅 / 三步八段式 / 布莱克节拍表 / 人物弧光 / 起承转合 / 自创」；用户下一轮 input 答完后调 `update_agent_genre_line` / `update_agent_architecture_method_line` 写回 AGENT.md。

#### 2c. 缺分卷时（已选定题材/方法/字数）

按 @reference references/volume-strategy.md 速选表计算**推荐分卷**（玄幻长篇建议 7 卷、历史长篇 4 卷、言情 3 卷等），在 TextChunk yield：

```
[建议分卷] 玄幻 + 雪花法 + 30 万字 → 推荐 3 卷：卷一(40 章)/卷二(30 章)/卷三(30 章)
[确认分卷] 是否采用此分卷？回复 yes 接受 / yes-不均分 <章数列表> / no 重排 / 默认 yes-不均分时填入分卷规划.md
```

- `yes` → 写 AGENT.md `分卷:` 行，调 `update_agent_volumes_line`。
- `yes-不均分 <章数列表>`（如 `yes-不均分 35 32 33`）→ 解析后写 AGENT.md。
- `no` / 长答理由 → 不写 AGENT.md `分卷:` 行，章节生成仍走单卷排布。
- 缺省 / 用户沉默超过本轮 → 沿用**单卷不分卷**（不写 `分卷:`），不影响后续 `/创作`。

### 3. 计算章节总数

- 若 `预计总章数:` 已存在 → 直接用，**跳过字数计算与除 3000 公式**。
- 否则：`总章数 = ceil(预计总字数 / 3000)`；最小 10 章（短篇下限），不设上限。
  - 例：30 万字 → 100 章；50 万字 → 167 章；100 万字 → 334 章。
- 把 `预计总章数` 写回 AGENT.md（`update_agent_total_chapters_line`）。

### 4. 按题材 + 架构方法展开章节骨架

> **题材是节拍层，架构方法是骨架层** —— 两者正交。

#### 4a. 题材前缀（来自 `大纲.md`，与 `/大纲` 对齐）

- `other` → 四幕模板：每个 act 标题 → 「第 N 章 <act> · 开端/冲突/收束」。
- `历史` → 章节用「史实: ... | 虚构: ...」格式（5 段：前期铺垫 / 第一转折 / 中盘深化 / 代价升级 / 终局落幕）。
- `言情` → 章节用「节拍<N>」前缀（9 段：相遇 → 吸引 → 暧昧 → 误会 → 内部障碍 → 分离 → 自我觉醒 → 表白/和解 → 余韵）。
- `玄幻` → 章节用「境界<N> <境界名>: ...」前缀（5 段：炼气 → 筑基 → 金丹 → 元婴 → 化神）。

#### 4b. 架构方法骨架（与 `/大纲` 中 "目录展开" 子句对齐）

- `雪花法`（默认）→ **四段式短梗概 / 章节长梗概 / 主要人物小传** 三层，按"章节长梗概（按幕划分）"小节展开。
- `三幕结构` → **第一幕·铺垫 25% / 第二幕·对抗 50% / 第三幕·结局 25%**，对应章数 0.25N / 0.5N / 0.25N。
- `英雄之旅` → **12 阶段**（平凡世界 → 召唤 → 拒绝 → 导师 → 跨越 → 试炼 → 接近洞穴 → 终极考验 → 获取奖励 → 归途 → 携赐回归），按大段映射到章数，再细分成 N 章。
- `三步八段式` → **8 段位**（开端 / 转机 / 成长 / 冲突 / 低谷 / 蜕变 / 决战 / 收尾），每段位均分。
- `三明治` → 主线段 + 支线节点穿插（按 `references/volume-strategy.md` 的"三明治架构"段）。
- `布莱克节拍表` → 15 节拍表（开篇画面 → … → 结局画面），按节拍均分。
- `人物弧光` → **6 段弧光** + 关键关系节点；按弧光阶段均分。
- `起承转合` → 4 步极简（起 / 承 / 转 / 合 各占 25%）。
- 其他方法（含复合写法「三幕+雪花」「节拍+情感节拍」等）→ 复用 `/大纲` 的架构方法速查表（`references/architecture-methods.md`），自由组合。

#### 4c. 分卷与目录展开

- 若 `分卷:` 已设定（含 2c 的用户响应），按卷数均分章数（保留每卷最后一章作为下卷钩子），按 @reference volume-strategy.md 选用单/双/三层卷-章。
- 若未设定，单卷展开 → 用单层 `# 第N章：标题`。
- 单章标题不超过 8 个中文字符；末 1-2 章做"钩子"留悬念。

### 5. 落盘与回写

按下方模板格式化输出，写入 `大纲/章节目录.md`：

```
# <书名>

## 章节目录

- 第 1 章：<标题>
- 第 2 章：<标题>
...
```

（卷-章结构参考 @reference chapter-format.md 。）

之后顺序：

1. 调 `update_agent_total_words_line(agent_md, total_words)` —— 写回预计总字数。
2. 调 `update_agent_total_chapters_line(agent_md, total_chapters)` —— 写回预计总章数。
3. 调 `update_agent_volumes_line(agent_md, volumes_text)` —— 写回分卷（如有）。
4. 调 `refresh_agent_file(project_root)` —— 状态推进到 `HAS_TOC`，自动保留上面三行不被清空。
5. yield TextChunk 显示前 / 后各 2 章示例 + `Done(reason="answered", payload={...})`。

## 输出模板

- 单卷不分卷（参考 @reference chapter-format.md "单层编号"）：

```
# <书名>

## 章节目录

- 第 1 章：<标题>
- 第 2 章：<标题>
```

- 多卷（参考 @reference chapter-format.md "双层 / 三层卷章"）：

```
# <书名>

## 章节目录

### 第一卷：<卷主题>
- 第 1 章：<标题>
...

### 第二卷：<卷主题>
- 第 N+1 章：<标题>
...
```

## 章节格式参考

- 单/双/三层卷章示例：@reference chapter-format.md 。
- **分卷策略速查表**（按题材 + 字数推荐卷数 / 卷长）：@reference volume-strategy.md 。
- **架构方法骨架速选**：复用 `/大纲` 的 `references/architecture-methods.md`。

## 边界与异常

- `project_root` 为 None 时 yield `SkillError("未绑定项目，无法生成目录")`。
- `大纲/大纲.md` 不存在 / 空 → yield `SkillError("未找到大纲文件，请先执行 /大纲 <创意>")`，**不**生成目录；用户先跑 `/大纲`。
- `AGENT.md` 缺失 → 题材回退 `other`，架构方法回退 `雪花法`，三行新字段全部为 `None`（与 `/大纲` 同款兜底，不抛异常）。
- user_input 含不合法字数（如 `零字` / `-100`） → 按负数 / 零处理：no-op，yield TextChunk 提示「预计字数必须 > 0，请重新输入」。
- 已存在 `大纲/章节目录.md` 时：TextChunk 先 yield `[提示] 已存在章节目录.md，将覆盖`。
- 用户拒绝所有分卷 / 留空分卷 → 不写 AGENT.md `分卷:` 行，单卷展开。
- 没有 LLM（rule-only 部署）→ 走 preview 路径：TextChunk 显示 directive 元信息 + 已读的 `大纲.md` 摘要 + 推算章节数；**不**真正落盘 AGENT.md 三行（避免误写）。

## 可调点

- 单章字数默认 3000 字；用户可在 user_input 里用 `--words-per-chapter=<N>` 临时覆盖（覆盖仅本轮不写 AGENT.md）。
- 玄幻长篇可走"7 卷×16 章 = 112 章"惯例（参考 @reference volume-strategy.md 末「反例」段）；其他题材对应表格查询。
- 已 `state = HAS_TOC` / `state = WRITING` 时再跑 `/目录`：与 `/大纲` 同款不拦截，body 内判断走"覆盖 / 追加"——即根据 `大纲/章节目录.md` 是否已存在 yield 提示并清空后重写。
- `update_agent_total_words_line` / `update_agent_total_chapters_line` / `update_agent_volumes_line` 都对 `AGENT.md` 做**局部更新**（不动其它字段）；这是 `_plan_chapter_node` 落地后"局部写入"的统一契约。
