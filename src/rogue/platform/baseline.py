"""Baseline-regression gate — the continuous-measurement thesis as a PR-blocking artifact.

ROGUE's whole pitch is *continuous* measurement: a model or system-prompt update that silently
re-opens a previously-closed bypass is exactly the failure a one-shot scan can't catch. This module
gives the gate a memory of a prior run:

* ``snapshot(report)`` freezes the per-(config, family) breach state of a scan into a small JSON
  baseline (commit it on ``main``).
* ``compare(baseline, current)`` diffs a fresh scan against that baseline and flags **regressions** —
  a family that was 0-breach in the baseline (a *closed* bypass) now breaching (``reopened``), or a
  family whose breach rate rose by more than the allowed tolerance (``worsened``). A regression fails
  the gate (nonzero exit), so the model update that re-opened the hole blocks the merge.

Per-family rates are aggregated through the same `scoring.aggregate_by_family` primitive the graded
scorecard uses, so the baseline can never disagree with the scorecard about a family's rate.

CLI (``python -m rogue.platform.baseline``), driven by scan-report JSON so it runs $0/offline:

    baseline save    --from-report scan.json --out baseline.json
    baseline compare --report current.json --baseline baseline.json [--max-regression 0.05]
        exit 0 = clean · exit 1 = regression(s) · exit 2 = operational error

The composite GitHub Action wires the *compare* step through ``scripts/ci/rogue_gate.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from rogue.platform.scoring import aggregate_by_family

if TYPE_CHECKING:
    from rogue.report import ScanReport

# Snapshot schema version — bumped if the on-disk shape changes so an old baseline is detected.
BASELINE_VERSION = 1


# --------------------------------------------------------------------------- #
# Snapshot — freeze a scan's per-family breach state.
# --------------------------------------------------------------------------- #


def _family_states(items: list[tuple[str, int, int]]) -> dict[str, dict]:
    """``[(family, n_breach, n_trials)]`` → ``{slug: {label,n_breach,n_trials,breach_rate,breached}}``.

    Aggregation goes through `scoring.aggregate_by_family` so a family's rate matches the scorecard's
    exactly. The human label is stored so a comparison renders without re-importing the report layer.
    """
    from rogue.report import technique_label  # noqa: PLC0415 — avoid an SDK import cycle at module load

    agg = aggregate_by_family(items)
    states: dict[str, dict] = {}
    for slug, (n_breach, n_trials) in agg.items():
        rate = n_breach / n_trials if n_trials else 0.0
        states[slug] = {
            "label": technique_label(slug),
            "n_breach": n_breach,
            "n_trials": n_trials,
            "breach_rate": round(rate, 4),
            "breached": n_breach > 0,
        }
    return states


def _items_from_payload(payload: dict) -> list[tuple[str, int, int]]:
    """Pull ``(family, n_breach, n_trials)`` triples from a report payload dict.

    Accepts either a raw ``ScanReport.to_dict()`` or a platform ``build_json()`` payload — both carry
    ``findings`` with ``family`` / ``n_breach`` / ``n_trials``.
    """
    items: list[tuple[str, int, int]] = []
    for f in payload.get("findings", []) or []:
        items.append((str(f["family"]), int(f.get("n_breach", 0)), int(f.get("n_trials", 0))))
    return items


def snapshot(report: "ScanReport | dict") -> dict:
    """Freeze a scan (a `ScanReport` object OR its report-payload dict) into a baseline snapshot."""
    from rogue.report import ScanReport as _ScanReport  # noqa: PLC0415

    if isinstance(report, _ScanReport):
        items = [(f.family, f.n_breach, f.n_trials) for f in report.findings]
        target = report.target
        n_tests = report.n_tests
        n_breaches = report.n_breaches
        breach_rate = report.breach_rate
    else:
        items = _items_from_payload(report)
        target = str(report.get("target", ""))
        n_tests = int(report.get("n_tests", 0))
        n_breaches = int(report.get("n_breaches", 0))
        breach_rate = float(report.get("breach_rate", (n_breaches / n_tests) if n_tests else 0.0))

    return {
        "baseline_version": BASELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "n_tests": n_tests,
        "n_breaches": n_breaches,
        "breach_rate": round(breach_rate, 4),
        "families": _family_states(items),
    }


def save(report: "ScanReport | dict", path: str | Path) -> dict:
    """Snapshot ``report`` and write it to ``path`` (pretty JSON). Returns the snapshot."""
    snap = snapshot(report)
    Path(path).write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return snap


def load(path: str | Path) -> dict:
    """Load a baseline snapshot JSON from ``path``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Compare — diff a fresh scan against a baseline; flag regressions.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Regression:
    """One family whose breach state got worse against the baseline, beyond tolerance."""

    family: str
    label: str
    baseline_rate: float
    current_rate: float
    delta: float
    kind: str  # "reopened" (baseline 0-breach) | "worsened" (baseline already breaching)

    def describe(self) -> str:
        pct = lambda r: f"{round(r * 100)}%"  # noqa: E731
        if self.kind == "reopened":
            return f"{self.label}: closed bypass RE-OPENED — {pct(self.current_rate)} (was 0%)"
        return (
            f"{self.label}: breach rate WORSENED {pct(self.baseline_rate)} → "
            f"{pct(self.current_rate)} (+{pct(self.delta)})"
        )


@dataclass(frozen=True)
class BaselineComparison:
    """The diff between a baseline snapshot and a current scan."""

    max_regression: float
    target_baseline: str
    target_current: str
    regressions: list[Regression] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)  # families that got strictly better
    new_families: list[str] = field(default_factory=list)  # probed now, absent from the baseline

    @property
    def failed(self) -> bool:
        """True iff any regression was flagged — the gate exits nonzero on this."""
        return bool(self.regressions)

    @property
    def target_mismatch(self) -> bool:
        """True when the baseline and current scans name different targets (a soft warning)."""
        return bool(self.target_baseline) and bool(self.target_current) and (
            self.target_baseline != self.target_current
        )

    def reasons(self) -> list[str]:
        """One human line per regression — folded into the gate's failure reasons."""
        return [r.describe() for r in self.regressions]

    def to_dict(self) -> dict:
        return {
            "failed": self.failed,
            "max_regression": self.max_regression,
            "target_baseline": self.target_baseline,
            "target_current": self.target_current,
            "target_mismatch": self.target_mismatch,
            "regressions": [
                {
                    "family": r.family,
                    "label": r.label,
                    "kind": r.kind,
                    "baseline_rate": r.baseline_rate,
                    "current_rate": r.current_rate,
                    "delta": round(r.delta, 4),
                }
                for r in self.regressions
            ],
            "improvements": self.improvements,
            "new_families": self.new_families,
        }


def compare_snapshots(
    baseline: dict, current: dict, *, max_regression: float = 0.0
) -> BaselineComparison:
    """Diff two baseline snapshots. A family regresses when it *re-opens* (baseline 0-breach, now
    breaching beyond ``max_regression``) or *worsens* (baseline already breaching, rate up by more
    than ``max_regression``). ``max_regression`` is an absolute breach-rate delta in [0,1]."""
    base_fams: dict[str, dict] = baseline.get("families", {}) or {}
    cur_fams: dict[str, dict] = current.get("families", {}) or {}

    regressions: list[Regression] = []
    improvements: list[str] = []
    new_families: list[str] = []

    for slug, cur in cur_fams.items():
        cur_rate = float(cur.get("breach_rate", 0.0))
        label = str(cur.get("label", slug))
        base = base_fams.get(slug)
        if base is None:
            new_families.append(slug)
            continue
        base_rate = float(base.get("breach_rate", 0.0))
        delta = cur_rate - base_rate

        if base_rate == 0.0 and cur_rate > max_regression:
            regressions.append(
                Regression(slug, label, base_rate, cur_rate, delta, kind="reopened")
            )
        elif base_rate > 0.0 and delta > max_regression:
            regressions.append(
                Regression(slug, label, base_rate, cur_rate, delta, kind="worsened")
            )
        elif delta < 0:
            improvements.append(slug)

    return BaselineComparison(
        max_regression=max_regression,
        target_baseline=str(baseline.get("target", "")),
        target_current=str(current.get("target", "")),
        regressions=regressions,
        improvements=improvements,
        new_families=new_families,
    )


def compare(
    baseline: dict, current: "ScanReport | dict", *, max_regression: float = 0.0
) -> BaselineComparison:
    """Diff a fresh scan (`ScanReport` or report payload) against a baseline snapshot."""
    return compare_snapshots(baseline, snapshot(current), max_regression=max_regression)


# --------------------------------------------------------------------------- #
# CLI — `python -m rogue.platform.baseline save|compare` (driven by report JSON, $0/offline).
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rogue-baseline",
        description="Snapshot a scan's per-family breach state, or fail on a regression vs a baseline.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    save_p = sub.add_parser("save", help="Snapshot a scan-report JSON into a baseline file.")
    save_p.add_argument("--from-report", required=True, help="Path to a scan-report JSON (ScanReport.to_dict / build_json).")
    save_p.add_argument("--out", required=True, help="Path to write the baseline snapshot JSON.")

    cmp_p = sub.add_parser("compare", help="Fail (exit 1) if the current scan regressed vs a baseline.")
    cmp_p.add_argument("--report", required=True, help="Path to the CURRENT scan-report JSON.")
    cmp_p.add_argument("--baseline", required=True, help="Path to the baseline snapshot JSON.")
    cmp_p.add_argument(
        "--max-regression",
        type=float,
        default=0.0,
        help="Allowed breach-rate increase per family before it counts as a regression (0-1, default 0.0).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "save":
        try:
            payload = json.loads(Path(args.from_report).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[baseline] could not read --from-report: {exc}", file=sys.stderr)
            return 2
        snap = save(payload, args.out)
        print(
            f"[baseline] saved snapshot of {snap['target'] or '(unknown target)'}: "
            f"{len(snap['families'])} families, {snap['n_breaches']}/{snap['n_tests']} breached → {args.out}"
        )
        return 0

    # compare
    if not 0.0 <= args.max_regression <= 1.0:
        print("[baseline] --max-regression must be between 0 and 1.", file=sys.stderr)
        return 2
    try:
        baseline = load(args.baseline)
        current = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[baseline] could not read inputs: {exc}", file=sys.stderr)
        return 2

    comparison = compare(baseline, current, max_regression=args.max_regression)
    if comparison.target_mismatch:
        print(
            f"[baseline] WARNING: comparing across targets "
            f"({comparison.target_baseline!r} → {comparison.target_current!r}).",
            file=sys.stderr,
        )
    if comparison.failed:
        print(f"[baseline] REGRESSION — {len(comparison.regressions)} family/families got worse:")
        for reason in comparison.reasons():
            print(f"  - {reason}")
        return 1
    print(
        f"[baseline] OK — no regression vs baseline "
        f"(tolerance {round(args.max_regression * 100)}%, "
        f"{len(comparison.new_families)} newly-probed, {len(comparison.improvements)} improved)."
    )
    return 0


__all__ = [
    "BASELINE_VERSION",
    "BaselineComparison",
    "Regression",
    "compare",
    "compare_snapshots",
    "load",
    "main",
    "save",
    "snapshot",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
