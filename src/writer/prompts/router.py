"""Router prompt 模板 —— 把用户输入翻译成 :class:`AgentAction`。

最初以行内方式位于 :mod:`writer.routing.llm_router` 中；移到这里
让 prompt 表面可以在一个地方审计。旧 import 路径
``from writer.routing.llm_router import COMMAND_AGENT_PROMPT`` 保留
为薄 re-export 别名，让调用方（与测试）无需更改。

模板接受两个输入：

* ``project_state`` —— 当前 :class:`writer.project.ProjectState`
  标识符（``"S0"`` / ``"S3"`` / …）；模型用它在当前生命周期阶段
  不合法的命令时拒绝。
* ``user_input`` —— 原始用户轮次文本。
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
