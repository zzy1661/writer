# Bug 03: `review_chapter` 几乎永远走 deterministic,API key 配了也无效

> ✅ **状态: 已修**(per commit `ad45896`,2026-07-09 之后)
> 修复方式:`_aggregate_reviews_node` 推迟 fallback 到 `_llm_review` 内部;`_llm_review` 走 `review_llm = getattr(deps, "review_llm", None) or _get_llm(get_settings())`,让"未注入 review_llm + production API key 已配"路径自然走真实 LLM。LLM 调用失败时降级到 `ConcernVerdict(score=4, pass=False)` + findings 含错误信息,让 `decision_gate` 标 `needs_rewrite`。新增测试 `test_aggregate_reviews_uses_llm_when_api_key_set` + `test_no_api_key_fallback_message_includes_error` 守住契约。
> **本文档保留**作为历史档案。

## 元信息

| 严重程度 | 🟠 Major |
|---|---|
| 状态 | ✅ 已修 (commit `ad45896`) |
| 发现日期 | 2026-07-09 |
| 关联文件 | `src/writer/workflows/review_chapter.py:265-288`、`src/writer/workflows/review_chapter.py:444-484`、`src/writer/workflows/write_chapter.py:494-509`、`备忘 03-审核工作流.md` |
| 测试盲区 | 测试 `review_llm` 注入有覆盖,但不覆盖 production 默认路径(`deps.review_llm=None` 时 + API key 配了) |

## 1. 现象(Symptom)

### 可复现步骤

1. `.env` 配 `OPENAI_API_KEY=sk-...`(或 DeepSeek),`writer doctor` 显示 API key 已配
2. REPL 启动后写两章: `/创作 1.1` + `/创作 1.2`
3. 输入 `/审核 1.2`
4. 实际结果:`manuscript/reviews/chapter-1.2-<ts>.json` 的 `summary` 字段为 `"deterministic review (no LLM configured)"`,所有 concern `score=8` / `pass=True` / `findings=[]`
5. 期望结果:LLM 真的审核章节,产出带 `findings` 的真实 JSON

### 代码引用

```python
# src/writer/workflows/review_chapter.py:247-294 (_aggregate_reviews_node)
def _aggregate_reviews_node(state: ReviewerState) -> ReviewerState:
    deps = _get_deps()
    ...
    # ✗ Bug: 这里用 deps.review_llm 当 LLM 启用判断
    review_llm = getattr(deps, "review_llm", None)
    if review_llm is None:
        review = _deterministic_review(active_foreshadows, focus)
    else:
        try:
            review = _llm_review(deps, chapter_text, active_foreshadows, focus)
        except Exception as exc:
            ...

# src/writer/workflows/review_chapter.py:444-484 (_llm_review)
def _llm_review(deps, chapter_text, active_foreshadows, focus) -> MultiConcernReview:
    ...
    # 这里其实有 fallback:review_llm 为 None 时从 settings.get_llm() 取
    review_llm = getattr(deps, "review_llm", None)
    llm = review_llm if review_llm is not None else _get_llm(get_settings())
    ...
```

## 2. 根因(Root Cause)

`_aggregate_reviews_node` 把 `deps.review_llm is None` 当作"是否启用 LLM 审核"的判断条件,但 **production 默认装配时 `deps.review_llm` 永远是 `None`**(`_DefaultRunnerDeps.review_llm: Any = None`,见 `src/writer/engine/deps.py:186`)。只有测试代码会显式注入 fake LLM。

也就是说:真实用户即便配了 API key,production 路径也直接走 `_deterministic_review`,完全绕过 `_llm_review` 内部的 fallback 逻辑(`review_llm is None → _get_llm(get_settings())`)。

### 数据流图

```
production_deps() → _DefaultRunnerDeps(review_llm=None)
                                ↓
                set_project_root() → deps.review_llm 仍为 None
                                ↓
                /审核 1.2 → review_chapter.run()
                                ↓
                _aggregate_reviews_node():
                  review_llm = getattr(deps, "review_llm", None)  ← None
                  if review_llm is None:                          ← 永远命中
                      review = _deterministic_review(...)         ← 走了 ✗
                  else:
                      review = _llm_review(deps, ...)             ← 永不命中 ✗
                                ↓
                MultiConcernReview(total_score=8, summary="deterministic ...")
```

**对照 `write_chapter._review_gate_node`**:`write_chapter.py:266-275` 改用 `prose_client.name == "deterministic"` 当 LLM 启用判断 — 这个判断在 production 默认装配里也永远是 False(因为 `production_deps` 总是装配 `RealProseClient` 当 API key 配了,见 `engine/deps.py:352-357`)。这才是正确的判断模式。

## 3. 影响范围(Blast Radius)

| 受影响表面 | 触发条件 | 严重性 | 当前绕过方式 |
|---|---|---|---|
| `/审核 <chapter>` 主路径 | 用户首次跑审核 + API key 已配 | 高(审核永远形同虚设,直接"通过") | 用户**自己**读章节文件人肉审核(完全绕开 Tool) |
| `_llm_review` 函数本身 | 永不触发(production 路径) | 中(代码 dead branch,但保留作为接口) | 单元测试 `test_review_llm_*` 仍可触发 |
| `decision_gate` 决策 | 永远得 `decision="pass"`,因为 `total_score=8` | 中(决策永远正确,但永远无新信息) | 无 |
| `review_chapter` workflow 报告产物 | `findings=[]` 永远空 | 中(用户期待至少一个 finding) | 无 |
| `write_chapter` rewrite 联动 | `review_chapter` 返回 `pending` → `write_chapter` 跑 rewrite loop | 低(`write_chapter` 自带 `_review_gate_node`,不走这个) | 无 |

## 4. 修复方案(Fix)

### 方案 A(★ 主推):移除早返,让 `_llm_review` 内部 fallback 兜底

移除 `_aggregate_reviews_node` 的 `if review_llm is None: deterministic` 早返,让 `_llm_review` 始终被调用,在其内部已有的 `getattr(deps, "review_llm", None) → _get_llm(get_settings())` 路径自然走 API key。LLM 真的失败时再 catch `Exception` 降级。

```python
# fix proposal — src/writer/workflows/review_chapter.py:_aggregate_reviews_node

def _aggregate_reviews_node(state: ReviewerState) -> ReviewerState:
    deps = _get_deps()
    chapter_text = state.get("chapter_text", "")
    active_foreshadows = state.get("active_foreshadows", [])
    focus = state.get("focus", [])
    try:
        review = _llm_review(deps, chapter_text, active_foreshadows, focus)
    except Exception as exc:  # noqa: BLE001
        # LLM 错误(包括 API key 未配置 / 调用失败 / schema 不匹配):
        # 降级到 deterministic。这是预期的 fallback,不是 bug。
        from writer.workflows.types import ConcernVerdict

        low = ConcernVerdict.model_validate({"score": 4, "pass": False, "findings": []})
        low_with_error = ConcernVerdict.model_validate(
            {"score": 4, "pass": False, "findings": [f"LLM 错误: {exc}"]}
        )
        review = MultiConcernReview(
            continuity=low_with_error,
            pacing=low,
            prose=low,
            total_score=4,
            summary=f"LLM 调用失败: {exc}",
        )
    ...
```

**关键差别**:
- **不判断** `deps.review_llm` — 让 `_llm_review` 内部统一处理 test/production 两条路径
- **`Exception` 捕获**包含两种情形:(1) `_get_llm(get_settings())` 因无 API key 抛 `LLMConfigError` (2) LLM 调用本身超时/解析失败
- **fallback 行为**:`_deterministic_review` 不再被"乐观早返",只被"失败兜底"调用 — 这才是 production 路径的预期

### 方案 B(备选):判断改成 `prose_client.name == "deterministic"`

镜像 `write_chapter._review_gate_node:269-275` 的判断模式:

```python
prose_client_name = deps.prose_client.name if deps.prose_client else "deterministic"
if prose_client_name == "deterministic":
    review = _deterministic_review(...)
else:
    review = _llm_review(...)
```

**否决理由**:把"LLM 是否可用"耦合到 `prose_client.name` 是错误耦合 — `prose_client.name` 表示的是"章节草稿是 LLM 写的还是 deterministic 写的",与"审核 LLM 是否可用"是两个独立维度。如果用户配了 LLM 但走 deterministic mode 写章节(production 不太可能但理论上),审核 LLM 不应该自动禁用。

### 方案 C(备选):增加 `settings.has_api_key` 判断

```python
from writer.config import get_settings
if not get_settings().has_api_key:
    review = _deterministic_review(...)
else:
    try:
        review = _llm_review(deps, ...)
    except LLMConfigError:
        review = _deterministic_review(...)
```

**否决理由**:与方案 A 重复 — 方案 A 的 `except Exception` 已覆盖 `LLMConfigError`。多写一层 `has_api_key` 判断等于在 `_llm_review` 已经做了 fallback 的基础上再做一次,反而引入不一致性(API key 配了但 key 过期时,`_llm_review` 抛 `AuthenticationError` 时怎么走?)。

## 5. 验证步骤(Manual Reproduction)

```bash
# 1. 配 API key
echo "OPENAI_API_KEY=sk-your-key" > /tmp/test-bug03/.env
cd /tmp/test-bug03
uv run writer doctor  # 确认 has_api_key=True

# 2. 创建项目 + 写两章
printf "/init 一个穿越到唐朝的程序员 --genre 其他\n/创作 1.1\n/创作 1.2\n" | uv run writer

# 3. 审核
printf "/审核 1.2\n" | uv run writer
cat manuscript/reviews/chapter-1.2-*.json | jq '.summary, .concerns'

# 期望(buggy):
#   "summary": "deterministic review (no LLM configured)"
#   所有 concerns: {"score": 8, "pass": true, "findings": [...]}

# 期望(修复后):
#   "summary": "本章开篇..."  (真实 LLM 评语)
#   至少一个 concern 有 findings 或 score < 8
```

e2e 路径(强制 deterministic 兜底):

```bash
# 不配 API key → 期望走 deterministic(正常 fallback)
unset OPENAI_API_KEY
printf "/init ...\n/创作 1.1\n/审核 1.1\n" | uv run writer
# 期望:summary 含 "deterministic" 或 "LLM 调用失败: No API key"
```

## 6. 回归测试用例清单

| 测试文件 | 测试名 | 关键断言 | 类型 |
|---|---|---|---|
| `tests/test_workflows_review_chapter.py` | `test_aggregate_reviews_uses_llm_when_api_key_set` | mock `settings.has_api_key=True` + 不注入 `review_llm`,断言调用了 `_llm_review` 而非 `_deterministic_review`(可用 mock counter) | NEW |
| `tests/test_workflows_review_chapter.py` | `test_aggregate_reviews_falls_back_to_deterministic_when_no_api_key` | mock `settings.has_api_key=False` + `get_llm` 抛 `LLMConfigError`,断言 `MultiConcernReview.summary` 含 "LLM 调用失败" 或 "No API key" | NEW |
| `tests/test_workflows_review_chapter.py` | `test_review_llm_injected_overrides_settings` | 同时注入 `review_llm=fake_llm` + `settings.has_api_key=True`,断言使用注入 LLM(优先级正确) | NEW |
| `tests/test_workflows_review_chapter.py` | `test_review_llm_none_still_calls_llm_review` | 旧 `test_review_llm_none_*` 系列断言需更新:`review_llm=None` 不再早返 deterministic | MODIFY(改断言:_llm_review 被调用,fake_llm 构造 mock) |
| `tests/test_workflows_review_chapter.py` | `test_no_api_key_fallback_message_includes_error` | 断言 fallback `MultiConcernReview.continuity.findings[0]` 含 `"LLM 错误:"` 前缀 | NEW |
| e2e | `tests/e2e/test_repl_review_uses_llm.py` | REPL 启动配 mock API key,跑 `/创作 1.1` + `/审核 1.1`,断言 review JSON 的 `findings` 非空 | NEW e2e |

## 7. 风险与遗留(Risks & Follow-ups)

### 修复后仍未解决的相邻问题

- **`review_chapter` 缺 retry 机制**:`_llm_review` 失败一次就降级,没有 `write_chapter._review_gate_node` 的 `max_retries` 循环。可作未来 change 跟进,但不在本 bug 范围。
- **`decision_gate` 阈值硬编码**(pass ≥ 8, tweak ≥ 6):阈值常量在 `src/writer/workflows/types.py` 中,与本 bug 独立。
- **`_deterministic_review` 与 LLM review 的 schema 兼容性**:两者必须都填 `MultiConcernReview` 的 4 个字段,`decision_gate` 假设 `total_score` 与 3 个 `concern.score` 同时存在。已验证兼容。

### 与 OpenSpec 的关系

- **未来 change 提案建议名**:`fix-review-chapter-llm-fallback`
- **可能需要的 spec delta**:`engine-loop` spec 的 `#### Scenario: /审核 workflow runs` 需补一句"production 默认装配时调用 LLM 审核,无 API key 时降级"
- **文档同步**:`docs/命令与用户流程.md` 中 `/审核` 的"S0-S5 可用性矩阵"无需改(命令本身可用,只是结果质量因 API key 不同)

### 关联 bug

- 与 [Bug 1](./01-tool-loop-not-rebound.md) **间接相关**:`tool_loop` 重建失败时,LLM 工具循环也可能错过 `.writer/cache` 写入(虽然不影响 `review_chapter`,但同根问题)。
- 与 [Bug 2](./02-action-answer-ignored-by-tool-loop.md) **正交**:`_initial_messages` 修复影响 LLM 工具循环的 system prompt,不影响 `_llm_review` 的 system 拼装(后者独立构造)。