"""Registry of built-in skills for project-level mirroring.

Each entry tells :func:`writer.project.workspace._seed_skill_mirrors`
how to materialise a built-in skill's Python source as a project-level
override file under ``<project_root>/.writer/skills/``.

The fields are kept narrow and explicit:

* ``command``           — the slash command (e.g. ``"/大纲"``).
* ``mirror_filename``   — basename of the project-level file (no path,
                          no ``.py``); Chinese names are kept verbatim
                          (the filesystem stores them as UTF-8).
* ``source_module``     — fully-qualified Python module that defines
                          the class. Used to import + read the source
                          text.
* ``class_name``        — the class to import from ``source_module``.
* ``source_sha256``     — SHA-256 of the source file at the time this
                          registry was generated. Future drift-detection
                          tooling (e.g. a future ``writer init
                          --upgrade-skills``) can use this to flag when
                          a mirror is out of sync with the built-in
                          version.
* ``doc_title``         — title of the companion Markdown file.
* ``doc_body``          — body of the companion Markdown file. Kept
                          short on purpose; long-form docs would risk
                          going stale.

The list is ordered to match :data:`writer.skills.BUILTIN_SKILLS` so
the on-disk order of mirror files is stable across Python versions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinSkillSource:
    """One row in the built-in skill source registry."""

    command: str
    mirror_filename: str
    source_module: str
    class_name: str
    source_sha256: str
    doc_title: str
    doc_body: str


# SHA-256 fingerprints of the source files at 2026-07-08 (per
# chg-project-skills design Decision 2). When the source changes, this
# table MUST be updated and a note added to the changelog so that
# drift-detection tooling has a baseline to compare against.
BUILTIN_SKILL_SOURCES: tuple[BuiltinSkillSource, ...] = (
    BuiltinSkillSource(
        command="/大纲",
        mirror_filename="大纲",
        source_module="writer.skills.outline",
        class_name="OutlineSkill",
        source_sha256=(
            "6d7216c7d81f8aa091e987d36bae68e5c47d22b14a2623756b50bf8ca052b634"
        ),
        doc_title="大纲",
        doc_body=(
            "## 用途\n\n"
            "调用 StoryConsultant 生成大纲；写入 `outline/大纲.md` 并刷新 `AGENT.md`。\n\n"
            "## 可调点\n\n"
            "- 想换四幕之外的章节结构：编辑本文件，重写 `OutlineSkill.run`。"
            " 看 `writer.skills.outline.OutlineSkill` 拿基线实现。\n"
            "- 想换输出格式：编辑 `OutlineSkill._format_outline` 即可。\n"
            "- 想接 LLM：把 `draft_outline` 调用点的本地 fallback 替成真 model；"
            " 详见 `StoryConsultant.draft_outline` 的 LLM 入口。"
        ),
    ),
    BuiltinSkillSource(
        command="/目录",
        mirror_filename="目录",
        source_module="writer.skills.toc",
        class_name="TocSkill",
        source_sha256=(
            "6899e531c0f85a5f17b4f6ebc481e30aec737d84b187ff29f9b2c2bec3b82c79"
        ),
        doc_title="目录",
        doc_body=(
            "## 用途\n\n"
            "读取 `outline/大纲.md`，调用 StoryConsultant 生成章节目录；"
            "写入 `outline/toc.md` 并刷新 `AGENT.md`。\n\n"
            "## 可调点\n\n"
            "- 想换章节粒度（卷/章/节）：编辑本文件，覆写 `TocSkill.run`。\n"
            "- 想跳过某些元数据写入：注释 `TocSkill._write_toc` 里的"
            " `refresh_agent_file` 调用。"
        ),
    ),
    BuiltinSkillSource(
        command="/续写",
        mirror_filename="续写",
        source_module="writer.skills.continue_writing",
        class_name="ContinueWritingSkill",
        source_sha256=(
            "6152ada1845b025aba2eb179ef9484a7e736e03ad2091baf2c8086e9f6e45954"
        ),
        doc_title="续写",
        doc_body=(
            "## 用途\n\n"
            "继续未完成章节。\n\n"
            "## 状态\n\n"
            "**占位** — 等待 LLM 接入。\n\n"
            "## 可调点\n\n"
            "- 接入 LLM：参考 `writer.roles.StoryConsultant.continue_chapter` 文档；"
            " 把 `ContinueWritingSkill.run` 里的 `[提示] /续写 尚未实现` 替换成真调用即可。\n"
            "- 改承接策略（取最新一章 / 取当前 draft / 取最近 N 段）："
            " 在 `ContinueWritingSkill.run` 里改读 `manuscript/` 的逻辑。"
        ),
    ),
    BuiltinSkillSource(
        command="/改",
        mirror_filename="改",
        source_module="writer.skills.revise",
        class_name="ReviseSkill",
        source_sha256=(
            "b8ee39bb38a9679e0e0f30be7047bd38170681bd2fd2830a77e6b648f480a14a"
        ),
        doc_title="改",
        doc_body=(
            "## 用途\n\n"
            "修改章节内容。\n\n"
            "## 状态\n\n"
            "**占位** — 等待 LLM 接入。\n\n"
            "## 可调点\n\n"
            "- 接入 LLM：把 `ReviseSkill.run` 里的 placeholder 替换为"
            " `StoryConsultant.revise_chapter` 调用；选择 in-place rewrite 或 side-by-side diff。\n"
            "- 改 review pipeline：把 `ReviseSkill` 接到 `review_chapter` 工作流上即可。"
        ),
    ),
)


# Header prepended to every mirrored ``<basename>.py`` so users know
# they're looking at a project-level override, not a built-in.
MIRROR_HEADER_TEMPLATE = '''\
"""项目级 skill：{command} (mirror of writer.skills.{source_module_last}.{class_name}).

这是 :class:`writer.skills.{source_module_last}.{class_name}` 的项目级
override 副本。新建项目时由 ``writer new`` 自动生成；用户可自由编辑。

## 与内置版的关系

* 类名、``command``、``description``、``requires_states`` 与内置版一致；
  改动任一字段都会覆盖内置版（按 command 字符串做 Replace）。
* 内置版升级时**不会**自动同步到本文件。当前内置版的 SHA-256 是
  ``{source_sha256}``；当该指纹与 ``writer.skills.{source_module_last}``
  模块的 SHA-256 不一致时，本文件已漂移，可手动同步或调用未来的
  ``writer init --upgrade-skills``。
* 内置版源文件在 ``writer/skills/{source_module_last}.py``（包内）。

## 修改建议

* 只想改输出格式：保留 ``run`` 调用，只改本文件中的格式函数。
* 想换数据流：复制 ``run`` 全文到本文件后改实现（注意保持
  ``AsyncIterator[TextChunk | Done]`` 签名）。
* 改完保存即生效（**下一次** REPL 启动时；不热重载）。
* 改坏了：删除本文件重启 REPL 即回到内置版（不会损坏项目其他文件）。

请勿删除本文件，除非确认要彻底放弃该 skill。
"""

'''


def mirror_filename_for(command: str) -> str | None:
    """Return the mirror filename for ``command``, or ``None`` if unknown."""

    for src in BUILTIN_SKILL_SOURCES:
        if src.command == command:
            return src.mirror_filename
    return None


__all__ = [
    "BUILTIN_SKILL_SOURCES",
    "BuiltinSkillSource",
    "MIRROR_HEADER_TEMPLATE",
    "mirror_filename_for",
]
