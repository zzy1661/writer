"""轻量级文本分析工具。

Wordcount 使用与备忘 13 参考代码相同的启发式：统计非空白码点。
这对于中文散文大致合理（每个字符约 1 字）；中英混合时也能得到
可用的估算。

``ProjectSearch`` 是 Claude Code 风格 Grep 的对等物：在项目树上
做行级子串匹配，没有 embedding、没有 RAG 兜底。RAG 兜底在
``chg-remove-rag`` 中被移除，因为占位的 ``HashEmbeddings`` 在真实
查询上的召回率几乎为零；结构化 ledger + 章节摘要现在覆盖了原本
由 RAG 填补的空缺。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from writer.tools.protocol import ToolResult

if TYPE_CHECKING:
    from writer.tools.runtime import ToolRuntime


class Wordcount:
    """估算一段文本或项目文件树的字数。"""

    name = "wordcount"
    description = "统计文本或项目路径的粗略字数(剔除空白);适合中文小说草稿。"

    def run(
        self,
        runtime: ToolRuntime,
        *,
        text: str | None = None,
        path: str | None = None,
    ) -> ToolResult:
        if path is not None:
            target = runtime.safe_path(path)
            try:
                if target.is_dir():
                    texts = [
                        file.read_text(encoding="utf-8")
                        for file in _iter_text_files(target)
                    ]
                    text = "\n".join(texts)
                else:
                    text = target.read_text(encoding="utf-8")
            except (PermissionError, OSError) as exc:
                # Per arch-optimizer M6（2026-07-07）：把 I/O 错误暴露为
                # ToolResult，而不是让它们冒泡到引擎的 ``except Exception``
                # 分支。与 ``ProjectSearch`` 处理 ``UnicodeDecodeError``
                # 的方式对称。
                return ToolResult(
                    output=f"读取失败: {exc}",
                    metadata={"path": path, "error": "io"},
                )

        if text is None:
            text = ""

        stripped = text.replace("\n", "").replace(" ", "").replace("\t", "")
        chars = len(stripped)
        return ToolResult(
            output=str(chars),
            metadata={"chars": chars, "raw_len": len(text), "path": path},
        )


class ProjectSearch:
    """通过行级子串匹配搜索项目文本（Grep 对等物）。"""

    name = "project_search"
    description = "在项目目录内搜索关键词;返回匹配文件、行号和片段。"

    def run(
        self,
        runtime: ToolRuntime,
        *,
        query: str,
        path: str = ".",
        limit: int = 20,
    ) -> ToolResult:
        keyword = query.strip()
        if not keyword:
            return ToolResult(output="请提供搜索关键词。", metadata={"matched": 0})

        target = runtime.safe_path(path)
        files = [target] if target.is_file() else list(_iter_text_files(target))
        exact_lines: list[str] = []

        for file in files:
            try:
                content = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except (PermissionError, OSError) as exc:
                # Mirror arch-optimizer M6（2026-07-07）决策：把 I/O 错误
                # 暴露为 ToolResult，而不是中断本轮。原代码会让这些
                # 异常冒泡到引擎的外层 ``except Exception`` 分支。
                exact_lines.append(
                    f"<io error: {file.relative_to(runtime.project_root).as_posix()}: {exc}>"
                )
                continue

            for line_no, line in enumerate(content.splitlines(), start=1):
                if keyword not in line:
                    continue
                relative = file.relative_to(runtime.project_root)
                snippet = line.strip()
                exact_lines.append(f"{relative.as_posix()}:{line_no}: {snippet}")
                if len(exact_lines) >= limit:
                    return ToolResult(
                        output="\n".join(exact_lines),
                        truncated=True,
                        metadata={
                            "matched": len(exact_lines),
                            "query": keyword,
                            "truncated": True,
                        },
                    )

        output = (
            "\n".join(exact_lines)
            if exact_lines
            else f"未找到关键词：{keyword}"
        )
        return ToolResult(
            output=output,
            metadata={
                "matched": len(exact_lines),
                "query": keyword,
                "truncated": False,
            },
        )


def _iter_text_files(root: Path) -> list[Path]:
    suffixes = {".md", ".txt"}
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            files.append(path)
    return files


__all__ = ["ProjectSearch", "Wordcount"]
