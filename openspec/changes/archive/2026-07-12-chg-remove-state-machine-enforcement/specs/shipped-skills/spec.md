## MODIFIED Requirements

### Requirement: Shipped SKILL.md frontmatter is valid YAML

Every shipped directive's ``SKILL.md`` MUST have a valid YAML frontmatter with two required fields: ``command`` and ``description``. The ``requires_states`` field MUST NOT be present in shipped frontmatter — the engine no longer enforces lifecycle gating (see ``chg-remove-state-machine-enforcement``); directive availability is determined entirely by directive registration and the LLM's runtime interpretation of file state inside the directive body.

#### Scenario: Frontmatter parses without error

- **WHEN** any shipped SKILL.md is read
- **THEN** the frontmatter MUST parse via ``yaml.safe_load`` without raising
- **AND** MUST contain ``command`` and ``description`` keys
- **AND** MUST NOT contain a ``requires_states`` key

#### Scenario: Extra fields in frontmatter are tolerated

- **WHEN** a user-edited project-level SKILL.md (post-``create_new_workspace``) still contains a legacy ``requires_states`` line that the user has not removed
- **THEN** the loader MUST NOT raise
- **AND** MUST register the directive using ``command`` and ``description`` only
- **AND** MUST silently ignore the ``requires_states`` value (it has no engine-level effect)