"""CLI: per-GrammarNode breach-lift table over the existing AttackPrimitive corpus.

OBSERVATIONAL, $0, READ-ONLY. Builds the grammar analysis dataset (SELECT-only),
heuristically labels every canonical non-synthesized primitive, then computes the
per-node 2×2 lift / odds-ratio / Fisher table over the per-(primitive × target) units
(the headline analysis unit — the per-primitive ANY-breach rate is a ~0.79 ceiling and
is NOT informative). Writes two artifacts:

  data/grammar_analysis/node_lift.json   — full NodeLift rows (machine-readable)
  data/grammar_analysis/node_lift.md     — a readable markdown table

NO DB WRITES. NO API CALLS. p-values are UNCORRECTED for multiple comparisons — FDR
correction is applied downstream (Engineer 6) across the full node table.

Usage
-----
  uv run python scripts/benchmark/grammar_node_lift.py
  uv run python scripts/benchmark/grammar_node_lift.py --unit per_primitive   # comparison only
  uv run python scripts/benchmark/grammar_node_lift.py --min-n 10
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

# Make sure the repo's src/ is importable when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

_OUT_DIR = _REPO_ROOT / "data" / "grammar_analysis"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grammar_node_lift",
        description=(
            "Per-GrammarNode breach-lift table (observational, read-only, $0).\n"
            "Default unit = per_target (headline); per_primitive is comparison-only."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--unit",
        choices=("per_target", "per_primitive"),
        default="per_target",
        help="Analysis unit. Default per_target (~1540 units; the headline).",
    )
    p.add_argument(
        "--min-n",
        type=int,
        default=5,
        help="Flag nodes with fewer than this many node-present units (default 5).",
    )
    p.add_argument(
        "--breach-threshold",
        type=float,
        default=0.0,
        help="Optional per-target any_breach_rate cutoff (per_target only). "
        "0.0 = use the dataset's precomputed breached flag.",
    )
    return p


def _fmt_p(p: float) -> str:
    if p < 1e-4:
        return f"{p:.2e}"
    return f"{p:.4f}"


def _write_markdown(path: Path, table, summary: dict, baseline: float, unit: str, min_n: int) -> None:
    lines: list[str] = []
    lines.append("# Grammar-node breach lift")
    lines.append("")
    lines.append(f"- Analysis unit: **{unit}**")
    lines.append(f"- Baseline breach rate (grand mean over units): **{baseline:.4f}**")
    lines.append(
        f"- Per-primitive ANY-breach base rate: **{summary['breach_base_rate']:.4f}** "
        "(a ceiling — why per_target is the headline unit, not per_primitive)"
    )
    lines.append(
        f"- Corpus: {summary['n_total']} primitives, "
        f"{summary['n_with_breach_data']} with breach data."
    )
    lines.append(f"- `min_n` flag threshold: {min_n} node-present units.")
    lines.append("")
    lines.append(
        "> **p-values are UNCORRECTED** for multiple comparisons. FDR correction is "
        "applied downstream across the full node table."
    )
    lines.append(
        "> Breach signal inherits the v1/v2 judge bias (over-reports vs judge v3). "
        "Treat absolute rates as v1/v2-baseline."
    )
    lines.append("")
    lines.append("| Node | n_with | p_with | baseline | lift_rel | OR [95% CI] | Fisher p | flag |")
    lines.append("|---|---:|---:|---:|---:|---|---:|:---:|")
    for nl in table:
        flag = "⚠" if nl.flagged else ""
        or_cell = f"{nl.odds_ratio:.2f} [{nl.or_ci_low:.2f}, {nl.or_ci_high:.2f}]"
        lines.append(
            f"| {nl.node.value} | {nl.n_with} | {nl.p_with:.3f} | {nl.baseline:.3f} "
            f"| {nl.lift_rel:.2f} | {or_cell} | {_fmt_p(nl.p_value)} | {flag} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _serialize(table) -> list[dict]:
    rows = []
    for nl in table:
        d = asdict(nl)
        d["node"] = nl.node.value  # enum -> wire string
        rows.append(d)
    return rows


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    try:
        from rogue.db.session import get_session  # type: ignore[import]
    except Exception as exc:
        print(f"ERROR: could not import DB session: {exc}", file=sys.stderr)
        print("Is the DB running?  Try: docker compose up -d --wait", file=sys.stderr)
        sys.exit(1)

    # Lazy imports — labeler is built in parallel; keep the import inside main.
    from rogue.grammar.dataset import build_grammar_analysis_dataset, dataset_summary
    from rogue.grammar.labeler import label_records
    from rogue.grammar.stats import node_lift_table

    with get_session() as session:
        print("Building grammar analysis dataset…", end=" ", flush=True)
        records = build_grammar_analysis_dataset(session)
        print(f"{len(records)} primitives loaded.")

        print("Applying heuristic labels…", end=" ", flush=True)
        labels = label_records(records)
        print("done.")

    summary = dataset_summary(records)
    table = node_lift_table(
        records,
        labels,
        unit=args.unit,
        min_n=args.min_n,
        breach_threshold=args.breach_threshold,
    )
    baseline = table[0].baseline if table else 0.0

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _OUT_DIR / "node_lift.json"
    md_path = _OUT_DIR / "node_lift.md"

    payload = {
        "unit": args.unit,
        "min_n": args.min_n,
        "breach_threshold": args.breach_threshold,
        "baseline": baseline,
        "summary": summary,
        "rows": _serialize(table),
        "note": "p-values UNCORRECTED; FDR applied downstream (Engineer 6).",
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_markdown(md_path, table, summary, baseline, args.unit, args.min_n)

    # Console summary.
    print()
    print("=" * 72)
    print(f"  GRAMMAR NODE LIFT  ({args.unit})")
    print(f"  Baseline breach rate (grand mean over units): {baseline:.4f}")
    print(
        f"  Per-primitive ANY-breach base rate: {summary['breach_base_rate']:.4f} "
        "(ceiling — per_primitive is comparison-only)"
    )
    print("=" * 72)
    print(f"  {'Node':<32}{'n_w':>5}{'p_with':>8}{'lift':>7}{'OR':>7}{'Fisher p':>12}")
    print("-" * 72)
    for nl in table:
        flag = " *" if nl.flagged else "  "
        print(
            f"  {nl.node.value:<32}{nl.n_with:>5}{nl.p_with:>8.3f}"
            f"{nl.lift_rel:>7.2f}{nl.odds_ratio:>7.2f}{_fmt_p(nl.p_value):>12}{flag}"
        )
    print("-" * 72)
    print("  * = flagged (n_with < min_n, under-powered)")
    print()
    print("  NOTE: p-values here are UNCORRECTED. FDR correction is applied")
    print("  downstream (Engineer 6) across the full node table.")
    print()
    print(f"  Wrote: {json_path}")
    print(f"  Wrote: {md_path}")


if __name__ == "__main__":
    main()
