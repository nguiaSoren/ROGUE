"""LIVE remediation run (build-05 optional live verification) — find→fix→prove on a REAL model.

Takes a known-breaching (rule, config), measures the pre-mitigation breach rate live, runs the
`RemediationLoop` (real LLM generation + real target + the calibrated per-rule judge), and reports
the post-mitigation breach rate + the generated patch.

HONEST SCOPE (spec §9 RISK #1): the breach reduction is scored by the CALIBRATED per-rule judge
(trustworthy). The over-block number is the calibration-gated piece — it is REPORTED but NOT used
as an accept gate here (`over_block_eps=1.0`); acceptance = the breach rate dropped. The over-block
figure is preliminary until its FP-mode is calibrated.

PAID. `--dry-run` is free (fakes, verifies wiring). `--yes` confirms the live run.

    uv run python scripts/governance/remediate_once.py --dry-run
    uv run python scripts/governance/remediate_once.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rogue.governance import build_attack_pack
from rogue.packs import load_pack
from rogue.remediation import RemediationLoop, RemediationTask, render_remediation_markdown
from rogue.remediation.retest import retest_vs_family
from rogue.schemas import AttackPrimitive, JudgeVerdict, demo_deployment_configs
from rogue.schemas.governance import ClientPolicy

_FIX = Path("tests/fixtures/governance")
_OUT = Path("data/governance")


def _rule(rule_id: str):
    pol = ClientPolicy.model_validate_json((_FIX / "sample_policy.json").read_text())
    return next(r for r in pol.rules if r.rule_id == rule_id)


def _corpus() -> list[AttackPrimitive]:
    seen: set[str] = set()
    out: list[AttackPrimitive] = []
    for name in ("aggressive", "default", "compliance"):
        for p in load_pack(name):
            if p.primitive_id not in seen:
                seen.add(p.primitive_id)
                out.append(p)
    return out


# ---- fakes for --dry-run (mirror tests/test_remediation_loop.py) ----
class _V:
    def __init__(self, v):
        self.verdict, self.rationale, self.confidence = v, "fake", 1.0


class _DryJudge:
    """Attacks resist (post-patch breach 0); legit engage (no false-block) — shows a clean accept."""

    def __init__(self, attack_ids):
        self._a = set(attack_ids)

    async def judge(self, rendered, model_response, primitive, context=None):
        return _V(JudgeVerdict.REFUSED if primitive.primitive_id in self._a else JudgeVerdict.FULL_BREACH)


class _DryResp:
    def __init__(self):
        self.content, self.cost_usd = "ok", 0.0


class _DryPanel:
    async def run_attack(self, rendered, config, temperature: float = 0.7, n_trials: int = 5):
        return [_DryResp() for _ in range(n_trials)]


async def _amain(args) -> None:
    rule = _rule(args.rule)
    config = next(c for c in demo_deployment_configs() if c.config_id == args.config_id)
    pack = build_attack_pack(rule, _corpus())
    transcripts = list(rule.forbidden_examples) or [rule.consummation_definition]
    print(f"rule={rule.rule_id} [{rule.breach_type.value}] · target={config.config_id} "
          f"({config.target_model}) · pack={len(pack.primitives)} primitives · n_trials={args.n_trials}")

    if args.dry_run:
        loop = RemediationLoop(
            panel=_DryPanel(), judge=_DryJudge([p.primitive_id for p in pack.primitives]),
            complete=lambda prompt: "MITIGATION: the agent must refuse this action.",
            n_trials=args.n_trials, over_block_eps=1.0)
        task = RemediationTask(rule=rule, config=config, primitives=pack.primitives,
                               transcripts=transcripts, pre_breach_rate=1.0)
        result = await loop.run(task)
        print("\n[DRY-RUN — no API calls]\n" + render_remediation_markdown(result))
        return

    # LIVE
    from rogue.reproduce.target_panel import TargetPanel

    panel = TargetPanel.from_env()
    loop = RemediationLoop(panel=panel, n_trials=args.n_trials, over_block_eps=1.0)
    judge = loop._judge_for(rule)  # the calibrated per-rule judge (live)

    print("measuring pre-mitigation breach rate (live, unpatched config)…")
    pre_rate, pre_ci = await retest_vs_family(config, pack.primitives, judge=judge, panel=panel,
                                              n_trials=args.n_trials)
    print(f"  pre-mitigation breach rate = {pre_rate:.3f}  CI{pre_ci}")

    task = RemediationTask(rule=rule, config=config, primitives=pack.primitives,
                           transcripts=transcripts, pre_breach_rate=pre_rate)
    print("running the remediation loop (generate → apply → re-test, live)…")
    result = await loop.run(task)

    print("\n" + render_remediation_markdown(result))
    ob = result.over_block
    print(f"\n--- accepted={result.accepted} · type={result.candidate.mitigation_type.value} · "
          f"verified_by={result.verified_by} · iterations={result.iterations} ---")
    print(f"--- breach {pre_rate:.3f} → {result.post_breach_rate:.3f} (calibrated judge) ---")
    if ob is not None:
        print(f"--- over-block (⚠ uncalibrated, NOT gating — RISK #1): {ob.over_block_rate:.3f} "
              f"on {ob.n_legit} legit requests ---")
    _OUT.mkdir(parents=True, exist_ok=True)
    dest = _OUT / f"remediation_{rule.rule_id}_{config.config_id}.json"
    dest.write_text(result.model_dump_json(indent=2))
    print(f"--- result → {dest} ---")


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default="R3")  # R3 = no-legal-opinions (unauthorized_action), breached on Llama
    ap.add_argument("--config-id", default="acme-llama3")
    ap.add_argument("--n-trials", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.yes:
        print("PAID live remediation run. Re-run with --yes (or --dry-run for a free check).")
        return
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
