# RAG 与检索实现方案

## 问题

本项目的 RAG 和检索怎么做?

## 业务背景

Writer Agent 要支撑 20-50 万字长篇小说写作。每次 `/写作`、`/审核`、`/改`、`/跨审` 都必须自动取到当前任务所需资料,包括大纲、目录、人物、世界观、伏笔、史实和前文摘要。

## 技术难点

长篇小说的上下文资料既多又分散。单纯向量检索可能漏掉人物名、伏笔 ID、章节号这类精确信号;单纯关键词检索又找不到语义相关内容。检索结果还需要按角色预算裁剪,不能把所有材料都塞给模型。

## 解决方案

采用“结构化定位 + 关键词检索 + 向量检索 + 动态补充”的混合检索:

1. 结构化定位:根据章节 ID 读取 `目录/目录.md` 和 `大纲/大纲.md` 中对应章节。
2. 关键词检索:用人物名、地点、伏笔 ID、物品名做 BM25 或简单倒排召回。
3. 向量检索:用 FAISS 检索语义相关的大纲、人物、世界观、史实片段。
4. 动态补充:当前章涉及待回收伏笔、新人物、卷首章、上一章悬念时,强制追加完整条目。
5. Token 裁剪:由 `prep_context` 按角色预算裁剪,写入 `ContextPack`。

## 最小化伪代码

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContextPack:
    chapter_id: str
    canon_block: str
    persona_block: str
    world_block: str
    foreshadow_block: str
    history_block: str
    previous_summary_block: str
    token_audit: dict[str, int]


class RagRetriever:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def query(self, index_name: str, query: str, k: int = 5) -> list[str]:
        # 实现期替换为 FAISS + BM25 混合检索。
        return []


def build_context_pack(project_root: Path, chapter_id: str, task: str) -> ContextPack:
    retriever = RagRetriever(project_root)

    outline_chunks = retriever.query("canon", chapter_id, k=4)
    persona_chunks = retriever.query("personas", task, k=4)
    world_chunks = retriever.query("world", task, k=3)
    foreshadow_chunks = retriever.query("foreshadow", chapter_id, k=5)
    history_chunks = retriever.query("history", task, k=3)

    topup_chunks = collect_required_topups(project_root, chapter_id)

    return ContextPack(
        chapter_id=chapter_id,
        canon_block="\n\n".join(outline_chunks),
        persona_block="\n\n".join(persona_chunks),
        world_block="\n\n".join(world_chunks),
        foreshadow_block="\n\n".join(foreshadow_chunks + topup_chunks),
        history_block="\n\n".join(history_chunks),
        previous_summary_block=load_previous_summaries(project_root, chapter_id),
        token_audit={},
    )


def collect_required_topups(project_root: Path, chapter_id: str) -> list[str]:
    # 例如:如果当前章是 F003 的回收章,强制加入 F003 完整条目。
    return []


def load_previous_summaries(project_root: Path, chapter_id: str) -> str:
    return ""
```

## 核心依赖版最小代码

```python
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter


def build_canon_index(project_root: Path) -> FAISS:
    outline = (project_root / "大纲" / "大纲.md").read_text(encoding="utf-8")
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
        ]
    )
    docs: list[Document] = splitter.split_text(outline)

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large",
        base_url="https://api.example.com/v1",
        api_key="YOUR_API_KEY",
    )
    return FAISS.from_documents(docs, embeddings)


def rag_query(index: FAISS, query: str, k: int = 5) -> list[str]:
    docs = index.similarity_search(query, k=k)
    return [doc.page_content for doc in docs]
```

## 落地建议

- 第一版可以先用结构化 Markdown 解析 + 简单关键词检索,再接 FAISS。
- 每个项目独立索引,避免不同小说互相污染。
- 章节定稿后立即生成摘要,加入 `past_chapters` 索引。
- 提供调试命令或开发开关,可查看某次 `/写作` 实际拼装了哪些上下文。

## 验收标准

- `/写作 1.8` 前自动生成该章 `ContextPack`。
- 伏笔回收章能强制带入对应伏笔完整条目。
- 检索层不直接调用写作 LLM,只负责准备材料。
- 上下文超预算时有确定裁剪顺序。
