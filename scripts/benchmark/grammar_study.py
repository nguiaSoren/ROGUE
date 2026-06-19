"""Grammar-component predictive-power study — one-command driver.

Runs the full observational analysis pipeline (read-only by default, $0):
  1. Build the primitive×target dataset from the live DB.
  2. Label every primitive with heuristic GrammarNode labels.
  3. Compute per-node lift / odds-ratio / Fisher table (per_target unit).
  4. Compute pairwise node interactions.
  5. Run the controlled validation pass.
  6. Write data/grammar_analysis/REPORT.md.
  7. Print the headline VERDICT to stdout.

Usage:
    uv run python scripts/benchmark/grammar_study.py
    uv run python scripts/benchmark/grammar_study.py --database-url postgresql+psycopg://...
    uv run python scripts/benchmark/grammar_study.py --persist-labels  # write labels to DB
    uv run python scripts/benchmark/grammar_study.py --min-n 10        # flag under-powered nodes
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_url(cli_url: str | None) -> str:
    """Resolve DB URL from CLI flag → TEST_DATABASE_URL → DATABASE_URL → default."""
    if cli_url:
        return cli_url
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("TEST_DATABASE_URL")
        or "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
    )


def _make_session(url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(url, connect_args={"connect_timeout": 10})
    return sessionmaker(bind=engine)()


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt_float(v: float, decimals: int = 3) -> str:
    return f"{v:.{decimals}f}"


def _top_n(items: list, key, n: int = 10):
    return sorted(items, key=key, reverse=True)[:n]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def _build_report(
    summary: dict,
    labels: dict,
    lifts: list,
    pairs: list,
    suppressed: int,
    verdict_dict: dict,
    min_n: int,
    generated_at: str,
) -> str:
    """Assemble the REPORT.md content from the pipeline outputs."""
    lines: list[str] = []
    a = lines.append  # shorthand

    # ---------------------------------------------------------------------- #
    # Header                                                                   #
    # ---------------------------------------------------------------------- #
    a("# Grammar-Component Predictive-Power Study — Report")
    a("")
    a(f"Generated: {generated_at}")
    a(f"Analysis unit: per-(primitive × target)  |  min_n flag threshold: {min_n}")
    a("")

    # ---------------------------------------------------------------------- #
    # §1 Dataset summary + base rate                                           #
    # ---------------------------------------------------------------------- #
    a("## 1. Dataset Summary")
    a("")
    n_total = summary["n_total"]
    n_data = summary["n_with_breach_data"]
    n_breached = summary["n_breached"]
    base_rate = summary["breach_base_rate"]
    a(f"- **Total primitives in corpus**: {n_total}")
    a(f"- **Primitives with breach data (analysable)**: {n_data}")
    a(f"- **Primitives that breached at least one target**: {n_breached}")
    a(f"- **Per-primitive ANY-breach base rate**: {_fmt_pct(base_rate)} ({n_breached}/{n_data})")
    a("")
    a(
        "> **Ceiling note** — the per-primitive ANY-breach base rate is "
        f"{_fmt_pct(base_rate)}, which is near or at a ceiling (the study spec "
        "documents 0.79 as the expected ceiling when 8 targets saturate 'any breached'). "
        "Per-primitive lift is therefore unreliable; the primary analysis unit is "
        "**per-(primitive × target)**, which provides ~10× more units and avoids "
        "ceiling saturation."
    )
    a("")
    a("> **Judge-v3 caveat** — `breach_matrix` is graded by the old v1/v2 judge. "
      "It over-reports breaches relative to judge v3. Absolute breach rates are "
      "v1/v2-baseline; treat relative lift comparisons as directionally correct.")
    a("")

    # Per-family breakdown (top 10 by count)
    family_counts = summary.get("family_counts", {})
    family_breached = summary.get("family_breached", {})
    if family_counts:
        a("### Per-family breakdown (top 10 by count)")
        a("")
        a("| Family | Count | Breached |")
        a("|--------|------:|--------:|")
        for fam, cnt in sorted(family_counts.items(), key=lambda x: -x[1])[:10]:
            br = family_breached.get(fam, 0)
            a(f"| `{fam}` | {cnt} | {br} |")
        a("")

    # Label coverage
    labeled = sum(1 for s in labels.values() if s)
    a("### Label coverage")
    a(f"- Primitives with at least one GrammarNode label: **{labeled}** / {n_total}")
    a("")

    # ---------------------------------------------------------------------- #
    # §2 Top node lifts                                                        #
    # ---------------------------------------------------------------------- #
    a("## 2. Top Node Lifts (per-target unit)")
    a("")
    a(
        "Sorted by relative lift vs corpus baseline. "
        "p-values are uncorrected Fisher exact; FDR correction applied downstream. "
        f"Rows marked ⚑ have n_with < {min_n} (under-powered)."
    )
    a("")
    a("| Node | n_with | breach_rate | baseline | lift_abs | lift_rel | OR | p_value | ⚑ |")
    a("|------|-------:|------------:|--------:|---------:|--------:|---:|--------:|:--:|")
    for nl in lifts[:15]:
        flag = "⚑" if nl.flagged else ""
        a(
            f"| `{nl.node.value}` "
            f"| {nl.n_with} "
            f"| {_fmt_pct(nl.p_with)} "
            f"| {_fmt_pct(nl.baseline)} "
            f"| {nl.lift_abs:+.3f} "
            f"| {nl.lift_rel:.2f}× "
            f"| {_fmt_float(nl.odds_ratio, 2)} "
            f"| {nl.p_value:.4f} "
            f"| {flag} |"
        )
    a("")

    # ---------------------------------------------------------------------- #
    # §3 Pairwise synergistic pairs                                            #
    # ---------------------------------------------------------------------- #
    a("## 3. Pairwise Node Interactions")
    a("")
    a(f"Suppressed pair count (insufficient data / n < {min_n}): **{suppressed}**")
    a("")

    # Pairs are Interaction dataclass instances (from rogue.grammar.combinations).
    # Fields: node_a, node_b, interaction_delta (float), synergy (bool), p_value.
    # Sort by interaction_delta descending; only show synergistic (synergy=True) pairs first.
    synergistic = [p for p in pairs if getattr(p, "synergy", False)]
    top_pairs = _top_n(synergistic, key=lambda p: getattr(p, "interaction_delta", 0.0), n=10)
    if not top_pairs:
        # Fall back to top by interaction_delta regardless of synergy flag
        top_pairs = _top_n(pairs, key=lambda p: getattr(p, "interaction_delta", 0.0), n=10)

    if top_pairs:
        a("| Node A | Node B | interaction_delta | p_value | synergy |")
        a("|--------|--------|------------------:|--------:|:-------:|")
        for p in top_pairs:
            delta = getattr(p, "interaction_delta", 0.0)
            pval = getattr(p, "p_value", None)
            syn = getattr(p, "synergy", False)
            pval_str = f"{pval:.4f}" if pval is not None else "—"
            syn_str = "yes" if syn else "no"
            na = getattr(p, "node_a")
            nb = getattr(p, "node_b")
            na_str = na.value if hasattr(na, "value") else str(na)
            nb_str = nb.value if hasattr(nb, "value") else str(nb)
            a(
                f"| `{na_str}` "
                f"| `{nb_str}` "
                f"| {delta:+.3f} "
                f"| {pval_str} "
                f"| {syn_str} |"
            )
    else:
        a("_No pairs with sufficient data._")
    a("")

    # ---------------------------------------------------------------------- #
    # §4 Validation VERDICT + caveats                                          #
    # ---------------------------------------------------------------------- #
    a("## 4. Validation")
    a("")
    # Accept either "VERDICT" (contract) or "verdict" (module's actual key)
    verdict = verdict_dict.get("VERDICT") or verdict_dict.get("verdict", "UNKNOWN")
    a(f"**VERDICT: {verdict}**")
    a("")

    # Print scalar fields as bullet list; skip the verdict key itself
    verdict_keys = {"VERDICT", "verdict"}
    for k, v in verdict_dict.items():
        if k in verdict_keys:
            continue
        # Only emit scalar / short values inline; skip large nested dicts
        if isinstance(v, (str, int, float, bool)):
            a(f"- **{k}**: {v}")
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            a(f"- **{k}**:")
            for item in v:
                a(f"  - {item}")
        else:
            a(f"- **{k}**: _(see raw output)_")
    a("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    *,
    database_url: str,
    persist_labels: bool,
    min_n: int,
) -> str:
    """Execute the full grammar study pipeline.

    Returns the headline VERDICT string.
    """
    # Step 1 — build dataset
    print("[1/6] Building grammar analysis dataset (read-only)...", flush=True)
    session = _make_session(database_url)
    try:
        from rogue.grammar.dataset import build_grammar_analysis_dataset, dataset_summary
        records = build_grammar_analysis_dataset(session)
        summary = dataset_summary(records)
    finally:
        session.close()

    n_total = summary["n_total"]
    n_data = summary["n_with_breach_data"]
    base_rate = summary["breach_base_rate"]
    print(
        f"    {n_total} primitives loaded, {n_data} with breach data, "
        f"per-primitive base rate {_fmt_pct(base_rate)}",
        flush=True,
    )

    # Step 2 — label
    print("[2/6] Labeling records with heuristic GrammarNode labels...", flush=True)
    from rogue.grammar.labeler import label_records
    labels = label_records(records)
    labeled_count = sum(1 for s in labels.values() if s)
    print(f"    {labeled_count}/{n_total} primitives labeled", flush=True)

    if persist_labels:
        print("    --persist-labels: writing labels to DB...", flush=True)
        from rogue.grammar.labeler import persist_labels as _persist
        session2 = _make_session(database_url)
        try:
            n_written = _persist(session2, labels)
            session2.commit()
            print(f"    {n_written} label rows written/upserted", flush=True)
        finally:
            session2.close()

    # Step 3 — node lift table
    print("[3/6] Computing per-node lift table (per_target unit)...", flush=True)
    from rogue.grammar.stats import node_lift_table
    lifts = node_lift_table(records, labels, unit="per_target", min_n=min_n)
    if lifts:
        top = lifts[0]
        print(
            f"    {len(lifts)} nodes; top: {top.node.value} "
            f"lift_rel={top.lift_rel:.2f}× p={top.p_value:.4f}",
            flush=True,
        )

    # Step 4 — pairwise interactions
    print("[4/6] Computing pairwise interactions...", flush=True)
    try:
        from rogue.grammar.combinations import pairwise_interactions, suppressed_pair_count
        pairs = pairwise_interactions(records, labels, min_cell_n=min_n)
        suppressed = suppressed_pair_count(records, labels, min_cell_n=min_n)
        print(f"    {len(pairs)} pairs; {suppressed} suppressed", flush=True)
    except ImportError as exc:
        print(f"    [SKIP] combinations module not yet available: {exc}", flush=True)
        pairs = []
        suppressed = -1

    # Step 5 — controlled validation
    print("[5/6] Running controlled validation pass...", flush=True)
    try:
        from rogue.grammar.validation import controlled_analysis
        verdict_dict = controlled_analysis(records, labels)
    except ImportError as exc:
        print(f"    [SKIP] validation module not yet available: {exc}", flush=True)
        verdict_dict = {
            "VERDICT": "PENDING",
            "note": "validation module (Engineer 6) has not yet landed",
        }

    verdict = verdict_dict.get("VERDICT") or verdict_dict.get("verdict", "UNKNOWN")

    # Step 6 — write report
    print("[6/6] Writing REPORT.md...", flush=True)
    out_dir = Path(__file__).parents[2] / "data" / "grammar_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "REPORT.md"
    generated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    report_md = _build_report(
        summary=summary,
        labels=labels,
        lifts=lifts,
        pairs=pairs,
        suppressed=suppressed,
        verdict_dict=verdict_dict,
        min_n=min_n,
        generated_at=generated_at,
    )
    report_path.write_text(report_md, encoding="utf-8")
    print(f"    Report written to {report_path}", flush=True)

    # Headline print
    print("", flush=True)
    print(f"VERDICT: {verdict}", flush=True)
    print(
        f"Base rate (per-primitive ANY-breach): {_fmt_pct(base_rate)}  "
        f"[analysis unit = per-(primitive × target)]",
        flush=True,
    )

    return verdict


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "SQLAlchemy database URL (overrides DATABASE_URL env var). "
            "Default: postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
        ),
    )
    parser.add_argument(
        "--persist-labels",
        action="store_true",
        default=False,
        help="Write heuristic labels to the DB (PrimitiveGrammarLabel table). "
             "Default: OFF (read-only).",
    )
    parser.add_argument(
        "--min-n",
        type=int,
        default=5,
        help="Minimum node-present unit count below which a node is flagged "
             "as under-powered (default: 5).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    url = _db_url(args.database_url)
    try:
        verdict = run(
            database_url=url,
            persist_labels=args.persist_labels,
            min_n=args.min_n,
        )
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(0)
