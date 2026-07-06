"""Project-scoped FAISS retrieval for writer projects.

This MVP intentionally uses a deterministic local embedding so tests and
offline writing sessions do not depend on an external embedding API. The
``ProjectRagIndex`` API is small enough to swap the embedding implementation
later without touching tools or workflows.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

INDEX_DIRS = ("outline", "characters", "manuscript")


@dataclass(frozen=True)
class RagHit:
    """One retrieved project chunk."""

    text: str
    source: str
    score: float | None = None


class HashEmbeddings(Embeddings):
    """Small deterministic embedding based on hashed Chinese-friendly tokens."""

    def __init__(self, *, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class ProjectRagIndex:
    """Build and query a project-local FAISS index."""

    def __init__(self, project_root: Path, *, embeddings: Embeddings | None = None) -> None:
        self.project_root = project_root.resolve()
        self.embeddings = embeddings or HashEmbeddings()

    def query(self, query: str, *, k: int = 5) -> list[RagHit]:
        docs = collect_project_documents(self.project_root)
        if not docs:
            return []

        index = FAISS.from_documents(docs, self.embeddings)
        results = index.similarity_search_with_score(query, k=min(k, len(docs)))
        return [
            RagHit(
                text=document.page_content,
                source=str(document.metadata.get("source", "")),
                score=float(score),
            )
            for document, score in results
        ]


def collect_project_documents(project_root: Path) -> list[Document]:
    """Collect chunked markdown/txt documents from the supported project dirs."""

    root = project_root.resolve()
    documents: list[Document] = []
    for dirname in INDEX_DIRS:
        base = root / dirname
        if not base.exists():
            continue
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in files:
            if not _is_indexable_file(root, path):
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            relative = path.relative_to(root).as_posix()
            for idx, chunk in enumerate(split_chinese_markdown(text)):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={"source": relative, "chunk": idx},
                    )
                )
    return documents


def split_chinese_markdown(text: str, *, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """Split prose on markdown and Chinese punctuation before hard wrapping."""

    pieces = [
        piece.strip()
        for piece in re.split(r"(?=\n#{1,4}\s)|\n\s*\n|(?<=[。！？!?])", text)
        if piece.strip()
    ]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n{piece}".strip() if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = piece
        while len(current) > chunk_size:
            chunks.append(current[:chunk_size])
            current = current[chunk_size - overlap :]
    if current:
        chunks.append(current)
    return chunks


def format_hits(hits: list[RagHit]) -> str:
    if not hits:
        return "未检索到相关资料。"
    return "\n".join(f"- {hit.source}: {hit.text}" for hit in hits)


def _is_indexable_file(root: Path, path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
        return False
    relative = path.relative_to(root)
    return not any(part.startswith(".") for part in relative.parts)


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", lowered)
    bigrams = [lowered[idx : idx + 2] for idx in range(max(len(lowered) - 1, 0))]
    return words + bigrams


__all__ = [
    "HashEmbeddings",
    "ProjectRagIndex",
    "RagHit",
    "collect_project_documents",
    "format_hits",
    "split_chinese_markdown",
]
