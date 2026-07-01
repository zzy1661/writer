# 核心 Tool 设计

## 问题

本项目的核心 Tool 是哪些?

## 业务背景

Agent 需要读写项目文件、解析大纲和目录、定位章节、登记草稿、更新伏笔、统计字数、构建上下文、必要时向用户询问选择或文本。

## 技术难点

Tool 不能只是文件读写函数。它们必须表达写作项目的业务语义,例如“登记章节草稿”“追加修订记录”“更新伏笔状态”。否则 LLM 会直接编辑 Markdown,带来格式破坏和状态不一致。

## 核心 Tool 清单

文件与状态类:

- `read_file`
- `write_file`
- `append_file`
- `list_dir`
- `read_agent_state`
- `update_agent_state`

写作项目类:

- `parse_outline`
- `parse_toc`
- `chapter_locate`
- `chapter_register`
- `append_revision_record`
- `wordcount`

RAG 与一致性类:

- `build_context_pack`
- `rag_query`
- `persona_search`
- `foreshadow_query`
- `foreshadow_update`
- `consistency_check`

用户交互类:

- `ask_user_choice`
- `ask_user_text`
- `confirm_action`

## 最小化代码

```python
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool


PROJECT_ROOT = Path.cwd().resolve()


def ensure_in_project(path: Path) -> Path:
    resolved = path.resolve()
    if PROJECT_ROOT not in [resolved, *resolved.parents]:
        raise PermissionError(f"路径不在项目内: {resolved}")
    return resolved


@tool
def read_file(path: str) -> str:
    """读取项目内文件。"""
    safe_path = ensure_in_project(PROJECT_ROOT / path)
    return safe_path.read_text(encoding="utf-8")


@tool
def append_revision_record(message: str) -> str:
    """向 大纲/大纲.md 顶部追加修订记录。"""
    outline_path = ensure_in_project(PROJECT_ROOT / "大纲" / "大纲.md")
    old = outline_path.read_text(encoding="utf-8")
    new = old.replace("## 修订记录\n", f"## 修订记录\n\n- {message}\n", 1)
    outline_path.write_text(new, encoding="utf-8")
    return "ok"


@tool
def chapter_locate(chapter: str | None = None) -> dict:
    """把 1.3、卷一第三章、章节标题解析为标准章节。"""
    return {
        "chapter_id": chapter or "1.1",
        "title": "待实现",
        "draft_path": "正文草稿/卷1_第1章_待实现.md",
    }


@tool
def chapter_register(
    chapter_id: str,
    title: str,
    draft: str,
    status: Literal["draft", "final"] = "draft",
) -> str:
    """登记章节正文到 正文草稿/ 或 正文/。"""
    folder = "正文" if status == "final" else "正文草稿"
    path = ensure_in_project(PROJECT_ROOT / folder / f"{chapter_id}_{title}.md")
    path.write_text(draft, encoding="utf-8")
    return str(path.relative_to(PROJECT_ROOT))


@tool
def foreshadow_update(op: Literal["create", "trigger", "recover", "discard"], data: dict) -> str:
    """创建或更新伏笔状态。"""
    # 实现期应由程序生成 ID,不要让 LLM 自己编号。
    return "F001"
```

## 核心依赖版最小代码

```python
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode


@tool
def wordcount(text: str) -> dict[str, int]:
    """统计中文文本的粗略字数。"""
    chars = len(text.replace("\n", "").replace(" ", ""))
    return {"chars": chars}


@tool
def foreshadow_query(query: str) -> str:
    """查询伏笔库中与 query 相关的条目。"""
    return "F003: 玉簪真实来历,状态=潜伏,计划第 18 章回收"


tool_node = ToolNode([wordcount, foreshadow_query])


def run_tool_call() -> dict:
    result = tool_node.invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "foreshadow_query",
                            "args": {"query": "F003"},
                            "id": "call_001",
                        }
                    ],
                )
            ]
        }
    )
    return result
```

## 设计原则

- LLM 调用业务 Tool,不直接编辑关键 Markdown。
- 路径 Tool 必须做 `resolve()` 和项目内权限检查。
- 写入 Tool 返回结构化结果,方便 LangGraph state 记录。
- 交互 Tool 不直接读 stdin,而是抛出 interrupt 给 REPL。

## 验收标准

- 章节写入必须通过 `chapter_register`。
- 伏笔状态必须通过 `foreshadow_update`。
- `read_file("../x")` 必须被拒绝。
- Tool 调用历史能写入 state,用于调试和恢复。
