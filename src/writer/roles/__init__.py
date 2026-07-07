"""Sub-agent roles (per 备忘 04 / 16).

Each module in this package exposes one specialist *role* — a small,
focused capability surface that the engine or workflow nodes call
explicitly. Roles do not dispatch to each other directly; cross-role
composition lives at the workflow graph layer.

Current roles:

* :class:`writer.roles.story_consultant.StoryConsultant` — the default
  four-act story consultant. Acts as the **fallback** for genres the
  engine doesn't know about (genre=other).
* :class:`writer.roles.history_consultant.HistoryConsultant` — outlines
  for historical / 架空历史 fiction; chapters carry ``史实:`` / ``虚构:``
  anchors.
* :class:`writer.roles.xuanhuan_consultant.XuanhuanConsultant` —
  outlines for 玄幻 / 修真 / fantasy web-novel; chapters carry
  ``境界<N>`` nodes.
* :class:`writer.roles.romance_consultant.RomanceConsultant` —
  outlines for 言情 (romance) web-novel; chapters carry ``节拍<N>``
  beats following the GMC / Romancing the Beat tradition.

All four roles share the :class:`OutlineResult` shape, so callers
(``EngineDeps.story_consultant``, ``cli outline``, ``/大纲`` engine
loop) only depend on the parent contract — the concrete subclass is
selected by ``production_deps`` based on the project's ``AGENT.md``
``题材:`` line.
"""

from writer.roles.history_consultant import HistoryConsultant
from writer.roles.romance_consultant import RomanceConsultant
from writer.roles.story_consultant import InitBriefResult, OutlineResult, StoryConsultant, TocResult
from writer.roles.xuanhuan_consultant import XuanhuanConsultant

__all__ = [
    "InitBriefResult",
    "HistoryConsultant",
    "OutlineResult",
    "RomanceConsultant",
    "StoryConsultant",
    "TocResult",
    "XuanhuanConsultant",
]
