"""Phase-3 EXIT GATE — the human-gate false-approve measurement orchestrator.

This is the build-07 §3 exit gate itself: load the designed-label corpus → assert
it passes ``independence_lint`` → collect reviewer decisions → score → print the
**false-approve rate with a bootstrap CI** plus the explicit independence-passed
assertion. The defensible headline ("22% false-approve [12%, 31%]") only ships if
it is scored against a key that is *provably independent* of the regulation, the
reviewers' votes, and the verifier's own opinion (ADR-0011, build 07 §1/§3). The
lint is wired in HERE, before any number is computed — if the lint isn't on this
path, the gate is theater (build 07 §3 risk note).

NOT a paid/looped script — it drives human reviewers, with NO LLM panel, NO Bright
Data, NO money spent (build 07 §3). But it consumes *reviewer time*, so it is still
**run-deliberately**: gated behind an explicit invocation, the way the costly
ops scripts are gated behind money (CLAUDE.md costly-scripts discipline, applied to
time rather than dollars). Importing this module opens NO DB and runs nothing; all
work happens inside ``main()`` only when a human invokes it.

Two modes (``--mode``):

  * ``stub`` (default — offline / CI / demo): a deterministic, seeded
    ``StubDecider`` exercises the WHOLE pipeline end-to-end with no humans. It
    produces a realistic, non-trivial false-approve rate by wrongly APPROVING a
    configurable fraction of DENY-truth cases (``--false-approve-frac``) and
    wrongly DENYING a fraction of APPROVE-truth cases (``--false-deny-frac``). The
    coin per case is seeded on ``(seed, case_id)`` so the run is reproducible.
    This is what runs in tests/CI; it spends nothing and needs no DB.
  * ``reviewers`` (the real exit-gate path): assign the corpus to real reviewers
    via ``ReviewSession`` over the org-scoped platform queue, then score their
    decisions. This needs real reviewers + the platform DB; in a CLI run it would
    assign every case and block on each reviewer answering. The path is deliberately
    THIN — it reuses ``ReviewSession`` + ``PostgresSessionStore`` unchanged; the
    stub mode is what the gate's automated coverage exercises.

Run-deliberately invocation::

    # Offline demo of the exit gate (no humans, no money, reproducible):
    uv run python scripts/oversight/run_gate_measurement.py \\
        --mode stub --false-approve-frac 0.2 --false-deny-frac 0.05

    # Against a custom corpus:
    uv run python scripts/oversight/run_gate_measurement.py --corpus path/to/corpus.json

    # The real exit gate (needs reviewers + DATABASE_URL; blocks on each reviewer):
    uv run python scripts/oversight/run_gate_measurement.py \\
        --mode reviewers --org-id org_... --reviewer user_...
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Defensive `src/` insert so the script runs even without the editable install on
# path (mirrors scripts/ops/*.py). No dotenv/DB import at module load — stub mode
# touches no environment and no database; the reviewers path imports DB lazily.
_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from rogue.oversight.case_corpus import GatedCase, load_corpus  # noqa: E402
from rogue.oversight.decider import (  # noqa: E402
    HumanDecider,
    InMemorySessionStore,
    ReviewSession,
    StubDecider,
)
from rogue.oversight.independence_lint import (  # noqa: E402
    assert_corpus_independent,
)
from rogue.oversight.scorer import OversightReport, score  # noqa: E402

DEFAULT_STUB_SEED = 1729
DEFAULT_STUB_REVIEWER = "stub-reviewer"
DEFAULT_ORG_ID = "demo-org"

INDEPENDENCE_PASS_LINE = (
    "✅ answer key passed independence_lint "
    "(regulation-independent, vote-independent, verifier-independent)"
)


def _seeded_coin(seed: int, case_id: str) -> float:
    """A deterministic per-case coin in [0, 1), keyed on ``(seed, case_id)``.

    Hashing the pair (rather than a shared mutable RNG advanced per case) makes each
    case's outcome independent of corpus ordering — so the false-approve rate is
    reproducible no matter how the corpus is sorted or filtered.
    """
    digest = hashlib.sha256(f"{seed}:{case_id}".encode()).digest()
    # Top 8 bytes → a uniform float in [0, 1).
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def make_stub_decider(
    *,
    seed: int,
    false_approve_frac: float,
    false_deny_frac: float,
) -> StubDecider:
    """A deterministic stub reviewer that injects a realistic error mix.

    Policy, per presented case (read off the case's own ``designed_label`` — the
    answer key — so the injected error is exactly the modeled fraction):

      * DENY-truth case: wrongly APPROVE iff its seeded coin < ``false_approve_frac``
        (a false-approve, the headline breach), else correctly DENY.
      * APPROVE-truth case: wrongly DENY iff its seeded coin < ``false_deny_frac``
        (a false-deny), else correctly APPROVE.

    Reusing ``case.designed_label`` here is sound: this is the SIMULATED reviewer
    (it would never see the key in a real run), and conditioning on truth is the only
    way to dial the false-approve / false-deny rates to the requested fractions for a
    deterministic demo. The scorer still compares the emitted decision to the key
    independently.
    """

    def policy(case: GatedCase) -> str:
        coin = _seeded_coin(seed, case.case_id)
        if case.designed_label == "DENY":
            return "APPROVE" if coin < false_approve_frac else "DENY"
        # designed_label == "APPROVE"
        return "DENY" if coin < false_deny_frac else "APPROVE"

    return StubDecider(policy, latency_s=None, notes="stub (deterministic, seeded)")


def collect_stub_decisions(
    cases: list[GatedCase],
    *,
    seed: int,
    false_approve_frac: float,
    false_deny_frac: float,
    org_id: str,
    reviewer: str,
):
    """Drive the FULL harness (queue → assign → decide → record) with the stub.

    Routes through ``ReviewSession`` + ``InMemorySessionStore`` rather than calling
    the decider directly, so the offline path exercises the same assign→decide→record
    state machine the real reviewers path uses — only the decider and the store are
    swapped. No DB, no money, fully deterministic.
    """
    decider: HumanDecider = make_stub_decider(
        seed=seed,
        false_approve_frac=false_approve_frac,
        false_deny_frac=false_deny_frac,
    )
    store = InMemorySessionStore(cases)
    session = ReviewSession(store, decider, org_id=org_id, reviewer=reviewer)
    return session.run_all()


def collect_reviewer_decisions(cases: list[GatedCase], *, org_id: str, reviewer: str):
    """The REAL exit-gate path — assign the corpus to a real reviewer via the queue.

    Thin by design (build 07 §3): it reuses ``ReviewSession`` over the Postgres-backed
    ``PostgresSessionStore`` (the platform ``SELECT … FOR UPDATE SKIP LOCKED`` queue),
    so the only new logic is wiring, not orchestration. In a live CLI run this assigns
    each un-decided case to ``reviewer`` in ``org_id`` and BLOCKS on the reviewer
    answering each one over their session — which is why this script is run-deliberately
    (it consumes reviewer time). DB imports stay lazy here so ``stub`` mode never opens
    a connection.

    This stub of the path raises rather than silently no-op'ing: a real run needs a
    live ``DATABASE_URL``, seeded reviewers/orgs, and a blocking UI session loop that
    is outside this orchestrator's scope. Wire ``PostgresSessionStore(session_factory,
    principal)`` here when those exist.
    """
    raise NotImplementedError(
        "reviewers mode needs a live platform DB (DATABASE_URL), seeded reviewers/org, "
        "and a blocking review-session UI loop. The orchestration is ReviewSession over "
        "PostgresSessionStore (platform SKIP-LOCKED queue) — wire it when those exist. "
        "Use --mode stub for the offline/CI exit-gate demonstration."
    )


def print_report(report: OversightReport) -> None:
    """Print the headline line + the 2×2 confusion breakdown."""
    print()
    print("false-approve / false-deny (scored against the independent key):")
    print(f"  {report.summary_line()}")
    print()
    c = report.confusion
    print("confusion (decision vs designed_label):")
    print(f"  true_approve : {c['true_approve']:>4}")
    print(f"  false_approve: {c['false_approve']:>4}   <- headline breach mode")
    print(f"  true_deny    : {c['true_deny']:>4}")
    print(f"  false_deny   : {c['false_deny']:>4}")
    print(f"  decisions    : {report.n_decisions:>4}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase-3 exit gate: a CI-bearing human false-approve rate scored against a "
            "provably-independent key (ADR-0011, build 07 §3). No money, no LLM, no "
            "Bright Data; run-deliberately (it consumes reviewer time)."
        )
    )
    parser.add_argument(
        "--corpus",
        default=None,
        help="Path to the designed-label corpus JSON (default: the bundled fixture).",
    )
    parser.add_argument(
        "--mode",
        choices=("stub", "reviewers"),
        default="stub",
        help="stub = offline/CI/demo (deterministic, no humans); reviewers = real path.",
    )
    parser.add_argument(
        "--false-approve-frac",
        type=float,
        default=0.2,
        help="[stub] fraction of DENY-truth cases the stub wrongly APPROVES (default 0.2).",
    )
    parser.add_argument(
        "--false-deny-frac",
        type=float,
        default=0.05,
        help="[stub] fraction of APPROVE-truth cases the stub wrongly DENIES (default 0.05).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_STUB_SEED,
        help=f"[stub] per-case coin seed (default {DEFAULT_STUB_SEED}); makes the run reproducible.",
    )
    parser.add_argument(
        "--org-id",
        default=DEFAULT_ORG_ID,
        help="Org the review session is scoped to (tenancy attribution).",
    )
    parser.add_argument(
        "--reviewer",
        default=DEFAULT_STUB_REVIEWER,
        help="Reviewer principal id the decisions are attributed to.",
    )
    args = parser.parse_args(argv)

    if args.mode == "stub":
        for name, frac in (
            ("--false-approve-frac", args.false_approve_frac),
            ("--false-deny-frac", args.false_deny_frac),
        ):
            if not (0.0 <= frac <= 1.0):
                parser.error(f"{name} must be in [0, 1], got {frac}")

    # 1) Load the corpus.
    cases = load_corpus(args.corpus)
    from rogue.oversight.case_corpus import corpus_stats

    print(f"corpus: {len(cases)} case(s) loaded from "
          f"{args.corpus or '<bundled fixture>'}")
    print(f"corpus_stats: {corpus_stats(cases)}")

    # 2) Assert independence — the WHOLE product. A number scored against a
    #    non-independent key must NOT ship (build 07 §3); abort loudly if it fails.
    try:
        assert_corpus_independent(cases)
    except AssertionError as exc:
        print(file=sys.stderr)
        print(
            "❌ ABORT: the answer key FAILED independence_lint — refusing to score a "
            "false-approve number against a non-independent key (ADR-0011, build 07 §3).",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1
    print(INDEPENDENCE_PASS_LINE)

    # 3) Collect decisions.
    if args.mode == "stub":
        print(
            f"mode=stub (deterministic, seed={args.seed}): "
            f"false_approve_frac={args.false_approve_frac}, "
            f"false_deny_frac={args.false_deny_frac} — no humans, no money, no DB."
        )
        decisions = collect_stub_decisions(
            cases,
            seed=args.seed,
            false_approve_frac=args.false_approve_frac,
            false_deny_frac=args.false_deny_frac,
            org_id=args.org_id,
            reviewer=args.reviewer,
        )
    else:
        print(
            f"mode=reviewers (org={args.org_id!r}, reviewer={args.reviewer!r}): "
            "assigning cases over the platform queue and blocking on real reviewers."
        )
        decisions = collect_reviewer_decisions(
            cases, org_id=args.org_id, reviewer=args.reviewer
        )

    print(f"collected {len(decisions)} decision(s).")

    # 4) Score against the independent key.
    report = score(decisions, cases)
    print_report(report)

    # 5) Success.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
