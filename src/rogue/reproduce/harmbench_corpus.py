"""HarmBench behaviors as CATEGORIZED AttackPrimitives.

HarmBench (Mazeika et al., 2402.04249) is a standardized harmful-behavior eval — behaviors grouped
into semantic categories (cybercrime_intrusion, chemical_biological, misinformation_disinformation,
harassment_bullying, illegal, harmful). We freeze the standard + contextual behaviors (ex-copyright)
and load them as ``AttackPrimitive``s tagged with the semantic category (``emergent_label``), so the
robustness board / endpoint scans can break a model's robustness DOWN BY HARM CATEGORY — a richer story
than one aggregate rate ("holds on cybercrime, caves on misinformation").

This is the *attack side* only. It does NOT replace ROGUE's calibrated per-breach-type judge (P2) —
HarmBench's own classifier is a narrow harm-axis specialist (see scripts/calibration/eval_harmbench_baseline.py,
where it serves as an independent validation baseline, not the judge).
"""

from __future__ import annotations

import json
from pathlib import Path

from rogue.schemas import AttackPrimitive

_HARMBENCH = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "harmbench.jsonl"
# A valid AttackPrimitive scaffold (golden fixture) — reproduce only reads a subset of fields; we swap
# the payload/id/title/category so we don't have to hand-fill every required enum + source.
_SCAFFOLD = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "02_copirate_365_cve_2026_24299.json"

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (ULID alphabet)


def _pid(behavior_id: str) -> str:
    """A deterministic ULID-shaped (26-char Crockford-base32) primitive id from a HarmBench BehaviorID."""
    h = 0
    for ch in behavior_id:
        h = (h * 131 + ord(ch)) & ((1 << 130) - 1)
    body = "".join(_B32[(h >> (5 * i)) & 31] for i in range(21))  # 21 chars
    return ("01HARMB" + body)[:26]


def load_harmbench_primitives(
    limit: int | None = None,
    categories: list[str] | None = None,
) -> list[AttackPrimitive]:
    """HarmBench behaviors → ``AttackPrimitive``s tagged by semantic category (``emergent_label``).

    ``categories`` filters to a subset of semantic categories (e.g. ``["cybercrime_intrusion"]``);
    ``limit`` caps the count (after filtering). A behavior's ``context`` (contextual functional
    category) is prepended to the payload so the primitive carries the full harmful request.
    """
    rows = [json.loads(x) for x in _HARMBENCH.read_text().splitlines() if x.strip()]
    if categories:
        wanted = set(categories)
        rows = [r for r in rows if r["semantic_category"] in wanted]
    if limit is not None:
        rows = rows[:limit]

    scaffold = AttackPrimitive.model_validate_json(_SCAFFOLD.read_text())
    prims: list[AttackPrimitive] = []
    for r in rows:
        payload = f"{r['context']}\n\n{r['behavior']}" if r.get("context") else r["behavior"]
        prims.append(
            scaffold.model_copy(
                update={
                    "primitive_id": _pid(r["behavior_id"]),
                    "payload_template": payload,
                    "title": r["behavior"][:120],
                    "emergent_label": r["semantic_category"],  # the queryable harm-category tag
                }
            )
        )
    return prims


def harmbench_categories() -> list[str]:
    """The semantic categories present in the frozen HarmBench corpus (sorted, stable)."""
    rows = [json.loads(x) for x in _HARMBENCH.read_text().splitlines() if x.strip()]
    return sorted({r["semantic_category"] for r in rows})


__all__ = ["load_harmbench_primitives", "harmbench_categories"]
