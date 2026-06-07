"""CLI: heuristic grammar-node labeling over the existing AttackPrimitive corpus.

DEFAULT (no flags) = DRY RUN — reads the live DB, labels every canonical
non-synthesized primitive, prints the node-distribution table and a coverage
summary.  No writes of any kind.

Usage
-----
  # Dry run — distribution table only (safe, $0)
  uv run python scripts/benchmark/grammar_labels.py

  # Persist heuristic labels to DB (writes primitive_grammar_labels rows)
  uv run python scripts/benchmark/grammar_labels.py --persist

  # Interactive manual-override for one primitive (writes source="manual" rows)
  uv run python scripts/benchmark/grammar_labels.py --review <PRIMITIVE_ID>

  # Show help
  uv run python scripts/benchmark/grammar_labels.py --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sure the repo root is on sys.path when running as a script.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grammar_labels",
        description=(
            "Heuristic grammar-node labeler for ROGUE's AttackPrimitive corpus.\n"
            "Default: dry run — print distribution table, no writes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--persist",
        action="store_true",
        default=False,
        help="Write heuristic labels to DB (primitive_grammar_labels table).  WRITES.",
    )
    p.add_argument(
        "--review",
        metavar="PRIMITIVE_ID",
        default=None,
        help=(
            "Enter an interactive stdin loop to manually override labels for "
            "the given primitive.  Writes source='manual' rows.  WRITES."
        ),
    )
    return p


def _print_distribution(
    distribution: "dict",
    labels: "dict",
    records: "list",
) -> None:
    """Print the node-distribution table to stdout."""
    total = len(records)
    zero_node = sum(1 for node_set in labels.values() if not node_set)

    print()
    print("=" * 60)
    print("  GRAMMAR NODE DISTRIBUTION")
    print(f"  Corpus: {total} primitives  |  0-node: {zero_node}")
    print("=" * 60)
    print(f"  {'Node':<35} {'Count':>6}  {'Coverage':>8}")
    print("-" * 60)

    # Sort by count descending, then name ascending for ties.
    sorted_items = sorted(distribution.items(), key=lambda kv: (-kv[1], kv[0].value))
    for node, count in sorted_items:
        pct = (count / total * 100) if total else 0.0
        print(f"  {node.value:<35} {count:>6}  {pct:>7.1f}%")

    print("-" * 60)
    total_assignments = sum(distribution.values())
    avg = total_assignments / total if total else 0.0
    print(f"  {'Total label assignments':<35} {total_assignments:>6}")
    print(f"  {'Avg nodes per primitive':<35} {avg:>7.2f}")
    print("=" * 60)
    print()


def _run_dry(session: "object") -> tuple["list", "dict", "dict"]:
    """Build dataset + labels; return (records, labels_dict, distribution)."""
    from rogue.grammar.dataset import build_grammar_analysis_dataset
    from rogue.grammar.labeler import label_distribution, label_records

    print("Building grammar analysis dataset…", end=" ", flush=True)
    records = build_grammar_analysis_dataset(session)  # type: ignore[arg-type]
    print(f"{len(records)} primitives loaded.")

    print("Applying heuristic labels…", end=" ", flush=True)
    labels = label_records(records)
    print("done.")

    distribution = label_distribution(labels)
    return records, labels, distribution


def _run_persist(session: "object", labels: "dict") -> None:
    """Persist labels to DB inside a transaction."""
    from rogue.grammar.labeler import persist_labels

    print("Persisting heuristic labels to DB…", end=" ", flush=True)
    rows = persist_labels(session, labels, source="heuristic")  # type: ignore[arg-type]
    session.commit()  # type: ignore[union-attr]
    print(f"{rows} rows written.")


def _run_review(session: "object", primitive_id: str) -> None:
    """Interactive stdin override loop for one primitive."""
    from rogue.grammar.dataset import build_grammar_analysis_dataset
    from rogue.grammar.labeler import heuristic_labels, persist_labels
    from rogue.schemas import GrammarNode

    # Find the requested primitive.
    records = build_grammar_analysis_dataset(session)  # type: ignore[arg-type]
    record = next((r for r in records if r.primitive_id == primitive_id), None)
    if record is None:
        print(f"ERROR: primitive '{primitive_id}' not found in dataset.", file=sys.stderr)
        sys.exit(1)

    auto_nodes = heuristic_labels(record)
    current_nodes: set[GrammarNode] = set(auto_nodes)

    all_node_values = [n.value for n in GrammarNode]

    print()
    print(f"Primitive: {primitive_id}")
    print(f"Family:    {record.family}")
    if record.secondary_families:
        print(f"Secondary: {', '.join(record.secondary_families)}")
    print(f"Slots:     {', '.join(record.payload_slots.keys()) or '(none)'}")
    print(f"Multi-turn: {record.requires_multi_turn}")
    print()
    print("Heuristic nodes assigned:")
    for n in sorted(current_nodes, key=lambda x: x.value):
        print(f"  + {n.value}")
    if not current_nodes:
        print("  (none)")
    print()
    print("Commands:  +<node>  add a node  |  -<node>  remove a node  |  done  save  |  quit  exit without saving")
    print()

    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted — no changes written.")
            return

        if not raw:
            continue

        if raw.lower() in ("done", "save"):
            break

        if raw.lower() in ("quit", "exit", "q"):
            print("Exiting without saving.")
            return

        if raw.lower() == "list":
            print("Available nodes:")
            for v in sorted(all_node_values):
                marker = "+" if GrammarNode(v) in current_nodes else " "
                print(f"  [{marker}] {v}")
            continue

        if raw.startswith("+") or raw.startswith("-"):
            op = raw[0]
            node_str = raw[1:].strip().lower()
            if node_str not in all_node_values:
                # Try to match by partial name
                matches = [v for v in all_node_values if v.startswith(node_str)]
                if len(matches) == 1:
                    node_str = matches[0]
                elif len(matches) > 1:
                    print(f"  Ambiguous: {', '.join(matches)}")
                    continue
                else:
                    print(f"  Unknown node '{node_str}'.  Type 'list' to see all nodes.")
                    continue
            node = GrammarNode(node_str)
            if op == "+":
                current_nodes.add(node)
                print(f"  Added {node_str}")
            else:
                current_nodes.discard(node)
                print(f"  Removed {node_str}")
        else:
            print("  Unknown command.  Use +<node>, -<node>, list, done, or quit.")

    # Persist current_nodes as source="manual"
    if not current_nodes:
        print("No nodes selected — nothing to persist.")
        return

    rows = persist_labels(  # type: ignore[arg-type]
        session,
        {primitive_id: current_nodes},
        source="manual",
    )
    session.commit()  # type: ignore[union-attr]
    print(f"Saved {rows} manual label(s) for {primitive_id}.")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Import DB machinery.
    try:
        from rogue.db.session import get_session  # type: ignore[import]
    except Exception as exc:
        print(f"ERROR: could not import DB session: {exc}", file=sys.stderr)
        print("Is the DB running?  Try: docker compose up -d --wait", file=sys.stderr)
        sys.exit(1)

    with get_session() as session:
        records, labels, distribution = _run_dry(session)
        _print_distribution(distribution, labels, records)

        if args.persist:
            _run_persist(session, labels)
        elif args.review:
            _run_review(session, args.review)
        else:
            print("(Dry run — no writes.  Pass --persist to write labels, or --review <ID> for manual override.)")


if __name__ == "__main__":
    main()
