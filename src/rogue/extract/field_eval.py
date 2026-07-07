"""Field-level agreement scoring for the extraction A/B (Q17).

Purpose
-------
Answer, per AttackPrimitive *slot*, "does extractor X reproduce the golden
value?" — the measurement the Q17 build recommendation calls for ("score
field-level F1 per slot vs the golden JSON"). It underlies two things:

  1. the offline extractor A/B (`scripts/extract/eval_extractor_fields.py`),
     which runs a local model ($0) and/or Haiku against the golden fixtures and
     prints a per-field agreement table; and

  2. the cascade's *span-grounding* acceptance gate (`extract/cascade.py`) — the
     precision mechanism Lincoln (2605.05532) attributes a domain-SLM's
     fewer-hallucinated-fields to: a non-enum field is trustworthy only if its
     literal content is grounded in the source document.

The scorer is deliberately field-type-aware because the fields fail differently.
Closed-set enums (`family`, `vector`, `base_severity`) and copy/named-entity
fields are where small models are strong (Lincoln §4.1); free-text synthesis
fields (`payload_template`, `payload_slots`, `reproducibility_score`) are where
every model — Haiku included — is weaker, so they are scored with tolerance and
grounding rather than exact match, and honestly labelled as soft.

No new dependency: pure stdlib + the AttackPrimitive schema.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rogue.schemas import AttackPrimitive


# Fields grouped by how they should be compared. Each group maps to a scoring
# rule below. Kept explicit (not schema-introspected) so the eval is legible and
# a schema addition doesn't silently start being scored the wrong way.
_ENUM_FIELDS: tuple[str, ...] = ("family", "vector", "base_severity")
_BOOL_FIELDS: tuple[str, ...] = (
    "requires_multi_turn",
    "requires_system_prompt_access",
    "requires_multimodal",
)
_SET_FIELDS: tuple[str, ...] = (
    "secondary_families",
    "requires_tools",
    "target_models_claimed",
)
#: free-text synthesis field scored by source-grounding, not exact match.
_TEXT_FIELD = "payload_template"
#: ordinal 1–10 field scored with ±1 tolerance.
_ORDINAL_FIELD = "reproducibility_score"
#: dict field scored by key-set F1.
_DICT_FIELD = "payload_slots"

# Tokenizer for span-grounding: significant word-ish tokens (≥4 chars) so we
# don't match on "the"/"a"/punctuation. Slot placeholders like ``{language}``
# are stripped before tokenizing (they're templated, not literal source text).
_SLOT_RE = re.compile(r"\{[^{}]*\}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{4,}")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(_SLOT_RE.sub(" ", text or ""))}


def _set_f1(pred: Any, gold: Any) -> float:
    p = {str(x).lower() for x in (pred or [])}
    g = {str(x).lower() for x in (gold or [])}
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    tp = len(p & g)
    if tp == 0:
        return 0.0
    prec, rec = tp / len(p), tp / len(g)
    return 2 * prec * rec / (prec + rec)


def grounding_score(text: str, source_text: str) -> float:
    """Fraction of a field's significant literal tokens present in the source doc.

    Lincoln's precision mechanism (2605.05532 §4.1) in one function: a synthesised
    field (here ``payload_template``) is trustworthy to the extent its literal
    content was *copied from the document* rather than fabricated. Slot
    placeholders are stripped first (they are templated, not quoted from source).
    Returns 1.0 for an empty field (nothing to ground) so it never penalises a
    legitimately terse payload; the caller pairs it with a non-empty check.
    """
    toks = _tokens(text)
    if not toks:
        return 1.0
    src = _tokens(source_text)
    return len(toks & src) / len(toks)


@dataclass
class FieldScore:
    name: str
    kind: str  # enum | bool | set | dict | ordinal | text
    score: float  # agreement in [0, 1]
    pred: Any = None
    gold: Any = None


@dataclass
class ExtractionScore:
    """Per-document score: the is_attack decision + per-field agreement."""

    doc: str
    predicted_attack: bool
    golden_attack: bool
    fields: list[FieldScore] = field(default_factory=list)

    @property
    def decision_correct(self) -> bool:
        return self.predicted_attack == self.golden_attack

    def field_map(self) -> dict[str, float]:
        return {f.name: f.score for f in self.fields}


def score_fields(
    predicted: AttackPrimitive | None,
    golden: dict[str, Any],
    *,
    source_text: str = "",
    doc: str = "",
) -> ExtractionScore:
    """Score one extractor output against a golden AttackPrimitive dict.

    ``golden`` is the on-disk fixture JSON (all 3 goldens are attacks). When
    ``predicted`` is None the extractor abstained: the decision is scored as a
    miss and no per-field scores are emitted (there is nothing to compare). When
    present, each field is scored by its type-appropriate rule. ``source_text``
    (the raw document) enables the payload_template grounding score.
    """
    golden_attack = golden.get("is_attack", True) is not False
    if predicted is None:
        return ExtractionScore(
            doc=doc, predicted_attack=False, golden_attack=golden_attack
        )

    pred = predicted.model_dump(mode="json")
    scores: list[FieldScore] = []

    for name in _ENUM_FIELDS:
        pv, gv = pred.get(name), golden.get(name)
        scores.append(
            FieldScore(name, "enum", 1.0 if pv == gv and gv is not None else 0.0, pv, gv)
        )
    for name in _BOOL_FIELDS:
        pv, gv = bool(pred.get(name)), bool(golden.get(name))
        scores.append(FieldScore(name, "bool", 1.0 if pv == gv else 0.0, pv, gv))
    for name in _SET_FIELDS:
        pv, gv = pred.get(name), golden.get(name)
        scores.append(FieldScore(name, "set", _set_f1(pv, gv), pv, gv))

    # payload_slots — key-set F1 (the keys the extractor found, not their values,
    # which are free-text and doc-specific).
    ps_pred, ps_gold = pred.get(_DICT_FIELD) or {}, golden.get(_DICT_FIELD) or {}
    scores.append(
        FieldScore(
            _DICT_FIELD,
            "dict",
            _set_f1(list(ps_pred.keys()), list(ps_gold.keys())),
            sorted(ps_pred.keys()),
            sorted(ps_gold.keys()),
        )
    )

    # reproducibility_score — ordinal, ±1 tolerance (a 8-vs-9 is agreement).
    rp, rg = pred.get(_ORDINAL_FIELD), golden.get(_ORDINAL_FIELD)
    ord_ok = (
        isinstance(rp, (int, float))
        and isinstance(rg, (int, float))
        and abs(rp - rg) <= 1
    )
    scores.append(FieldScore(_ORDINAL_FIELD, "ordinal", 1.0 if ord_ok else 0.0, rp, rg))

    # payload_template — grounded in the SOURCE (not the golden template, which
    # is a normalised example). Non-empty AND ≥50% of its literal tokens appear
    # in the document. Labelled 'text' so aggregates can report it separately.
    pt = pred.get(_TEXT_FIELD) or ""
    if source_text:
        gs = grounding_score(pt, source_text) if pt.strip() else 0.0
    else:
        gs = 1.0 if pt.strip() else 0.0
    scores.append(FieldScore(_TEXT_FIELD, "text", gs, (pt or "")[:80], None))

    return ExtractionScore(
        doc=doc,
        predicted_attack=True,
        golden_attack=golden_attack,
        fields=scores,
    )


def aggregate(scores: list[ExtractionScore]) -> dict[str, Any]:
    """Roll per-doc scores into a per-field agreement table + headline numbers.

    Reports two decisions honestly: ``recall`` (did the extractor flag the
    attack at all) and ``conditional_field_agreement`` (per-field agreement
    computed ONLY over docs the extractor did not abstain on — so a model that
    abstains on everything doesn't score 1.0 by never being wrong).
    """
    n = len(scores)
    n_recall = sum(1 for s in scores if s.predicted_attack and s.golden_attack)
    fired = [s for s in scores if s.predicted_attack]

    per_field: dict[str, dict[str, Any]] = {}
    for s in fired:
        for f in s.fields:
            slot = per_field.setdefault(f.name, {"kind": f.kind, "vals": []})
            slot["vals"].append(f.score)
    field_table = {
        name: {
            "kind": d["kind"],
            "agreement": round(sum(d["vals"]) / len(d["vals"]), 4) if d["vals"] else None,
            "n": len(d["vals"]),
        }
        for name, d in per_field.items()
    }
    macro = (
        round(sum(v["agreement"] for v in field_table.values()) / len(field_table), 4)
        if field_table
        else None
    )
    # Structural macro EXCLUDES the free-text grounding signal (payload_template),
    # which grounds only partially even for correct reconstructed payloads and so
    # unfairly drags an all-fields macro down. Report both, honestly labelled.
    structural = {
        k: v for k, v in field_table.items() if v["kind"] != "text"
    }
    structural_macro = (
        round(sum(v["agreement"] for v in structural.values()) / len(structural), 4)
        if structural
        else None
    )
    return {
        "n_docs": n,
        "recall": round(n_recall / n, 4) if n else None,
        "n_fired": len(fired),
        "conditional_macro_field_agreement": macro,
        "structural_macro_field_agreement": structural_macro,
        "fields": field_table,
    }
