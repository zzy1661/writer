## MODIFIED Requirements

### Requirement: production_deps always wires an LLMProseClient

`RunnerDeps.prose_client: LLMProseClient` (renamed from `EngineDeps.prose_client`) MUST be set by `production_deps` to either `RealProseClient(get_llm(settings))` (when `settings.has_api_key` is True) or `DeterministicProseClient(prep_context=writer.context.prep_context)` (otherwise). The field MUST NOT be `None` under any configuration.

#### Scenario: production_deps with API key wires RealProseClient
- **WHEN** `production_deps(project_root=root)` is called with `settings.has_api_key=True`
- **THEN** `deps.prose_client.name` MUST equal `"real"`