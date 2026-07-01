# writer-agent

长篇小说写作 Agent 的命令行工具骨架，目标是辅助用户完成 20-50 万字小说的构思、规划、分章、正文生成与修订。

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
writer --help
```

## 当前能力

- `writer doctor`：检查基础运行环境与配置。
- `writer new <name>`：创建一个小说项目目录。
- `writer outline <idea>`：根据一句话创意生成一个最小大纲占位输出。

## 配置

环境变量统一使用 `WRITER_` 前缀：

```bash
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=your-api-key
WRITER_BASE_URL=https://api.openai.com/v1
```

当前初始化版本先提供稳定的 CLI、配置和 Agent 边界，后续可以在 `src/writer/agent` 中接入 LangGraph 工作流、RAG 检索和长期记忆。
