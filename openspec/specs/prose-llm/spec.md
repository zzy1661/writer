# prose-llm Specification

## Purpose
TBD - created by archiving change real-writing-pipeline. Update Purpose after archive.
## Requirements
### Requirement: LLMProseClient Protocol with generate_text

The system SHALL define `writer.llm.prose.LLMProseClient` as a `typing.Protocol` with a single method:

```python
class LLMProseClient(Protocol):
    name: str  # "real" or "deterministic"; surfaced in metrics
    def generate_text(self, *, system: str, user: str) -> str: ...
```

`generate_text` MUST accept two keyword arguments (`system`, `user`) and return a single string (the model response). The client MUST NOT raise on the happy path; transport / parse errors SHOULD propagate as `LLMProseError` (a new `ValueError` subclass) so callers can `except` cleanly.

#### Scenario: client exposes name and a callable generate_text
- **WHEN** a test creates a `RealProseClient(llm=stub_llm)` instance
- **THEN** `client.name` MUST equal `"real"`
- **AND** `client.generate_text(system="x", user="y")` MUST return a `str`

#### Scenario: custom LLMProseClient implementations satisfy the Protocol
- **WHEN** a test defines a class with `name = "fake"` and `def generate_text(self, *, system, user) -> str: return "ok"`
- **THEN** `isinstance(instance, LLMProseClient)` MUST be True (Protocol is `@runtime_checkable`)

### Requirement: RealProseClient wraps ChatOpenAI

The system SHALL provide `RealProseClient` constructed as `RealProseClient(llm: BaseChatModel)`. Its `generate_text` MUST call `llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])` and return the response content coerced to `str` (same coercion rules as `writer.llm.structured._message_content_to_text`).

#### Scenario: RealProseClient invokes the underlying LLM once
- **WHEN** a fake LLM records every `invoke` call and `client.generate_text(system="A", user="B")` is called
- **THEN** the fake MUST record exactly one `invoke` call
- **AND** the call's messages MUST be `[SystemMessage("A"), HumanMessage("B")]` in that order

#### Scenario: RealProseClient raises LLMProseError on unexpected content type
- **WHEN** the underlying LLM returns a response whose content is neither str nor list-of-strings-or-dicts
- **THEN** `generate_text` MUST raise `LLMProseError` with a message mentioning the unexpected content type

### Requirement: DeterministicProseClient assembles prose without LLM

The system SHALL provide `DeterministicProseClient` constructed as `DeterministicProseClient(prep_context_fn: Callable[..., Any])` (or any callable that returns a context pack with `canon_block` and `history_block` fields). Its `generate_text` MUST return a deterministic prose string assembled from the prep_context fields plus the `user` message, with NO network call.

#### Scenario: DeterministicProseClient returns deterministic text for fixed inputs
- **WHEN** the same `(system, user)` is passed to `DeterministicProseClient` twice
- **THEN** the returned strings MUST be byte-identical
- **AND** no network or `BaseChatModel.invoke` call MUST occur (assertable via a recording fake)

#### Scenario: DeterministicProseClient name is "deterministic"
- **WHEN** a `DeterministicProseClient(prep_context_fn=...)` is constructed
- **THEN** `client.name` MUST equal `"deterministic"`

### Requirement: production_deps always wires an LLMProseClient

`RunnerDeps.prose_client: LLMProseClient` (renamed from `EngineDeps.prose_client`) MUST be set by `production_deps` to either `RealProseClient(get_llm(settings))` (when `settings.has_api_key` is True) or `DeterministicProseClient(prep_context=writer.context.prep_context)` (otherwise). The field MUST NOT be `None` under any configuration.

#### Scenario: production_deps with API key wires RealProseClient
- **WHEN** `production_deps(project_root=root)` is called with `settings.has_api_key=True`
- **THEN** `deps.prose_client.name` MUST equal `"real"`

### Requirement: LLMProseError is a domain exception

The system SHALL define `writer.llm.prose.LLMProseError(ValueError)` for transport / parse / protocol failures. The engine boundary (`engine._engine_loop`'s `except Exception` arm) MUST handle it like any other exception: emit `ErrorEvent` + `Done(reason="aborted")`.

#### Scenario: LLMProseError propagates through workflow into engine aborted branch
- **WHEN** a workflow calls `client.generate_text(...)` and the client raises `LLMProseError`
- **THEN** the engine MUST emit `ErrorEvent(message="工具错误: ...")` and `Done(reason="aborted", payload={"error": "..."})`
- **AND** the workflow MUST be able to catch `LLMProseError` and convert it to `WorkflowResult(status="failed", metrics={"error": str(exc)})` if the workflow wants structured failure

