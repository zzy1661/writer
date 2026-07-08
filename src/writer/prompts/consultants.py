"""Consultant prompt templates — outline / TOC / init_brief LLM calls.

Centralizes every ChatPromptTemplate used by the four concrete
consultants in :mod:`writer.roles`. The structure follows the convention
laid out in the prompts plan:

* Each genre-specific outline template reuses the matching identity
  fragment from :mod:`writer.prompts.identity` so swapping identity
  wording only requires editing one file.
* TOC and init-brief templates use the neutral
  :data:`CONSULTANT_IDENTITY_STORY` because they do not currently
  branch by genre (per the prompts plan, those branches are explicitly
  out of scope for this iteration).
* :data:`FALLBACK_OUTLINE_CHAPTERS` holds the deterministic chapter
  lists previously inlined in the three genre-specific Consultants.
  Centralizing them here keeps all prompt-shaped content in one place
  and lets the genre Consultants shrink to ``class C(P): GENRE = "…"``
  declarations.

The :func:`build_outline_user_message` helper stays in
:mod:`writer.project.ideas` because it consumes the on-disk
``IdeasContext`` (a project-layer concern). It is intentionally not
imported here so the import graph stays one-way — ``consultants.py``
must not pull from ``writer.project`` because :mod:`writer.project.ideas`
re-exports :data:`OUTLINE_SYSTEM_PROMPT` from this module for backward
compatibility.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from writer.prompts.identity import (
    CONSULTANT_IDENTITY_HISTORY,
    CONSULTANT_IDENTITY_ROMANCE,
    CONSULTANT_IDENTITY_STORY,
    CONSULTANT_IDENTITY_XUANHUAN,
)

# ---------------------------------------------------------------------------
# Outline templates — one per (genre, role="outline")
# ---------------------------------------------------------------------------

OUTLINE_TEMPLATE_STORY: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_STORY
            + "\n\n任务:基于项目的核心创意（及辅助素材），"
            "生成一份可落地的大纲种子，不是正文。"
            "\n约束:每条章节须体现冲突、转折或悬念；若提供了核心创意，"
            "大纲必须以其为叙事中心展开。",
        ),
        ("human", "{user_message}"),
    ]
)

OUTLINE_TEMPLATE_HISTORY: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_HISTORY
            + "\n\n任务:基于项目的核心创意（及辅助素材），"
            "生成一份具备历史纵深的大纲种子，不是正文。"
            "\n约束:每条章节须含「史实锚点」与「虚构补充」两层元素；"
            "史实部分引用真实朝代/年份/事件，虚构部分说明主角的抉择与代价。",
        ),
        ("human", "{user_message}"),
    ]
)

OUTLINE_TEMPLATE_ROMANCE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_ROMANCE
            + "\n\n任务:基于项目的核心创意（及辅助素材），"
            "生成一份以情感节拍为主轴的大纲种子，不是正文。"
            "\n约束:章节使用「节拍<N>」前缀，按 GMC（Goal/Motivation/Conflict）"
            "推进关系曲线；通常 8 到 12 条节拍，覆盖相遇、吸引、暧昧、"
            "误会、内部障碍、分离、自我觉醒、表白/和解、余韵。",
        ),
        ("human", "{user_message}"),
    ]
)

OUTLINE_TEMPLATE_XUANHUAN: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_XUANHUAN
            + "\n\n任务:基于项目的核心创意（及辅助素材），"
            "生成一份以境界推进为骨架的大纲种子，不是正文。"
            "\n约束:章节使用「境界<N> <境界名>」前缀，每个境界须给"
            "核心冲突 + 升级目标；典型层级含炼气、筑基、金丹、元婴、化神。",
        ),
        ("human", "{user_message}"),
    ]
)


# ---------------------------------------------------------------------------
# TOC template — shared across genres (per prompts plan, no genre split)
# ---------------------------------------------------------------------------

TOC_TEMPLATE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_STORY
            + "\n\n任务:基于已有大纲，生成可执行的章节目录，不是正文。",
        ),
        (
            "human",
            "大纲:\n{outline_text}\n"
            "请返回目录 JSON: title 为书名或工作名; chapters 为 8 到 24 条"
            "章节标题，按故事顺序排列，每条需体现冲突或推进。",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Init brief template — /init creative-brief expansion (genre-agnostic)
# ---------------------------------------------------------------------------

INIT_BRIEF_TEMPLATE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            CONSULTANT_IDENTITY_STORY
            + "\n\n任务:用户刚创建小说项目，请从自然语言描述中提炼核心创意与写作基本要求。",
        ),
        (
            "human",
            "用户描述:\n{brief}\n"
            "请返回 JSON: core_idea 为 Markdown 格式的核心创意扩写"
            "（含标题、故事核、主角目标、核心冲突）; requirements 为"
            "项目基本要求清单（Markdown 列表，含篇幅、风格、禁忌等）。",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Deterministic fallback chapter lists — used when LLM is unavailable
# ---------------------------------------------------------------------------

FALLBACK_OUTLINE_CHAPTERS: dict[str, list[str]] = {
    "other": [
        "第一幕：主角处境与核心欲望",
        "第二幕：进入新世界并遭遇主要阻力",
        "第三幕：代价升级，关系与秘密浮出水面",
        "第四幕：失败后的反击与终局选择",
    ],
    "历史": [
        "前期铺垫: 史实: 朝代/年份与主角出身背景 | 虚构: 主角穿越或登场理由",
        "第一转折: 史实: 重大历史事件锚点（元年/事变）| 虚构: 主角抉择如何介入",
        "中盘深化: 史实: 派系/制度/地理细节 | 虚构: 主角隐藏身份的副作用",
        "代价升级: 史实: 真实人物与权力交锋 | 虚构: 主角承担的风险与代价",
        "终局落幕: 史实: 历史已知的结局 | 虚构: 主角的解释与后续命运",
    ],
    "玄幻": [
        "境界1 炼气期: 觉醒金手指 → 入宗门(或获得传承)",
        "境界2 筑基期: 宗门内比 → 首次外出历练",
        "境界3 金丹期: 副本/秘境 → 同辈/师长级别对手",
        "境界4 元婴期: 大势力登场 → 卷末大高潮",
        "境界5 化神期: 飞升/位面跃迁 → 铺设更高地图",
    ],
    "言情": [
        "节拍1: 相遇 → 第一印象 → 巧合接触",
        "节拍2: 吸引 → 主动互动 → 共处升温",
        "节拍3: 暧昧 → 错觉甜蜜 → 内心骚动",
        "节拍4: 误会 → 信息差/第三者破坏 → 关系骤冷",
        "节拍5: 内部障碍 → 主角情感创伤/价值观冲突",
        "节拍6: 分离危机 → 外部压力下的分别",
        "节拍7: 自我觉醒 → 主角主动解决自身障碍",
        "节拍8: 表白/和解 → 关系转换 → 承诺",
        "节拍9: 余韵 → 关系稳定 → 长线钩子",
    ],
}


__all__ = [
    "FALLBACK_OUTLINE_CHAPTERS",
    "INIT_BRIEF_TEMPLATE",
    "OUTLINE_TEMPLATE_HISTORY",
    "OUTLINE_TEMPLATE_ROMANCE",
    "OUTLINE_TEMPLATE_STORY",
    "OUTLINE_TEMPLATE_XUANHUAN",
    "TOC_TEMPLATE",
]
