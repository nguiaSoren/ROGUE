"""Small LIVE run of Surface-1 OFFENSE on sample_policy (build-04 §6 live demonstration).

PAID: dispatches real target + judge model calls. Run deliberately (CLAUDE.md costly-scripts
rule). ``--dry-run`` is free (stub responder/grader — verifies the orchestration wiring);
``--yes`` confirms the paid live run.

    uv run python scripts/governance/run_sample_policy.py --dry-run   # free wiring check
    uv run python scripts/governance/run_sample_policy.py --yes       # paid live run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rogue.governance import (
    attestation_rows,
    default_grade,
    live_responder,
    render_markdown,
    run_policy_scan,
)
from rogue.schemas import AttackPrimitive, demo_deployment_configs
from rogue.schemas.governance import ClientPolicy

_FIX = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "governance"


def _policy() -> ClientPolicy:
    return ClientPolicy.model_validate_json((_FIX / "sample_policy.json").read_text())


def _corpus() -> list[AttackPrimitive]:
    raw = json.loads((_FIX / "mini_corpus.json").read_text())
    rows = raw["primitives"] if isinstance(raw, dict) and "primitives" in raw else raw
    return [AttackPrimitive.model_validate(r) for r in rows]


def _pick_config(config_id: str | None):
    cs = demo_deployment_configs()
    if config_id:
        return next(c for c in cs if c.config_id == config_id)
    for c in cs:  # prefer a Haiku target — cheap + same provider key as the judge
        if "haiku" in c.target_model.lower():
            return c
    return cs[0]


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()  # adapters read provider keys from the env at call time

    ap = argparse.ArgumentParser()
    ap.add_argument("--config-id", default=None)
    ap.add_argument("--n-trials", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="free: stub respond/grade, verify wiring")
    ap.add_argument("--yes", action="store_true", help="confirm the PAID live run")
    args = ap.parse_args()

    policy, corpus, config = _policy(), _corpus(), _pick_config(args.config_id)
    print(
        f"policy={policy.policy_id} ({len(policy.rules)} rules) · "
        f"target={config.config_id} ({config.target_model}) · "
        f"corpus={len(corpus)} primitives · n_trials={args.n_trials}"
    )

    if args.dry_run:
        report = run_policy_scan(
            policy, config, corpus,
            respond=lambda prim, cfg: "I can't help with that.",
            grade=lambda rule, judge, prim, resp, cfg: False,
            n_trials=args.n_trials,
        )
        print("\n[DRY-RUN — no API calls]\n")
        print(render_markdown(report))
        print(f"\n[wiring OK · {len(attestation_rows(report))} attestation rows would emit]")
        return

    if not args.yes:
        print("\nPAID live run (real target + judge calls). Re-run with --yes to confirm.")
        return

    respond, stats = live_responder()
    report = run_policy_scan(
        policy, config, corpus, respond=respond, grade=default_grade, n_trials=args.n_trials
    )
    print("\n" + render_markdown(report))
    print(
        f"\n--- spend: {stats['calls']} target calls, ~${stats['target_cost_usd']:.4f} target "
        f"(judge cost separate) · {stats['empty']} modality-skips ---"
    )
    out = Path("data/governance")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"sample_policy_{config.config_id}.json"
    dest.write_text(report.model_dump_json(indent=2))
    print(f"--- {len(attestation_rows(report))} attestation rows emitted · report → {dest} ---")


if __name__ == "__main__":
    main()
