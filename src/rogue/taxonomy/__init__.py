"""rogue.taxonomy — reporting-layer crosswalk from ROGUE's frozen attack taxonomy to industry frameworks.

This package does NOT define or modify any taxonomy vocabulary. The single source of truth for AttackFamily / AttackVector remains `rogue.schemas.attack_primitive` (frozen Day 0 per ROGUE_PLAN.md §4.2). Everything here is a static, hand-curated, read-only lookup that tags those frozen enum values with externally-recognized framework identifiers (OWASP LLM Top 10 2025, MITRE ATLAS, NIST AI RMF) so the threat brief can speak in language enterprise buyers already know.
"""

from .crosswalk import (
    FAMILY_CROSSWALK,
    FrameworkMapping,
    crosswalk_coverage,
    crosswalk_for_families,
    crosswalk_for_family,
    format_frameworks_line,
)

__all__ = [
    "FAMILY_CROSSWALK",
    "FrameworkMapping",
    "crosswalk_coverage",
    "crosswalk_for_families",
    "crosswalk_for_family",
    "format_frameworks_line",
]
