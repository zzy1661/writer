## 1. 删 `state.py` 的拦截符号

- [x] 1.1 删 `src/writer/project/state.py` 中的 `COMMAND_ALLOWED` dict (lines 72-86) 和 `COMMAND_HINTS` dict (lines 88-96)
- [x] 1.2 删 `CommandCheck` dataclass (lines 42-49)
- [x] 1.3 删 `validate_command_available()` 函数 (lines 195-247)
- [x] 1.4 删 `SkillRegistryView` Protocol (lines 250-261) 和 `_skill_hint()` 函数 (lines 264-275)
- [x] 1.5 更新 `__all__` 列表,移除已删符号,保留 `ProjectState` / `STATE_DESCRIPTIONS` / `detect_state` / `inspect_project` / `find_outline_path` / `discover_project_root` / `count_chapters` / `safe_cwd` / `render_agent_file` / `refresh_agent_file` / `append_agent_requirements` / `read_genre_from_agent` / `ProjectSnapshot` / `CURRENT_STATE_SECTION_HEADER`
- [x] 1.6 更新 `src/writer/project/__init__.py` 的 re-export,移除 `validate_command_available` 和 `CommandCheck`(如果出现在 `__all__`)

## 2. 删 `SkillDirective.requires_states` 字段 + `DirectiveRegistry` 相关方法

- [x] 2.1 在 `src/writer/skills/protocol.py::SkillDirective` dataclass 中删除 `requires_states: frozenset[ProjectState]` 字段 (line 62)
- [x] 2.2 更新 `SkillDirective` 字段 docstring (lines 41-58) 中移除"requires_states"说明
- [x] 2.3 更新模块顶部 docstring 中"4 个下游表面"列表 (lines 13-27),删除"状态机拦截"项
- [x] 2.4 移除 `if TYPE_CHECKING` 块中的 `ProjectState` import (line 36-37,可能不再需要)
- [x] 2.5 在 `src/writer/skills/registry.py` 中删除 `_validate()` 里的 requires_states 校验块 (lines 60-68)
- [x] 2.6 删 `DirectiveRegistry.state_matrix()` 方法 (lines 121-129)
- [x] 2.7 更新 `DirectiveRegistry` 类 docstring (lines 73-81) 移除 state_matrix 提及

## 3. 删 `directive_discovery.py` 里的 `requires_states` 处理

- [x] 3.1 删 `_resolve_requires_states()` 函数 (lines ~345-385)
- [x] 3.2 删两处 `meta` dict 构造里的 `requires_states=...` 字段 (lines 244, 299)
- [x] 3.3 删 directive `requires_states` 校验 (lines 398-399)
- [x] 3.4 删模块顶部 docstring 或必要位置的 `requires_states` 引用
- [x] 3.5 更新 `if TYPE_CHECKING` 块中的 `ProjectState` import (可能不再需要)

## 4. 删 `engine/loop.py` 的拦截块

- [x] 4.1 删 `_engine_loop` 中 `validate_command_available()` 拦截块 (lines 124-140,含 17 行)
- [x] 4.2 删除 `from writer.project import (...)` 中不再需要的 `validate_command_available`(可能在 lines 57-62)
- [x] 4.3 验证 `_maybe_run_init_brief_or_block` 内的 S1-only 检查 (lines 296-311) **保留不动**——这是 `/init <brief>` 子命令的业务规则,不是通用拦截
- [x] 4.4 验证 init flow 三处 `Done(aborted, payload={"project_state": ...})` payload (lines 304-310, 354, 382) **保留不动**——是 CLI 渲染契约
- [x] 4.5 跑 `uv run mypy src/writer` 确认类型正确(无未使用 import)

## 5. 删 shipped SKILL.md frontmatter 的 `requires_states` 行

- [x] 5.1 删 `src/writer/skills/_shipped/大纲/SKILL.md` line 4: `requires_states: [INITIALIZED, HAS_OUTLINE]`
- [x] 5.2 删 `src/writer/skills/_shipped/目录/SKILL.md` line 4: `requires_states: [HAS_OUTLINE, HAS_TOC]`
- [x] 5.3 检查并同步 `src/writer/skills/builtin_sources.py` 的镜像元组(若涉及 `requires_states` 字段,同步删除)
- [x] 5.4 检查并同步 `src/writer/project/workspace.py::_seed_skill_mirrors` / `_render_skill_mirror`(若生成 frontmatter 时包含 `requires_states` 行,同步删除)

## 6. 删/改测试 fixture

- [x] 6.1 `tests/test_project_state.py`:删除 `test_validate_command_blocks_write_in_s0` (lines 79-84),移除 `validate_command_available` import (line 14)
- [x] 6.2 `tests/test_directive_registry.py`:删除或改写以下 case:
  - L117-131 `test_registry_state_matrix_derives_from_metadata` —— 改为"registry 不暴露 state_matrix 方法"
  - L70-... 含 `requires_states: [S1]` 的 YAML fixture 改掉
  - L157 `test_registry_rejects_directive_with_empty_requires_states` —— 改为"registry 不校验 requires_states"
- [x] 6.3 `tests/test_directive_discovery.py`:删除/改写以下:
  - `_write_skill_md` helper 的 `requires_states` 参数 (lines 38-49) 改默认行为(不再写 `requires_states` 行)
  - L130-145 关于 `requires_states` 解析的 case 改为"loader 忽略 requires_states"
  - L224-... missing requires_states 校验 case 删除
  - L241-... bad state case 删除
  - L269-272 `test_discover_shipped_directives_have_requires_states` 改写为"shipped SKILL.md 不含 requires_states"
  - 模块顶部 docstring (lines 10-12) 更新
- [x] 6.4 `tests/test_directive_dispatch.py:55` fake directive stub:移除 `requires_states=frozenset({ProjectState.INITIALIZED})` 参数
- [x] 6.5 `tests/test_llm_tool_loop.py:415, 507` fake directive stub:移除 `requires_states=frozenset()` 参数
- [x] 6.6 全量 grep `requires_states` 在 `tests/` 下残留,清零(若仍存在应是无关 fixture)

## 7. 新增测试 case 覆盖"L4 下 directive 可执行"

- [x] 7.1 新增 case:`test_dispatch_directive_in_s4_does_not_block` —— 在 S4 项目下,`engine/loop.py` 收到 `action.command="/大纲"` 时,直接进入 directive body 而不是 yield `Done(aborted)`。可用 fake `LLMToolLoop` 让循环返回 `Done(reason="answered")`,断言没有 `validate_command_available` 拦截分支被触发
- [x] 7.2 新增 case:`test_dispatch_directive_in_s4_does_not_block_toc` —— 同上但针对 `/目录`
- [x] 7.3 新增 case:`test_shipped_skill_md_lacks_requires_states` —— 验证 shipped `_shipped/大纲/SKILL.md` 和 `_shipped/目录/SKILL.md` frontmatter 不含 `requires_states` 键

## 8. 改 docs 与备忘

- [x] 8.1 改 `docs/命令与用户流程.md:233-247` 第 5.2 节:删除"命令 × 状态矩阵"表(或改为"无命令拦截,见各 SKILL.md body");删除 △¹ / △² / △³ 条件说明
- [x] 8.2 改 `技术难点与解决方案备忘/01-项目状态机与命令可用性.md`:删除"COMMAND_ALLOWED 实际样子"代码块中的"`/init` / `/创作` / `/审核` / `/字数统计`"静态表,改为说明"状态机退化为展示层";追加"用户项目级 SKILL.md frontmatter 残留的 `requires_states:` 行无害,无需手动清理"
- [x] 8.3 检查 `技术难点与解决方案备忘/` 其他文件(02 / 03 / 04 / 09 / 13 等)的 `COMMAND_ALLOWED` / `requires_states` 引用并同步清理

## 9. 验证

- [x] 9.1 `uv run ruff check src tests` clean
- [x] 9.2 `uv run mypy src/writer` clean
- [x] 9.3 `uv run pytest` 全过(基线 472 → 删/改后约 440-450 测试)
- [x] 9.4 e2e 验证:`mkdir -p /tmp/s4_test && cd /tmp/s4_test && writer new demo && printf "outline/大纲.md\n# 大纲\n## 前提\nX\n## 四幕大纲\n- 1\n" > demo/outline/大纲.md && mkdir -p demo/manuscript && touch demo/manuscript/ch01.md && printf "/大纲 补充伏笔\n" | .venv/bin/writer` —— 验证 S4 项目跑 `/大纲` 不再被拦截,进入 directive body
- [x] 9.5 e2e 验证:`/状态` 在 S4 项目下正常显示 "S4(正文编辑中)"
- [x] 9.6 e2e 验证:S0 用户跑 `/创作 第 1 章` 不被状态机拦截,但工具层兜底返回 `no_project_root` 错误(`ToolRuntime` sentinel)
- [x] 9.7 `openspec validate chg-remove-state-machine-enforcement --strict` 通过