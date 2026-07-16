"""``/init`` 多轮探索能力。

``writer.explore`` 承载 ``/init`` 的多轮对话逻辑，镜像
:mod:`writer.agents` 既是身份层（shipped Markdown）又是能力层
（Python 函数）的双层模式。
"""

from writer.explore.agent import (
    MAX_EXPLORE_QUESTIONS,
    ExploreOutcome,
    ExploreQuestion,
    run_explore,
)
from writer.explore.architectures import (
    ARCHITECTURES,
    ArchitectureSpec,
    lookup_architecture,
)

__all__ = [
    "ARCHITECTURES",
    "ArchitectureSpec",
    "ExploreOutcome",
    "ExploreQuestion",
    "MAX_EXPLORE_QUESTIONS",
    "lookup_architecture",
    "run_explore",
]
