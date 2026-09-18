CURRENT_SPLITTER_VERSION = "legal-text-splitter-v1"
LEGACY_SPLITTER_VERSION = "legacy-text-chunker-v1"

# Batch 4 preserves the legacy boundary algorithm while exposing it through
# LangChain's splitter interface. Future algorithm changes must replace this set.
COMPATIBLE_SPLITTER_VERSIONS = frozenset(
    {CURRENT_SPLITTER_VERSION, LEGACY_SPLITTER_VERSION}
)
