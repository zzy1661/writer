## ADDED Requirements

### Requirement: LLM Provider Factory

The system SHALL provide a `get_llm(settings: Settings) -> ChatOpenAI` factory in `src/writer/llm/provider.py` that instantiates a LangChain `ChatOpenAI` from `writer.config.Settings`.

#### Scenario: Factory returns ChatOpenAI with settings applied
- **WHEN** `get_llm()` is called with a `Settings` instance having `model="gpt-4o-mini"`, `base_url="https://api.example.com/v1"`, `temperature=0.5`, and `api_key` set
- **THEN** the returned object MUST be a `ChatOpenAI` (or compatible mock) with `model_name="gpt-4o-mini"`, `openai_api_base="https://api.example.com/v1"`, `temperature=0.5`, and `openai_api_key` set from settings

#### Scenario: Missing API key raises explicit error
- **WHEN** `get_llm()` is called with `settings.has_api_key is False`
- **THEN** it MUST raise a `LLMConfigError` (or subclass of `ValueError`) whose message mentions `WRITER_API_KEY`

#### Scenario: Base URL honored for OpenAI-compatible APIs
- **WHEN** `settings.base_url="https://api.deepseek.com/v1"` and `settings.model="deepseek-chat"`
- **THEN** the returned ChatOpenAI MUST be configured to call that base URL with that model name

### Requirement: LLM Provider is Mockable in Tests

The system MUST allow tests to substitute a fake LLM without monkey-patching LangChain internals.

#### Scenario: Test injects FakeListLLM via monkeypatch
- **WHEN** a test monkeypatches `writer.llm.provider.get_llm` to return a `FakeListChatModel` returning a fixed string
- **THEN** `LlmIntentRouter.route()` MUST receive that string and parse it via `with_structured_output`
- **AND** the test MUST NOT need a real network call

### Requirement: LLM Package Public Surface

The system SHALL expose `get_llm` and any error types via `from writer.llm import get_llm, LLMConfigError`.

#### Scenario: Importing get_llm works
- **WHEN** a consumer runs `from writer.llm import get_llm`
- **THEN** the import MUST succeed without side effects (no LLM instantiation at import time)