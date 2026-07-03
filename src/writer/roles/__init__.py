"""Sub-agent roles (per 备忘 04 / 16).

Each module in this package exposes one specialist *role* — a small,
focused capability surface that the engine or workflow nodes call
explicitly. Roles do not dispatch to each other directly; cross-role
composition lives at the workflow graph layer.

Current roles:

* :class:`writer.roles.story_consultant.StoryConsultant` — drafts four-act
  story outlines from a one-line premise.
"""

from writer.roles.story_consultant import OutlineResult, StoryConsultant

__all__ = ["OutlineResult", "StoryConsultant"]
