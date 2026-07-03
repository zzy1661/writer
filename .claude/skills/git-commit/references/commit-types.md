# Conventional Commits `[type]` 速查表

> 完整规范见 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/zh-hans/v1.0.0/)。
> 本表是本 skill 在选 type 时的判定标准。

## 一级 type（常用）

| type       | 含义                              | 什么时候用 ✓                              | 什么时候**不**要用 ✗                          |
|------------|----------------------------------|------------------------------------------|----------------------------------------------|
| `fea` / `feat` | 新功能                            | 新增 API、新增命令、新增用户可见行为       | 重命名 / 改结构（用 `refactor`）              |
| `fix`      | 修复 bug                          | 修崩溃、修错逻辑、修复类型错误             | 拼写错误（用 `docs` 或 `style`）              |
| `refactor` | 重构，**不改外部行为**            | 抽函数、改命名、拆模块、迁移到新 API       | 修了 bug（用 `fix`）                          |
| `perf`     | 性能优化                          | 缓存、索引、算法复杂度                    | 仅仅换了实现方式（用 `refactor`）             |
| `doc`      | 文档                              | README、注释、CHANGELOG、API 文档          | 改配置文件示例（看是否带行为变化）            |
| `test`     | 测试                              | 新单测、e2e、测试夹具、覆盖率              | 修了生产代码的 bug（用 `fix`）                |
| `build`    | 构建系统                          | pyproject / package.json / Makefile / Dockerfile / 锁文件（带构建含义） | CI 脚本（用 `ci`）                            |
| `ci`       | CI/CD                             | GitHub Actions、GitLab CI、pre-commit、hook | 构建系统本身（用 `build`）                    |
| `style`    | 代码风格（无逻辑变化）            | 格式化、空行、import 排序、lint 自动修复   | 改了逻辑（用 `refactor` 或 `fix`）            |
| `chore`    | 杂项 / 维护                       | 依赖升降级（无功能变化）、`.gitignore`、脚本 | 改了用户可见行为（必须用 `fea` / `fix`）      |
| `revert`   | 撤销                              | `git revert` 生成的 commit                 | 自己手写撤销（一般用 `fix` 或 `refactor`）    |
| `init`     | 仓库初始化                        | 仅限**首次** commit                        | 任何后续 commit                                |

## 判定树（拿不准时按这个走）

```
改了用户可见行为？
├── 是 → 用户**看到了什么新东西**？ → fea
│       用户**遇到什么 bug**？     → fix
│       用户**没察觉，但有性能改善**？ → perf
└── 否 → 改了哪类东西？
        ├── 内部代码结构 / 命名 / 抽函数 → refactor
        ├── 测试代码                       → test
        ├── 文档 / 注释 / changelog        → doc
        ├── 仅格式化 / 风格                 → style
        ├── CI / pre-commit hook          → ci
        ├── 构建配置 / 锁文件              → build
        ├── 依赖升降级（无功能变化）       → chore
        ├── .gitignore / 工具脚本          → chore
        └── 我也不知道                     → chore
```

## scope（可选，本 skill 不强制）

`[type]` 后可以加 scope，格式 `[type](scope): summary`：

```
fea(router): add IntentRouter protocol
fix(cli): resolve REPL exit on Ctrl-D
refactor(engine): split deps into separate module
test(tools): cover safe_path boundary cases
```

何时加 scope：

- 改动只影响**一个明确模块 / 包 / 子系统**时。
- 仓库是多模块 monorepo 时。
- 改动**跨 ≥3 个目录**时反而**不**加 scope，改用 body 描述。

## BREAKING CHANGE

破坏性变更用 `!` 后缀 + footer：

```
refactor(api)!: drop legacy v1 endpoints

BREAKING CHANGE: /v1/* paths now return 410 Gone.
Migrate to /v2/* — see docs/migration-v2.md.
```

本 skill 默认**不**主动标 `!`，除非改动确实是 API 移除 / 签名变更 / 默认值翻转这类硬破坏。

## 与 `git commit -m` 的字面值关系

```bash
# type + scope + summary
git commit -m "fea(router): add IntentRouter protocol"

# type + summary
git commit -m "fea: add IntentRouter protocol"

# 多行用 HEREDOC
git commit -m "$(cat <<'EOF'
fea(router): add IntentRouter protocol

Introduce a runtime_checkable Protocol so the routing layer
can swap between RuleBasedIntentRouter (MVP) and a future
LlmIntentRouter without changing engine code.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

## 真实仓库示例

```
fea: add chapter-level foreshadow query tool
fix: resolve word count off-by-one on UTF-8 boundaries
refactor: extract Tool Protocol from registry into own module
perf: cache safe_path resolution per project root
doc: document IntentRouter protocol contract in docs/routing.md
test: cover RuleBasedIntentRouter protocol conformance
build: bump pytest-asyncio to 0.24
ci: run mypy on PRs touching src/writer/
style: apply ruff format to engine/loop.py
chore: drop deprecated --stream flag from CLI
revert: revert "fea: add experimental LangChain bridge"
```
