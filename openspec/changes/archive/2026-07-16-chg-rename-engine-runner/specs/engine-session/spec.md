## RENAMED Requirements

All requirements in this capability are pure renames (the behavioral contract is unchanged; only the class / field names are renamed):

- FROM: `### Requirement: EngineSession fixes session identity across turns`
- TO: `### Requirement: Engine fixes session identity across turns`

- FROM: `### Requirement: EngineSession holds mutable cross-turn state`
- TO: `### Requirement: Engine holds mutable cross-turn state`

- FROM: `### Requirement: EngineSession builds deps once at construction`
- TO: `### Requirement: Engine builds deps once at construction`

- FROM: `### Requirement: EngineSession rebuilds tool_runtime when project_root changes`
- TO: `### Requirement: Engine rebuilds tool_runtime when project_root changes`

- FROM: `### Requirement: EngineSession records each turn via TurnRecord`
- TO: `### Requirement: Engine records each turn via TurnRecord`

- FROM: `### Requirement: EngineSession tracks pending Interrupt across turns`
- TO: `### Requirement: Engine tracks pending Interrupt across turns`

- FROM: `### Requirement: REPL owns one EngineSession for its lifetime`
- TO: `### Requirement: REPL owns one Engine for its lifetime`

- FROM: `### Requirement: EngineSession package public surface`
- TO: `### Requirement: Engine package public surface`