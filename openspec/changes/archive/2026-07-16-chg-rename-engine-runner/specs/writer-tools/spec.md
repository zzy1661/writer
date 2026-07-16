## MODIFIED Requirements

### Requirement: ToolRuntime exposes allowed_write_paths for customization

The `ToolRuntime` constructor MUST accept an `allowed_write_paths: frozenset[str]` keyword-only parameter that overrides the default `DEFAULT_WRITE_WHITELIST` when supplied. The parameter MUST be keyword-only (no positional usage) and MUST default to `DEFAULT_WRITE_WHITELIST` when omitted so existing call sites continue to compile.

#### Scenario: production_deps uses default whitelist
- **WHEN** `production_deps(project_root=root)` is called
- **THEN** the returned `RunnerDeps.tool_runtime.allowed_write_paths` (renamed from `EngineDeps.tool_runtime.allowed_write_paths`) MUST equal `DEFAULT_WRITE_WHITELIST`