"""Router prompt template — translates user input into an :class:`AgentAction`.

Originally lived inline in :mod:`writer.routing.llm_router`; moved here
so the prompt surface is auditable in one place. The legacy import path
``from writer.routing.llm_router import COMMAND_AGENT_PROMPT`` is
preserved as a thin re-export alias so callers (and tests) need not
change.

The template takes two inputs:

* ``project_state`` — the current :class:`writer.project.ProjectState`
  identifier (``"S0"`` / ``"S3"`` / …); the model uses this to reject
  commands that are not legal in the current lifecycle stage.
* ``user_input`` — the raw user turn text.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

COMMAND_AGENT_TEMPLATE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            (
                "你是 Writer Agent 的前台调度 Agent。\n"
                "职责:把用户输入转成 AgentAction,不要直接动手。\n"
                "边界:\n"
                "- 不直接写文件。\n"
                "- 不直接生成整章正文。\n"
                "- 不直接修改 AGENT.md。\n"
                "- 长任务(整章写作、章节审核) → start_workflow。\n"
                "- 轻量查询(伏笔、字数、定位) → call_tool。\n"
                "- 信息不足 → ask_user。\n"
                "- 明确命令或闲聊 → answer_directly。\n"
            ),
        ),
        (
            "human",
            "项目状态: {project_state}\n用户输入: {user_input}\n",
        ),
    ]
)


__all__ = ["COMMAND_AGENT_TEMPLATE"]
