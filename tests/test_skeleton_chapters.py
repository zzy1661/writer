"""Tests for ``writer.workflows.skeleton_chapters`` (per ``chg-skeleton-chapters-pr1``).

2026-07-17 — covers:

* ``_load_inputs_node`` 校验（state >= S3、大纲/目录存在）
* ``_call_generate_open_close`` deterministic strict raise
* ``_build_chapter_prompt`` 注入题材 + 架构方法
* ``_parse_toc_text`` 章节目录解析（含卷 header）
* ``_filter_tasks`` mode=full / volume / range
* ``run()`` end-to-end happy path + partial failure
* 直写 ``骨架/<卷>/第N章.md`` + 不经 ``safe_write_file``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from writer.llm.prose import DeterministicProseClient, RealProseClient
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps, production_deps
from writer.workflows.skeleton_chapters import (
    CLOSE_MAX_CHARS,
    OPEN_MAX_CHARS,
    _build_chapter_prompt,
    _call_generate_open_close,
    _filter_tasks,
    _parse_toc_text,
    run,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingChatModel(BaseChatModel):
    """Fake ``BaseChatModel`` that returns canned open/close skeleton text.

    Each call's ``response_text`` is computed by ``response_factory`` so we
    can vary it across chapters (e.g. raise on chapter 2). Records every
    ``invoke`` so tests can inspect the prompt.
    """

    last_messages: list = []  # type: ignore[type-arg]
    response_factory: Any = None
    invoke_calls: list = []  # type: ignore[type-arg]

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "recording-fake-skeleton"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.last_messages = list(messages)
        self.invoke_calls.append(list(messages))
        if self.response_factory is not None:
            response_text = self.response_factory()
        else:
            response_text = _default_skeleton_text()
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=response_text))]
        )

    async def _agenerate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _default_skeleton_text() -> str:
    """返回带 ``## 开头`` / ``## 结尾`` 的 LLM 假输出。"""

    return (
        "## 开头\n"
        "本章场景在废墟中开场,主角独自面对残局。\n"
        "他环顾四周,寻找可以继续前行的线索。\n"
        "\n"
        "## 结尾\n"
        "他转身离开,远方传来低沉的钟声,暗示新的挑战即将到来。\n"
    )


def _make_deps(
    project_root: Path,
    *,
    llm: BaseChatModel | None = None,
    use_deterministic: bool = False,
) -> RunnerDeps:
    """Build RunnerDeps with the test project root + custom prose client."""

    deps = production_deps(project_root=project_root)
    if use_deterministic:
        deps.prose_client = DeterministicProseClient()
    else:
        deps.prose_client = RealProseClient(llm=llm or _RecordingChatModel())
    return deps


def _write_agent_md(project_root: Path, *, genre: str = "玄幻", method: str = "雪花法") -> Path:
    """写最小 ``AGENT.md`` 含题材/架构方法两行。"""

    agent_md = project_root / "AGENT.md"
    agent_md.write_text(
        f"---\n"
        f"题材: {genre}\n"
        f"架构方法: {method}\n"
        f"---\n\n"
        f"# 测试项目\n",
        encoding="utf-8",
    )
    return agent_md


def _write_outline(project_root: Path) -> Path:
    """写最小 ``大纲/大纲.md``。"""

    outline_dir = project_root / "大纲"
    outline_dir.mkdir(parents=True, exist_ok=True)
    outline = outline_dir / "大纲.md"
    outline.write_text(
        "# 大纲\n\n"
        "主角穿越到唐朝，作为程序员的他必须适应古代的政治生态。\n",
        encoding="utf-8",
    )
    return outline


def _write_toc(project_root: Path, *, chapters: list[tuple[str, str, str]] | None = None) -> Path:
    """写 ``大纲/章节目录.md``。

    ``chapters`` 是 ``(volume, chapter_id, title)`` 元组列表。
    默认两章：1.1 和 1.2。
    """

    if chapters is None:
        chapters = [
            ("卷一", "1.1", "开局"),
            ("卷一", "1.2", "冲突"),
        ]
    toc_dir = project_root / "大纲"
    toc_dir.mkdir(parents=True, exist_ok=True)
    toc = toc_dir / "章节目录.md"
    lines = ["# 章节目录\n", "\n"]
    current_volume = ""
    for volume, chapter_id, title in chapters:
        if volume != current_volume:
            lines.append(f"\n{volume}\n\n")
            current_volume = volume
        lines.append(f"第 {chapter_id} 章 · {title}\n\n")
        lines.append(f"{chapter_id} 的目录摘要内容。\n\n")
    toc.write_text("".join(lines), encoding="utf-8")
    return toc


def _make_context(
    project_root: Path, user_input: str = "/骨架"
) -> RunnerContext:
    """Build RunnerContext pointing at a project. ``session_id`` 用于 thread_id。"""

    return RunnerContext(
        user_input=user_input,
        project_root=project_root,
        project_state="S3",
        session_id="test-skel-session",
    )


# ---------------------------------------------------------------------------
# Tests: _call_generate_open_close deterministic raise (task 8.4)
# ---------------------------------------------------------------------------


class TestDeterministicStrictRaise:
    def test_raises_runtime_error(self) -> None:
        client = DeterministicProseClient()
        with pytest.raises(RuntimeError) as exc_info:
            _call_generate_open_close(
                prose_client=client,
                chapter_id="1.1",
                title="开局",
                volume="卷一",
                toc_blurb="",
                prev_closing="",
                genre="玄幻",
                architecture_method="雪花法",
            )
        assert "WRITER_API_KEY" in str(exc_info.value)

    def test_error_message_mentions_skeleton(self) -> None:
        client = DeterministicProseClient()
        with pytest.raises(RuntimeError, match="skeleton_chapter"):
            _call_generate_open_close(
                prose_client=client,
                chapter_id="1.1",
                title="",
                volume="",
                toc_blurb="",
                prev_closing="",
                genre="",
                architecture_method="",
            )

    def test_real_client_does_not_raise(self) -> None:
        llm = _RecordingChatModel()
        client = RealProseClient(llm=llm)
        opening, closing = _call_generate_open_close(
            prose_client=client,
            chapter_id="1.1",
            title="开局",
            volume="卷一",
            toc_blurb="摘要",
            prev_closing="",
            genre="玄幻",
            architecture_method="雪花法",
        )
        assert "废墟" in opening or len(opening) > 0
        assert "钟声" in closing or len(closing) > 0


# ---------------------------------------------------------------------------
# Tests: _build_chapter_prompt consumes AGENT.md metadata (task 8.6)
# ---------------------------------------------------------------------------


class TestBuildChapterPrompt:
    def test_genre_in_system_prompt(self) -> None:
        system, _ = _build_chapter_prompt(
            chapter_id="1.1", title="开局", volume="卷一",
            toc_blurb="", prev_closing="", genre="玄幻",
            architecture_method="雪花法",
        )
        assert "玄幻" in system

    def test_architecture_method_in_system_prompt(self) -> None:
        system, _ = _build_chapter_prompt(
            chapter_id="1.1", title="开局", volume="卷一",
            toc_blurb="", prev_closing="", genre="",
            architecture_method="三幕结构",
        )
        assert "三幕结构" in system

    def test_max_chars_constants_in_system(self) -> None:
        system, _ = _build_chapter_prompt(
            chapter_id="1.1", title="t", volume="",
            toc_blurb="", prev_closing="", genre="",
            architecture_method="",
        )
        assert str(OPEN_MAX_CHARS) in system
        assert str(CLOSE_MAX_CHARS) in system

    def test_prev_closing_threaded_in_user(self) -> None:
        _, user = _build_chapter_prompt(
            chapter_id="1.2", title="冲突", volume="卷一",
            toc_blurb="", prev_closing="上一章结尾文本",
            genre="", architecture_method="",
        )
        assert "上一章结尾文本" in user

    def test_first_chapter_has_no_prev_closing(self) -> None:
        _, user = _build_chapter_prompt(
            chapter_id="1.1", title="开局", volume="卷一",
            toc_blurb="", prev_closing="",
            genre="", architecture_method="",
        )
        assert "承接" not in user

    def test_prev_closing_truncated_at_budget(self) -> None:
        long_text = "x" * 1000
        _, user = _build_chapter_prompt(
            chapter_id="1.2", title="t", volume="",
            toc_blurb="", prev_closing=long_text,
            genre="", architecture_method="",
        )
        assert "x" * 500 in user
        # 截断标记
        assert "截断" in user


# ---------------------------------------------------------------------------
# Tests: _parse_toc_text (helper for parse_toc_node)
# ---------------------------------------------------------------------------


class TestParseTocText:
    def test_basic_two_chapters(self) -> None:
        text = (
            "# 章节目录\n\n"
            "卷一\n\n"
            "第 1.1 章 · 开局\n\n"
            "这是 1.1 的摘要。\n\n"
            "第 1.2 章 · 冲突\n\n"
            "这是 1.2 的摘要。\n\n"
        )
        entries = _parse_toc_text(text)
        assert len(entries) == 2
        assert entries[0]["chapter_id"] == "1.1"
        assert entries[0]["title"] == "开局"
        assert entries[0]["volume"] == "卷一"
        assert "1.1" in entries[0]["toc_blurb"]
        assert entries[1]["chapter_id"] == "1.2"

    def test_alternate_format_dotted_id_skipped(self) -> None:
        """PR1 只支持 ``第 X.Y 章`` 形式;裸 ``X.Y 标题`` 行不被解析为章节。

        这是为了避免把目录摘要文本（形如 ``1.1 的目录摘要内容。``）
        误识别为第二个章节。
        """
        text = "卷一\n\n1.1 开局\n\n这是摘要。\n\n1.2 冲突\n\n"
        entries = _parse_toc_text(text)
        # 只支持 `第 X.Y 章` 形式,所以这条文本应解析为 0 个章节
        assert entries == []

    def test_two_volumes(self) -> None:
        text = (
            "卷一\n\n第 1.1 章 · 开局\n\n"
            "卷二\n\n第 2.1 章 · 新篇\n\n"
        )
        entries = _parse_toc_text(text)
        assert len(entries) == 2
        assert entries[0]["volume"] == "卷一"
        assert entries[1]["volume"] == "卷二"

    def test_empty_text_returns_empty(self) -> None:
        assert _parse_toc_text("") == []

    def test_header_lines_skipped(self) -> None:
        text = "# 标题\n\n## 子标题\n\n卷一\n\n第 1.1 章 · 开局\n\n"
        entries = _parse_toc_text(text)
        assert len(entries) == 1
        assert entries[0]["chapter_id"] == "1.1"


# ---------------------------------------------------------------------------
# Tests: _filter_tasks (helper for parse_toc_node)
# ---------------------------------------------------------------------------


class TestFilterTasks:
    def test_full_mode_returns_all(self) -> None:
        toc = [
            {"chapter_id": "1.1", "volume": "卷一"},
            {"chapter_id": "1.2", "volume": "卷一"},
            {"chapter_id": "2.1", "volume": "卷二"},
        ]
        from writer.workflows.params import SkeletonArgs

        result = _filter_tasks(toc, SkeletonArgs(mode="full"))
        assert len(result) == 3

    def test_volume_mode_filters(self) -> None:
        toc = [
            {"chapter_id": "1.1", "volume": "卷一"},
            {"chapter_id": "1.2", "volume": "卷一"},
            {"chapter_id": "2.1", "volume": "卷二"},
        ]
        from writer.workflows.params import SkeletonArgs

        result = _filter_tasks(toc, SkeletonArgs(mode="volume", volume="卷一"))
        assert len(result) == 2
        assert all(t["volume"] == "卷一" for t in result)

    def test_range_mode_filters_chapters(self) -> None:
        toc = [
            {"chapter_id": "1.1", "volume": "卷一"},
            {"chapter_id": "1.2", "volume": "卷一"},
            {"chapter_id": "1.3", "volume": "卷一"},
            {"chapter_id": "2.1", "volume": "卷二"},
        ]
        from writer.workflows.params import SkeletonArgs

        result = _filter_tasks(toc, SkeletonArgs(mode="range", start="1.1", end="1.2"))
        assert [t["chapter_id"] for t in result] == ["1.1", "1.2"]

    def test_cross_volume_range(self) -> None:
        toc = [
            {"chapter_id": "1.1", "volume": "卷一"},
            {"chapter_id": "1.2", "volume": "卷一"},
            {"chapter_id": "2.1", "volume": "卷二"},
            {"chapter_id": "2.2", "volume": "卷二"},
        ]
        from writer.workflows.params import SkeletonArgs

        result = _filter_tasks(toc, SkeletonArgs(mode="range", start="1.2", end="2.1"))
        assert [t["chapter_id"] for t in result] == ["1.2", "2.1"]


# ---------------------------------------------------------------------------
# Tests: load_inputs state validation (task 8.3)
# ---------------------------------------------------------------------------


class TestLoadInputsStateValidation:
    def test_state_below_s3_rejected(self, tmp_path: Path) -> None:
        """``/骨架`` 在 S2 状态（有大纲无目录）下应 abort。"""

        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        # 没有 toc.md → state = HAS_OUTLINE = S2

        deps = _make_deps(tmp_path, llm=_RecordingChatModel())
        ctx = _make_context(tmp_path, user_input="/骨架")

        result = run(ctx, deps)
        assert result.status == "failed"
        assert any("/目录" in str(metrics.get("error", "")) or "状态" in str(metrics.get("error", ""))
                   for metrics in [result.metrics])
        # 无骨架文件
        assert not (tmp_path / "骨架").exists()

    def test_missing_outline_rejected(self, tmp_path: Path) -> None:
        _write_agent_md(tmp_path)
        _write_toc(tmp_path)  # 只有 TOC
        # 没有 大纲/大纲.md → state = HAS_TOC = S3, 大纲.md 缺失

        deps = _make_deps(tmp_path, llm=_RecordingChatModel())
        ctx = _make_context(tmp_path, user_input="/骨架")

        result = run(ctx, deps)
        assert result.status == "failed"
        assert "大纲" in str(result.metrics.get("error", "")) or "/大纲" in str(result.metrics.get("error", ""))

    def test_missing_toc_rejected(self, tmp_path: Path) -> None:
        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        # 没有 toc.md → state = HAS_OUTLINE = S2

        deps = _make_deps(tmp_path, llm=_RecordingChatModel())
        ctx = _make_context(tmp_path, user_input="/骨架")

        result = run(ctx, deps)
        assert result.status == "failed"
        assert "目录" in str(result.metrics.get("error", "")) or "/目录" in str(result.metrics.get("error", ""))


# ---------------------------------------------------------------------------
# Tests: end-to-end happy path (tasks 8.5, 8.8)
# ---------------------------------------------------------------------------


class TestEndToEndHappyPath:
    def test_full_mode_writes_chapter_files(self, tmp_path: Path) -> None:
        """S3 项目 + 2 chapters → 2 文件落盘 + 索引 + 进度。"""

        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path)

        result = run(ctx, deps)

        assert result.status == "completed"
        assert result.metrics["chapter_count"] == 2
        assert result.metrics["mode"] == "full"
        assert result.metrics["rewrite"] == 0
        assert result.metrics["resumed"] == 0

        # 落盘：骨架/卷一/第001章.md + 第002章.md
        assert (tmp_path / "骨架" / "卷一" / "第001章.md").is_file()
        assert (tmp_path / "骨架" / "卷一" / "第002章.md").is_file()

        # 索引
        index_path = tmp_path / "骨架" / "索引.md"
        assert index_path.is_file()
        index_content = index_path.read_text(encoding="utf-8")
        assert "1.1" in index_content
        assert "1.2" in index_content

        # 进度 JSON
        progress_path = tmp_path / "骨架" / "进度.json"
        assert progress_path.is_file()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress["status"] in ("running", "completed")
        assert progress["completed"] == ["1.1", "1.2"]

    def test_no_safe_write_file_tool_calls(self, tmp_path: Path) -> None:
        """关键不变量：``Path.write_text`` 直写，**不**经 ``safe_write_file``。"""

        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path)

        # 用 ToolRegistry spy 验证
        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)

        # Spy: wrap tool_registry.invoke 计数
        original_invoke = deps.tool_registry.invoke
        calls: list[tuple[str, dict]] = []

        def spy_invoke(name: str, runtime: Any, **kwargs: Any) -> Any:
            calls.append((name, kwargs))
            return original_invoke(name, runtime, **kwargs)

        deps.tool_registry.invoke = spy_invoke  # type: ignore[assignment]

        ctx = _make_context(tmp_path)
        result = run(ctx, deps)

        assert result.status == "completed"
        # 没有任何 safe_write_file / safe_edit_file 调用
        write_calls = [name for name, _ in calls if name in ("safe_write_file", "safe_edit_file")]
        assert write_calls == []

    def test_prompt_includes_architecture_method(self, tmp_path: Path) -> None:
        """验证单章 prompt 包含 AGENT.md 架构方法字段。"""

        _write_agent_md(tmp_path, method="三幕结构")
        _write_outline(tmp_path)
        _write_toc(tmp_path)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path)
        run(ctx, deps)

        # 检查 LLM 收到的 system prompt 包含「三幕结构」
        assert llm.invoke_calls, "expected at least one invoke call"
        first_call = llm.invoke_calls[0]
        # _call_generate_open_close 把 system 拼到了 _build_chapter_prompt
        system_msg = first_call[0].content  # 第一条是 SystemMessage
        assert "三幕结构" in system_msg

    def test_volume_filter_writes_only_target_volume(self, tmp_path: Path) -> None:
        """``/骨架 卷一`` 只写卷一章节，卷二不动。"""

        chapters = [
            ("卷一", "1.1", "开局"),
            ("卷一", "1.2", "冲突"),
            ("卷二", "2.1", "新篇"),
            ("卷二", "2.2", "高潮"),
        ]
        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path, chapters=chapters)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path, user_input="/骨架 卷一")

        result = run(ctx, deps)

        assert result.status == "completed"
        assert result.metrics["chapter_count"] == 2
        assert result.metrics["volume"] == "卷一"

        assert (tmp_path / "骨架" / "卷一" / "第001章.md").is_file()
        assert (tmp_path / "骨架" / "卷一" / "第002章.md").is_file()
        # 卷二目录不应创建
        assert not (tmp_path / "骨架" / "卷二").exists()

    def test_range_mode_filters_chapters(self, tmp_path: Path) -> None:
        """``/骨架 1.1-1.20`` 只写区间内的章节。"""

        chapters = [
            ("卷一", "1.1", "c1"),
            ("卷一", "1.2", "c2"),
            ("卷一", "1.3", "c3"),
            ("卷二", "2.1", "c4"),
        ]
        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path, chapters=chapters)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path, user_input="/骨架 1.1-1.2")

        result = run(ctx, deps)
        assert result.status == "completed"
        assert result.metrics["chapter_count"] == 2
        assert (tmp_path / "骨架" / "卷一" / "第001章.md").is_file()
        assert (tmp_path / "骨架" / "卷一" / "第002章.md").is_file()
        assert not (tmp_path / "骨架" / "卷一" / "第003章.md").exists()

    def test_workflow_result_artifacts_complete(self, tmp_path: Path) -> None:
        """验证 WorkflowResult.artifacts 包含 skeleton_root / index_path / progress_path。"""

        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path)
        result = run(ctx, deps)

        assert result.status == "completed"
        assert "skeleton_root" in result.artifacts
        assert "index_path" in result.artifacts
        assert "progress_path" in result.artifacts
        assert result.artifacts["index_path"].exists()


# ---------------------------------------------------------------------------
# Tests: partial failure (task 8.9)
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_llm_failure_mid_batch_returns_failed(self, tmp_path: Path) -> None:
        """章节 2 LLM 抛错后，结果是 status=failed + partial_chapters=1 + 进度 JSON 已标记 failed。"""

        chapters = [
            ("卷一", "1.1", "c1"),
            ("卷一", "1.2", "c2"),
            ("卷一", "1.3", "c3"),
        ]
        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path, chapters=chapters)

        call_count = {"n": 0}

        def factory() -> str:
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated LLM error on chapter 2")
            return _default_skeleton_text()

        llm = _RecordingChatModel(response_factory=factory)
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path)
        result = run(ctx, deps)

        assert result.status == "failed"
        assert result.metrics.get("partial_chapters") == 1

        # 已写章节文件存在
        assert (tmp_path / "骨架" / "卷一" / "第001章.md").is_file()
        # 未写章节文件不存在
        assert not (tmp_path / "骨架" / "卷一" / "第002章.md").exists()

        # 进度 JSON 标记 failed
        progress_path = tmp_path / "骨架" / "进度.json"
        assert progress_path.is_file()
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        assert progress["status"] == "failed"
        assert "1.1" in progress["completed"]

        # artifacts 包含 progress_path
        assert "progress_path" in result.artifacts


# ---------------------------------------------------------------------------
# Tests: graph topology / state propagation
# ---------------------------------------------------------------------------


class TestGraphTopology:
    def test_all_six_nodes_registered(self) -> None:
        from writer.workflows.skeleton_chapters import build_skeleton_graph

        graph = build_skeleton_graph()
        # StateGraph compiled; we can inspect nodes via the inner schema
        node_names = set(graph.get_graph().nodes.keys())
        expected = {
            "load_inputs",
            "parse_toc",
            "init_or_load_progress",
            "generate_batch",
            "persist_skeleton",
            "finalize",
            "__start__",
        }
        assert expected.issubset(node_names)

    def test_trace_contains_all_six_node_names_on_success(self, tmp_path: Path) -> None:
        _write_agent_md(tmp_path)
        _write_outline(tmp_path)
        _write_toc(tmp_path)

        llm = _RecordingChatModel()
        deps = _make_deps(tmp_path, llm=llm)
        ctx = _make_context(tmp_path)
        result = run(ctx, deps)

        # 通过 chunks 拿到 trace
        trace_chunk = next((c for c in result.chunks if "trace=" in c), "")
        assert "load_inputs" in trace_chunk
        assert "parse_toc" in trace_chunk
        assert "generate_batch" in trace_chunk
        assert "finalize" in trace_chunk
