# 长篇上下文管理与 RAG 检索

## 业务背景

项目目标是辅助生成 20-50 万字长篇小说。章节越多,人物、伏笔、世界观、过往剧情越难一次性放入模型上下文,但写作又必须遵循全书正典。

## 技术难点

长篇写作的上下文既要全面,又要受 token 限制。只喂近几章会遗忘远期伏笔和人物弧光;全量喂正文会超预算、成本高、噪声大。不同节点的需求也不同:写正文需要前文节奏,校对需要当前正文,历史顾问需要史实索引。

## 解决方案

采用 `prep_context` 前置节点,主节点不直接检索。上下文由静态骨架 + 动态 RAG top-up 组成:

- 静态骨架:角色 prompt、输出格式、当前任务。
- 正典检索:大纲、人物、世界观、伏笔、史实。
- 金字塔记忆:近 3 章详细摘要,中期章节简摘要,远期只保留人物/伏笔/信物状态。
- top-up:当章节涉及待回收伏笔、新人物、卷首章、重大信物时补充完整条目。

索引按项目隔离,FAISS 存向量索引,BM25 负责关键词补召回。

## 最小 demo / 伪代码

```python
from dataclasses import dataclass


@dataclass
class ContextPack:
    chapter_id: str
    canon: list[str]
    personas: list[str]
    world: list[str]
    foreshadows: list[str]
    summaries: list[str]


def prep_context(chapter_id: str, task: str) -> ContextPack:
    canon = rag_query(index="canon", query=chapter_id, k=4)
    personas = rag_query(index="personas", query=task, k=4)
    world = rag_query(index="world", query=task, k=3)
    foreshadows = rag_query(index="foreshadow", query=chapter_id, k=5)
    summaries = load_pyramid_summaries(chapter_id)

    # top-up:命中硬规则时强制补充完整资料,不依赖相似度排序。
    if is_reveal_chapter(chapter_id):
        foreshadows.extend(load_required_foreshadows(chapter_id))

    return trim_to_budget(
        ContextPack(chapter_id, canon, personas, world, foreshadows, summaries),
        budget_tokens=30_000,
    )
```

## 核心依赖版最小代码

```python
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tiktoken


def split_chinese_markdown(text: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n## ", "\n### ", "\n\n", "。", "！", "？", "\n"],
        chunk_size=800,
        chunk_overlap=120,
    )
    return splitter.create_documents([text])


def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    encoder = tiktoken.encoding_for_model(model)
    return len(encoder.encode(text))


def trim_blocks_to_budget(blocks: list[str], max_tokens: int) -> list[str]:
    selected: list[str] = []
    used = 0
    for block in blocks:
        cost = count_tokens(block)
        if used + cost > max_tokens:
            break
        selected.append(block)
        used += cost
    return selected
```

## 落地建议

- 新增 `ContextPack` 类型,包含 `system_block`、`canon_block`、`history_block`、`task_block`、`token_audit`。
- `prep_context` 负责预算裁剪,主写作节点只读取 `state.context`。
- 章节定稿后生成 `chapter_summaries.json`,不要把历史正文原文直接塞给模型。
- 中文分块优先按标题、段落、句号、问号、叹号切分,避免硬切断语义。

## 验收标准

- 写第 30 章时仍能检索到第 3 章埋下的相关伏笔。
- 上下文超预算时系统按固定顺序压缩,不会随机丢弃关键正典。
- 每次上下文拼装都有 token 审计记录。
- 主 Agent 节点不包含检索细节,便于后续替换 RAG 实现。
