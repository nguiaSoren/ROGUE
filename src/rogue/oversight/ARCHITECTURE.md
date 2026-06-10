# `src/rogue/oversight/` — Surface 2: the human gate as an instrument

*ROGUE v2 · build 07 · Surface 2 · maps to ADR-0011 (the independence invariant), `ROGUE_unified_spec.md` §1 (the instrument), §2.5 (the signed record). NET-NEW package, sibling to `reproduce/` and `platform/`.*

## The surface-as-instrument map

Surface 2 is the *same instrument as Surface 1, pointed at a human instead of a model*: fire inputs at a decider, capture the decision, score it against an independent standard, emit a signed record. The mapping onto the shared instrument spine (`src/rogue/instrument/`):

- **Target** = the **human gate** — the reviewer who signs off on an escalated risky action. (A `HumanDecider`, not a `core.TargetAdapter`: a human is sync-capture behind a `ReviewSession`, distinct from the provider-SDK async path; ADR-0004's "no provider types above adapters/" does not apply to a human — the adapter philosophy is "a reviewer is just another decider behind an interface.")
- **Probe** = a `GatedCase` — one escalated case presented as **structured checkable facts** (amount, parties, dispute type, what was flagged), never prose engineered to persuade.
- **Decider** = `HumanDecider` — yields `{APPROVE | DENY}` + optional deliberation notes + decision latency for a presented case, persisted as a `GatedDecision`.
- **Consummation / breach** = **false-approve** — the reviewer consummated a wrong approval. Engagement ≠ breach: deliberating, asking questions, taking time is NOT a breach; only the decision-vs-key comparison counts. False-approve is the named headline FP mode.
- **Ground truth** = the **independent designed-label key** — `GatedCase.designed_label`, a `GroundTruthRef` on the spine, provably independent of the regulation, the reviewers' votes, and the verifier's own opinion (ADR-0011). Scored, never the other way around.

## Modules

- **`case_corpus.py`** *(built)* — the `GatedCase` / `GatedDecision` models + corpus loader (`load_corpus`, `corpus_stats`). The independence invariant's code home: `label_provenance` is required with no `verifier` member; `from_dict` loud-rejects unknown `case_class` / `designed_label` / `label_provenance`. The frozen field set every other module imports.
- **`independence_lint.py`** *(built)* — the enforcement teeth of ADR-0011: a static CI check that fails the build if a case's label could trace to regulation text, the verifier's own model family, or an unbalanced split. A deliberately-seeded bad case is caught by a test.
- **`decider.py`** *(built)* — the `HumanDecider` abstraction + `ReviewSession` record-and-resume, backed by the platform queue, attributing each decision to a real reviewer principal.
- **`disposition_judge.py`** *(built)* — a thin wrapper, NOT a new judge: instantiates area-02's consummation template for the gate (breach = false-approve; engagement ≠ breach) and classifies the FP/FN mode. The human's decision is compared to the key directly — no LLM grades the human's reasoning.
- **`scorer.py`** *(built)* — aggregates `GatedDecision`s against the corpus key → false-approve rate + false-deny rate, each with a bootstrap CI.
- **`attestation.py`** *(built)* — an adapter into area-03, NOT a new attestation impl: maps each `GatedDecision` to an `AttestationEntry` (tamper-evident, complete, decision-rationale captured including dissent, replayable, queryable).
- **`cockpit.py`** *(optional, §4)* — the decision-support strip: the case's calibrated confidence + measured class context + the checkable facts. Structured evidence to *check*, never prose to *persuade* (a `no_persuasive_prose` guard enforces it).

## What it reuses, never forks

The new work is only the independent answer key (`case_corpus` + `independence_lint`) and the human-pointed harness. Everything cross-surface is imported:

- **Area 02 (calibration apparatus)** — the consummation template, the bootstrap CI (`src/rogue/diff/bootstrap.py`), and the `CalibrationReport` shape (`reproduce/judge_calibration.py`); the false-approve rate is structurally `false_positive_breach_rate` conditioned on a human-DENY truth.
- **Area 03 (attestation layer)** — the per-org append-only hash chain + `AttestationEntry`; Surface 2 emits into it.
- **The platform** (`src/rogue/platform/`) — the `SELECT … FOR UPDATE SKIP LOCKED` queue to hand un-decided cases to reviewers, `tenancy.Principal` / `org_id` isolation to attribute and scope a decision, and the `report_service` rendering spine.

**The one line:** the corpus + the independence lint are the product; the human-pointed scorer is mostly reuse; everything else is downstream of getting one number — the false-approve rate — honestly, against a key that is provably independent of the regulation, the votes, and the verifier.
