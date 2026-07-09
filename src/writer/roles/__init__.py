"""Sub-agent roles (per 备忘 04 / 16).

Each module in this package exposes one specialist *role* — a small,
focused capability surface that the engine or workflow nodes call
explicitly. Roles do not dispatch to each other directly; cross-role
composition lives at the workflow graph layer.

Current roles:

* :class:`writer.roles.story_agent.StoryAgent` — the default
  four-act story agent. Acts as the **fallback** for genres the
  engine doesn't know about (genre=other).
* :class:`writer.roles.history_agent.HistoryAgent` — outlines
  for historical / 架空历史 fiction; chapters carry ``史实:`` / ``虚构:``
  anchors.
* :class:`writer.roles.xuanhuan_agent.XuanhuanAgent` —
  outlines for 玄幻 / 修真 / fantasy web-novel; chapters carry
  ``境界<N>`` nodes.
* :class:`writer.roles.romance_agent.RomanceAgent` —
  outlines for 言情 (romance) web-novel; chapters carry ``节拍<N>``
  beats following the GMC / Romancing the Beat tradition.

All four roles share the :class:`OutlineResult` shape, so callers
(``EngineDeps.story_agent``, ``cli outline``, ``/大纲`` engine
loop) only depend on the parent contract — the concrete subclass is
selected by the caller of ``production_deps`` (typically
``EngineSession.__post_init__``) based on a genre string read from
the project's ``AGENT.md`` ``题材:`` line.

Renamed from ``consultant`` to ``agent`` per ``fea-agent-mirror``
(2026-07-09) — see the change proposal for the full rename mapping.
"""

from writer.roles.history_agent import HistoryAgent
from writer.roles.romance_agent import RomanceAgent
from writer.roles.story_agent import InitBriefResult, OutlineResult, StoryAgent, TocResult
from writer.roles.xuanhuan_agent import XuanhuanAgent

__all__ = [
    "HistoryAgent",
    "InitBriefResult",
    "OutlineResult",
    "RomanceAgent",
    "StoryAgent",
    "TocResult",
    "XuanhuanAgent",
]
