"""Tests for the skill registry and outline/toc skills."""

from __future__ import annotations

from pathlib import Path

from writer.engine import production_deps, run_engine
from writer.engine.context import EngineContext
from writer.project import create_workspace, detect_state
from writer.skills import OutlineSkill, SkillRegistry, TocSkill, built_skill_registry


def _consume(events):  # noqa: ANN001
    import asyncio

    async def drain() -> list[object]:
        return [event async for event in events]

    return asyncio.run(drain())


def test_built_skill_registry_registers_outline_and_toc() -> None:
    registry = built_skill_registry()

    assert registry.get("/大纲") is not None
    assert registry.get("/目录") is not None
    assert isinstance(registry.get("/大纲"), OutlineSkill)
    assert isinstance(registry.get("/目录"), TocSkill)


def test_outline_skill_writes_outline_file(tmp_path: Path) -> None:
    workspace = create_workspace("skill-outline", tmp_path)
    deps = production_deps(project_root=workspace.root)
    registry = SkillRegistry()
    ctx = EngineContext(
        user_input="/大纲 程序员穿越唐朝",
        project_root=workspace.root,
        project_state=detect_state(workspace.root).value,
        session_id="test",
    )

    events = _consume(registry.run("/大纲", ctx, deps, cfg=__import__("writer.engine.config", fromlist=["build_engine_config"]).build_engine_config(ctx)))

    assert (workspace.root / "outline" / "大纲.md").is_file()
    assert any(getattr(e, "reason", None) == "answered" for e in events)


def test_toc_skill_writes_toc_file(tmp_path: Path) -> None:
    workspace = create_workspace("skill-toc", tmp_path)
    (workspace.root / "outline" / "大纲.md").write_text(
        "# 测试\n\n- 第一幕\n- 第二幕\n- 第三幕\n- 第四幕\n",
        encoding="utf-8",
    )
    deps = production_deps(project_root=workspace.root)
    registry = built_skill_registry()
    ctx = EngineContext(
        user_input="/目录",
        project_root=workspace.root,
        project_state=detect_state(workspace.root).value,
        session_id="test",
    )

    events = _consume(registry.run("/目录", ctx, deps, cfg=__import__("writer.engine.config", fromlist=["build_engine_config"]).build_engine_config(ctx)))

    assert (workspace.root / "outline" / "toc.md").is_file()
    assert any(getattr(e, "reason", None) == "answered" for e in events)


def test_engine_dispatches_outline_via_skill_registry(tmp_path: Path) -> None:
    workspace = create_workspace("engine-skill", tmp_path)
    deps = production_deps(project_root=workspace.root)
    ctx = EngineContext(
        user_input="/大纲 测试创意",
        project_root=workspace.root,
        project_state=detect_state(workspace.root).value,
        session_id="test",
    )

    events = _consume(run_engine(ctx, deps))
    text = "".join(e.text for e in events if hasattr(e, "text"))

    assert "outline skill" in text
    assert (workspace.root / "outline" / "大纲.md").is_file()
