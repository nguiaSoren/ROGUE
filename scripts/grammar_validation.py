#!/usr/bin/env python
"""Grammar-study research validation — the "don't fool ourselves" pass (Engineer 6).

Builds the per-primitive analysis dataset from existing rows, labels each primitive with
structural ``GrammarNode``s, runs the full controlled analysis (collinearity / family &
target stratification / BH-FDR), and writes the headline VERDICT + surviving-nodes table
+ caveats.

READ-ONLY, $0. SELECT-only on ``attack_primitives`` / ``breach_matrix`` /
``deployment_configs``. Spends no API money, writes no DB rows — only the two report
files under ``data/grammar_analysis/``.

Usage::

    uv run python scripts/grammar_validation.py                 [reads live DB, $0]
    uv run python scripts/grammar_validation.py --alpha 0.10
    uv run python scripts/grammar_validation.py --out data/grammar_analysis

The DB read is gated behind ``--yes`` only in spirit (it costs nothing); we keep it
ungated because it is strictly read-only. If the sibling labeler module isn't built yet,
a conservative built-in heuristic labeler is used so this script never hard-blocks the
parallel build.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
log = logging.getLogger("grammar_validation")


def _db_url() -> str:
    from dotenv import load_dotenv

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set (check .env)")
    return url


def _label_records(records: list) -> dict[str, set]:
    """primitive_id → set[GrammarNode]. Prefer the sibling labeler; fall back locally.

    The sibling ``rogue.grammar.labeler`` (parallel build) is expected to expose
    ``label_records(records) -> dict[str, set[GrammarNode]]`` or ``label_primitive(rec)``.
    If neither is importable yet, a conservative built-in heuristic derives nodes from
    family / secondary_families / payload_slots / requires_multi_turn so the validation
    pass can run standalone.
    """
    try:
        from rogue.grammar import labeler as _lab  # type: ignore

        if hasattr(_lab, "label_records"):
            res = _lab.label_records(records)
            if res:
                log.info("labeled via sibling labeler.label_records")
                return {k: set(v) for k, v in res.items()}
        if hasattr(_lab, "label_primitive"):
            out = {r.primitive_id: set(_lab.label_primitive(r)) for r in records}
            if any(out.values()):
                log.info("labeled via sibling labeler.label_primitive")
                return out
    except Exception as e:  # pragma: no cover - depends on parallel build state
        log.warning("sibling labeler unavailable (%s); using built-in heuristic", e)
    return _builtin_label(records)


def _builtin_label(records: list) -> dict[str, set]:
    """Conservative built-in node derivation (mirror of GRAMMAR_NODE_META rules)."""
    from rogue.schemas import GrammarNode as GN

    out: dict[str, set] = {}
    for r in records:
        fam = r.family
        sec = set(r.secondary_families or [])
        slots = r.payload_slots or {}

        def has(key: str) -> bool:
            v = slots.get(key)
            return v is not None and str(v).strip() != ""

        nodes: set = set()
        fam_set = {fam} | sec
        # family-mirroring
        if "role_hijack" in fam_set or (has("role_name") and has("role_description")):
            nodes.add(GN.ROLE_HIJACK)
        if "dan_persona" in fam_set:
            nodes.add(GN.DAN_PERSONA)
        if "policy_roleplay" in fam_set:
            nodes.add(GN.POLICY_ROLEPLAY)
        if "refusal_suppression" in fam_set:
            nodes.add(GN.REFUSAL_SUPPRESSION)
        if "direct_instruction_override" in fam_set:
            nodes.add(GN.DIRECT_OVERRIDE)
        if "system_prompt_leak" in fam_set:
            nodes.add(GN.SYSTEM_PROMPT_LEAK)
        if "training_data_extraction" in fam_set:
            nodes.add(GN.TRAINING_DATA_EXTRACTION)
        if "indirect_prompt_injection" in fam_set:
            nodes.add(GN.INDIRECT_INJECTION)
        if "tool_use_hijack" in fam_set or has("tool_name"):
            nodes.add(GN.TOOL_INVOCATION)
        if "chain_of_thought_hijack" in fam_set:
            nodes.add(GN.CHAIN_OF_THOUGHT_HIJACK)
        if "multimodal_injection" in fam_set:
            nodes.add(GN.MULTIMODAL)
        # cross-family structural
        if has("authority_claim") or has("justification"):
            nodes.add(GN.AUTHORITY_FRAME)
        if has("language") or "language_switching" in fam_set:
            nodes.add(GN.LANGUAGE_SHIFT)
        if has("encoding_scheme") or "obfuscation_encoding" in fam_set:
            nodes.add(GN.ENCODING_OBFUSCATION)
        if has("target_output_format") or has("NewResponseFormat"):
            nodes.add(GN.STRUCTURED_OUTPUT)
        if has("role_description") and fam in {"policy_roleplay", "dan_persona", "role_hijack"}:
            nodes.add(GN.FICTIONAL_FRAMING)
        if r.requires_multi_turn or fam_set & {"multi_turn_gradient", "multi_turn_persona_chain"}:
            nodes.add(GN.MULTI_TURN_ESCALATION)
        if has("trigger_phrase"):
            nodes.add(GN.TRIGGER_BACKDOOR)
        if has("exfil_destination"):
            nodes.add(GN.EXFILTRATION)
        if has("role_name") and (has("role_description") or has("personality_trait")):
            nodes.add(GN.PERSONA_CONSTRUCTION)
        if has("target_behavior") or has("target_topic"):
            nodes.add(GN.TARGET_BEHAVIOR_SPECIFICATION)
        if has("invisible_tag_instruction"):
            nodes.add(GN.INVISIBLE_INJECTION)
        if (has("rag_document") or has("poison_payload")) and "indirect_prompt_injection" in fam_set:
            nodes.add(GN.RAG_POISONING)

        out[r.primitive_id] = nodes
    return out


def _build_dataset():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from rogue.grammar.dataset import build_grammar_analysis_dataset

    engine = create_engine(_db_url())
    with Session(engine) as session:
        records = build_grammar_analysis_dataset(session)
    return records


def _jsonable(obj: Any) -> Any:
    """Recursively coerce tuples / floats(inf,nan) / sets into JSON-safe values."""
    if isinstance(obj, dict):
        return {_json_key(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, set):
        return sorted(_jsonable(x) for x in obj)
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    return obj


def _json_key(k: Any) -> str:
    if isinstance(k, tuple):
        return " × ".join(str(x) for x in k)
    return str(k)


def _fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        if math.isnan(x):
            return "—"
        if math.isinf(x):
            return "∞" if x > 0 else "-∞"
        return f"{x:.{nd}f}"
    return str(x)


def _render_md(result: dict) -> str:
    ds = result["dataset_summary"]
    fdr = result["fdr"]
    lines: list[str] = []
    lines.append("# Grammar-component predictive power — controlled validation\n")
    lines.append(
        "Adversarial 'don't fool ourselves' pass: collinearity-with-family, "
        "family/target stratification (Mantel–Haenszel), and a single "
        "Benjamini–Hochberg FDR across all node + pair tests.\n"
    )
    lines.append(f"## VERDICT: **{result['verdict'].upper()}**\n")
    lines.append(result["verdict_note"] + "\n")

    lines.append("## Dataset\n")
    lines.append(f"- primitives: {ds['n_primitives']} ({ds['n_with_breach_data']} with breach data)")
    lines.append(f"- per-primitive ANY-breach base rate: {_fmt(ds['primitive_breach_base_rate'],2)} (ceiling/saturated)")
    lines.append(f"- per-(primitive × target) units: {ds['n_target_units']} — base rate {_fmt(ds['target_unit_breach_base_rate'],2)} (the non-saturated denominator)")
    lines.append(f"- nodes observed: {ds['n_nodes_observed']}")
    lines.append(f"\n> {ds['ceiling_note']}\n")

    lines.append("## FDR\n")
    lines.append(
        f"Benjamini–Hochberg α={fdr['alpha']} across {fdr['n_total_tests']} tests "
        f"({fdr['n_node_tests']} node + {fdr['n_pair_tests']} pair). "
        f"Node rejections: {fdr['n_node_reject']}; pair rejections: {fdr['n_pair_reject']}.\n"
    )

    lines.append("## Surviving nodes (signal that clears every control)\n")
    if result["surviving_nodes"]:
        lines.append("| node | raw lift | raw OR | FDR-sig | within-family OR | target MH OR |")
        lines.append("|---|---|---|---|---|---|")
        for r in result["surviving_nodes"]:
            lines.append(
                f"| `{r['node']}` | {_fmt(r['raw_lift'],2)} | {_fmt(r['raw_odds_ratio'],2)} | "
                f"{'✓' if r['fdr_significant'] else '✗'} | {_fmt(r['within_family_pooled_or'],2)} | "
                f"{_fmt(r['target_mh_pooled_or'],2)} |"
            )
    else:
        lines.append("_None._ No node is simultaneously FDR-significant, non-circular, "
                     "within-family-surviving, and target-MH-surviving. This is a "
                     "**successful null** — it saves the AST/synthesis roadmap from "
                     "building on an effect the data does not support.\n")

    lines.append("\n## All nodes (raw + controls)\n")
    lines.append("| node | n_pres units | raw lift | raw p | FDR-sig | circular | dom. family | overlap | Cramér V | within-fam survives | target MH survives | SIGNAL |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(result["node_rows"], key=lambda x: (not x["is_signal"], x["node"])):
        raw = result["raw_node_lift"][r["node"]]
        lines.append(
            f"| `{r['node']}` | {raw['n_present_units']} | {_fmt(r['raw_lift'],2)} | "
            f"{_fmt(r['raw_p_value'],4)} | {'✓' if r['fdr_significant'] else '✗'} | "
            f"{'⚠' if r['circular'] else '·'} | {r['dominant_family'] or '—'} | "
            f"{_fmt(r['overlap_frac'],2)} | {_fmt(r['cramers_v'],2)} | "
            f"{'✓' if r['survives_family_stratification'] else '✗'} | "
            f"{'✓' if r['survives_target_stratification'] else '✗'} | "
            f"{'**YES**' if r['is_signal'] else 'no'} |"
        )

    lines.append("\n## Caveats (read before quoting any number)\n")
    for c in result["caveats"]:
        lines.append(f"- {c}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alpha", type=float, default=0.05, help="BH-FDR level (default 0.05)")
    ap.add_argument("--out", default="data/grammar_analysis", help="output dir")
    args = ap.parse_args()

    from rogue.grammar.validation import controlled_analysis

    log.info("building dataset (SELECT-only on attack_primitives / breach_matrix)…")
    records = _build_dataset()
    log.info("built %d primitive records", len(records))

    labels = _label_records(records)
    n_labeled = sum(1 for v in labels.values() if v)
    log.info("labeled %d/%d primitives with ≥1 grammar node", n_labeled, len(records))

    result = controlled_analysis(records, labels, alpha=args.alpha)
    log.info("VERDICT: %s (%d surviving nodes)", result["verdict"], len(result["surviving_nodes"]))

    out_dir = _ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "validation.json"
    md_path = out_dir / "validation.md"
    json_path.write_text(json.dumps(_jsonable(result), indent=2))
    md_path.write_text(_render_md(result))
    log.info("wrote %s", json_path)
    log.info("wrote %s", md_path)
    print(f"\nVERDICT: {result['verdict'].upper()}")
    print(result["verdict_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
