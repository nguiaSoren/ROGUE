"""Bundled attack packs — curated AttackPrimitive sets that ship with the SDK.

Most customers don't know attack names; ``client.scan()`` loads the ``default`` pack. Packs are JSON
files (lists of serialized ``AttackPrimitive`` rows) sitting next to this module, so they travel in
the wheel — no DB required at scan time.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..schemas import AttackPrimitive

_PACKS_DIR = Path(__file__).parent

# Friendly attack names (what a user might pass to ``scan(attacks=[...])``) → internal family slug.
_ATTACK_ALIASES: dict[str, str] = {
    "dan": "dan_persona",
    "crescendo": "multi_turn_gradient",
    "role_hijack": "role_hijack",
    "roleplay": "policy_roleplay",
    "injection": "indirect_prompt_injection",
    "ipi": "indirect_prompt_injection",
    "prompt_injection": "indirect_prompt_injection",
    "multimodal": "multimodal_injection",
    "leak": "system_prompt_leak",
    "system_prompt_leak": "system_prompt_leak",
    "refusal_suppression": "refusal_suppression",
    "obfuscation": "obfuscation_encoding",
    "tool_hijack": "tool_use_hijack",
    "override": "direct_instruction_override",
}


def available_packs() -> list[str]:
    """Names of the bundled packs (json files in this directory)."""
    return sorted(p.stem for p in _PACKS_DIR.glob("*.json"))


def load_pack(name: str = "default") -> list[AttackPrimitive]:
    """Load a bundled pack by name → list of :class:`AttackPrimitive`."""
    path = _PACKS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"unknown attack pack {name!r}; available: {', '.join(available_packs()) or '(none)'}"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [AttackPrimitive.model_validate(row) for row in raw]


def filter_attacks(
    primitives: list[AttackPrimitive], attacks: list[str] | None
) -> list[AttackPrimitive]:
    """Keep only primitives whose family matches one of the requested attack names.

    Names are matched against the family slug directly or via :data:`_ATTACK_ALIASES`
    (so ``attacks=["dan", "crescendo"]`` selects ``dan_persona`` + ``multi_turn_gradient``).
    """
    if not attacks:
        return primitives
    wanted = {_ATTACK_ALIASES.get(a.lower(), a.lower()) for a in attacks}
    return [p for p in primitives if p.family.value in wanted]


__all__ = ["available_packs", "load_pack", "filter_attacks"]
