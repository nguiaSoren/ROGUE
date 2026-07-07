#!/usr/bin/env python
"""Q17 offline extractor A/B — per-field agreement vs the golden fixtures.

Runs one or more extractors over ROGUE's golden (source-doc → AttackPrimitive)
fixtures and prints, per AttackPrimitive slot, how well each reproduces the
golden value — plus a projection of how the local-first cascade would behave
(accept vs escalate) on the same docs.

$0 by default: a ``local/<model>`` extractor runs against your local Ollama /
vLLM endpoint for free. The Haiku baseline (the bar a local model must clear)
is a real paid call and is therefore OPT-IN behind ``--include-haiku`` (cents).

    # $0 local-only run (Ollama serving qwen2.5:3b):
    OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama \
      uv run python scripts/extract/eval_extractor_fields.py --models local/qwen2.5:3b

    # Add the paid Haiku baseline (a few cents):
    uv run python scripts/extract/eval_extractor_fields.py \
      --models local/qwen2.5:3b --include-haiku

Only fixtures 01 and 02 carry a source document on disk; 03 is golden-only and
is skipped (reported). This is a SMALL-n harness (n=2 doc pairs) — it is a
directional signal + the mechanism check, not a powered benchmark. Read the
honest caveats in docs/research/extraction_cascade.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Repo-root import shim (mirrors scripts/harvest/*).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rogue.extract.extraction_agent import ExtractionAgent  # noqa: E402
from rogue.extract.field_eval import (  # noqa: E402
    aggregate,
    grounding_score,
    score_fields,
)

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
# (source doc, golden json, source_url, source_type)
PAIRS = [
    (
        "multilingual_paper.html",
        "01_multilingual_african_languages.json",
        "https://arxiv.org/abs/2605.18239",
        "arxiv",
    ),
    (
        "copirate_365.html",
        "02_copirate_365_cve_2026_24299.json",
        "https://example.com/copirate-365",
        "blog",
    ),
]


async def run_model(model: str, grounding_threshold: float) -> dict:
    agent = ExtractionAgent(model=model, prompt_version="v3")
    scores = []
    cascade_rows = []
    for doc_name, golden_name, url, stype in PAIRS:
        doc = (FIXTURES / doc_name).read_text(encoding="utf-8", errors="ignore")
        golden = json.loads((FIXTURES / golden_name).read_text())
        prim = await agent.extract(doc, url, stype)
        s = score_fields(prim, golden, source_text=doc, doc=doc_name)
        scores.append(s)
        # Cascade projection: accept iff grounded, schema-valid primitive.
        if prim is None:
            decision = "escalate(abstain)"
        else:
            gs = grounding_score(prim.payload_template or "", doc)
            decision = (
                "accept" if (prim.payload_template or "").strip() and gs >= grounding_threshold
                else f"escalate(fabrication-floor g={gs:.2f})"
            )
        cascade_rows.append((doc_name, decision))
    return {"model": model, "agg": aggregate(scores), "cascade": cascade_rows}


def print_report(result: dict) -> None:
    agg = result["agg"]
    print(f"\n{'='*66}\nMODEL: {result['model']}\n{'='*66}")
    print(f"recall (flagged the attack): {agg['recall']}  "
          f"({agg['n_fired']}/{agg['n_docs']} docs)")
    print(f"structural macro field-agreement (enum/bool/set/dict/ordinal): "
          f"{agg['structural_macro_field_agreement']}")
    print(f"all-fields macro (incl. payload_template grounding): "
          f"{agg['conditional_macro_field_agreement']}")
    if agg["fields"]:
        print(f"\n  {'field':<32}{'kind':<9}{'agree':>7}{'n':>4}")
        print(f"  {'-'*32}{'-'*9}{'-'*7}{'-'*4}")
        for name, d in agg["fields"].items():
            print(f"  {name:<32}{d['kind']:<9}{str(d['agreement']):>7}{d['n']:>4}")
    print("\n  cascade projection (would the local-first gate accept?):")
    for doc, decision in result["cascade"]:
        print(f"    {doc:<32} -> {decision}")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--models",
        default="local/qwen2.5:3b",
        help="comma-separated extractor model ids (local/ = $0, openai/, anthropic/)",
    )
    ap.add_argument(
        "--include-haiku",
        action="store_true",
        help="ALSO run the paid Haiku baseline (anthropic/claude-haiku-4-5) — costs cents",
    )
    ap.add_argument("--grounding-threshold", type=float, default=0.15)
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.include_haiku and "anthropic/claude-haiku-4-5" not in models:
        models.append("anthropic/claude-haiku-4-5")

    # Convenience: if a local/ model is requested and no endpoint is set, default
    # to the documented Ollama endpoint so the $0 path just works.
    if any(m.startswith("local/") for m in models) and not os.environ.get("OPENAI_BASE_URL"):
        os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:11434/v1")
        os.environ.setdefault("OPENAI_API_KEY", "ollama")
        print("[info] OPENAI_BASE_URL unset — defaulting local/ to "
              "http://localhost:11434/v1 (Ollama)")

    results = []
    for m in models:
        if m.startswith("anthropic/"):
            print(f"[warn] {m} is a PAID call ({len(PAIRS)} docs, ~cents)")
        results.append(await run_model(m, args.grounding_threshold))

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        for r in results:
            print_report(r)
        print("\nNOTE: n=2 source-doc fixtures (03 is golden-only, skipped). "
              "Directional signal, not a powered benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
