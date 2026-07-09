"""Shipped agent sources — drift detection metadata.

Each entry records the expected ``sha256`` of the shipped ``.md``
file so :func:`writer.agents.registry._check_builtin_sources_drift`
can warn at registry construction time if the file was modified
after the recorded hash. This is a soft check (the registry still
loads the file) but a useful maintenance signal.

To refresh the hash after editing a shipped file:

1. Compute ``sha256 src/writer/agents/_shipped/<name>.md``
2. Update the matching entry's ``source_sha256`` field
3. Run ``uv run pytest tests/test_agent_registry.py -k drift`` to
   confirm the warning now disappears
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinAgentSource:
    """One shipped agent's identity + integrity metadata.

    Fields:

    * ``mirror_filename`` — the file name under
      ``src/writer/agents/_shipped/`` (e.g. ``历史.md``).
    * ``source_module`` — the dotted module path used by
      ``importlib.resources`` (``writer.agents._shipped``).
    * ``source_sha256`` — expected sha256 of the file's UTF-8
      content; the registry emits a WARNING on mismatch.
    """

    mirror_filename: str
    source_module: str
    source_sha256: str


#: Shipped agents shipped at ``writer.agents._shipped/``. The order
#: is informational only; discovery sorts by filename. sha256 values
#: are filled in by the apply-phase write of the actual .md files
#: (see tasks 2.5 / 2.6 in ``fea-agent-mirror/tasks.md``). Until then
#: each entry uses a placeholder; drift detection will fire loudly
#: on the first registry construction, which is the apply-phase
#: trigger to refresh them.
BUILTIN_AGENT_SOURCES: tuple[BuiltinAgentSource, ...] = (
    BuiltinAgentSource(
        mirror_filename="other.md",
        source_module="writer.agents._shipped",
        source_sha256="3a0060e21ff31c9db0a1395f7ed98767ebd6c1027fa3c01b0f6e5e976735c625",
    ),
    BuiltinAgentSource(
        mirror_filename="历史.md",
        source_module="writer.agents._shipped",
        source_sha256="b602b870cf1513809d2f1ed8c238e09c38ba0b2295338ce404079440e99beafd",
    ),
    BuiltinAgentSource(
        mirror_filename="言情.md",
        source_module="writer.agents._shipped",
        source_sha256="388b81262e6566b54b0d821bc7aec7f4d7c8f429c831dc97430797a5d6e55326",
    ),
    BuiltinAgentSource(
        mirror_filename="玄幻.md",
        source_module="writer.agents._shipped",
        source_sha256="23f448f5b62f80a9d70c59e20b2555054bb9e206c6930022a1e5f83e8ecfd08d",
    ),
)


__all__ = ["BUILTIN_AGENT_SOURCES", "BuiltinAgentSource"]
