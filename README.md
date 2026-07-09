# writer-agent

长篇小说写作 Agent 的命令行工具，目标是辅助用户完成 20-50 万字小说的构思、规划、分章、正文生成与修订。

## 快速开始

环境要求：[uv](https://docs.astral.sh/uv/)（自带 Python 管理，无需手动安装 Python）。

```bash
# 同步依赖（自动创建 .venv 并安装项目本体 + 所有 extras）
uv sync --all-extras

# 复制环境变量模板并填入 API Key（可选，未配置时使用本地模板回退）
cp .env.example .env

# 检查配置
uv run writer doctor

# 进入交互式 REPL（默认入口）
uv run writer
```

## 最小闭环：new/init → 大纲 → 目录

阶段一 MVP 已打通「创建项目 → 生成大纲 → 生成章节目录」的完整链路。

### 方式 A：`writer new` 创建新书（推荐）

```bash
writer new 长安程序员          # 交互式多选题材
writer new 长安程序员 -g 历史 -g 玄幻   # 或 CLI 指定多题材
cd 长安程序员
uv run writer
```

`writer new` 会创建完整项目目录，并附带 `.writer/` 元数据（`skills/`、`agents/`、`config`）与 `创意/` 目录。

### 方式 B：全程在 REPL 内

```bash
uv run writer
```

```text
/init 我的小说
/大纲 一个穿越到唐朝的程序员
/目录
/状态
```

注意：S0 时 `/init` 须带项目名（例如 `/init 我的小说`）；S1 已绑定后可直接 `/init <故事梗概>` 完成创意访谈。

## 当前能力

| 命令 | 说明 |
|------|------|
| `writer` | 进入 REPL；输入 `/帮助` 查看命令 |
| `writer doctor` | 检查模型、Base URL、API Key 等配置 |
| `writer new <书名>` | 创建新书项目（含 `.writer/`、`创意/`；创建前多选题材） |
| REPL `/init <name>` | 在 REPL 内创建并绑定项目 |
| REPL `/init <梗概>` | S1 已绑定项目时，写入 `创意/核心创意.md` 并更新 `AGENT.md` |
| REPL `/大纲 <创意>` | 生成大纲并写入 `outline/大纲.md`(SKILL.md directive) |
| REPL `/目录` | 基于已有大纲生成章节目录，写入 `outline/toc.md`(SKILL.md directive) |
| REPL `/字数统计` | 估算项目文件的字数（走 `wordcount` builtin Tool） |
| REPL `/状态` | 查看 session、项目路径、当前状态（S0–S5） |

REPL 启动时会自动绑定项目：当前目录含 `AGENT.md`，或只有一个含 `AGENT.md` 的子目录时生效。若目录下有多个项目，请 `cd` 进入具体项目后再启动 REPL。

## 配置

环境变量统一使用 `WRITER_` 前缀。加载优先级（后者覆盖前者）：

1. Shell 环境变量
2. 项目目录 `.env`
3. **`.writer/config`（最高优先级）**

```bash
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=your-api-key
WRITER_BASE_URL=https://api.openai.com/v1
WRITER_TEMPERATURE=0.7
```

`writer new` 会在项目内生成 `.writer/config` 模板；格式与 `.env` 相同。REPL 自动绑定项目时会调用 `load_project_settings()`，优先读取 `.writer/config`。

配置 API Key 后，`/大纲` 与 `/目录` 会调用 LLM 生成更具体的内容；未配置或调用失败时自动回退到本地四幕模板，CLI 仍可离线使用。用 `writer doctor` 确认 Key 是否「已配置」。

**推荐**：在小说项目目录下编辑 `.writer/config` 或放置 `.env`（可从 writer 仓库复制 `.env.example`）：

```bash
cp /path/to/writer/.env.example "./我的小说/.writer/config"
# 编辑 config 填入 WRITER_API_KEY 等
```

若 `/大纲` 输出「第一幕 / 第二幕 / 第三幕 / 第四幕」四行固定模板，说明走了离线回退；终端会提示 `[提示] 本次 /大纲 使用本地四幕模板`。

## 开发与测试

```bash
uv run pytest                    # 全量测试
uv run pytest tests/test_cli.py  # CLI / REPL 测试
uv run ruff check src tests
uv run mypy src/writer
```

## 打包 CLI 可执行文件

项目使用 [PyInstaller](https://pyinstaller.org/) 打包命令行程序。先同步开发依赖：

```bash
uv sync --all-extras
```

然后在目标系统上构建：

```bash
PYINSTALLER_CONFIG_DIR=tmp/pyinstaller \
  uv run pyinstaller writer.spec
```

> 修改源码后需重新构建 `dist/writer` 才会生效。若 REPL 启动报 `FileNotFoundError`，请拉取最新代码并重新打包。

构建完成后，产物位于：

```bash
dist/writer      # macOS / Linux
dist/writer.exe  # Windows
```

macOS 和 Windows 需要分别在对应系统上构建；跨平台发布时建议后续用 GitHub Actions 分别生成两个产物。
