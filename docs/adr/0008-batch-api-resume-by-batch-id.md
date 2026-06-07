# 0008 — Batch-API + resume-by-batch-id for cost-controlled re-grades

- **Status:** Accepted
- **Date:** 2026-06-08 (retroactive; used for the 2026-06-07 matrix re-judge)

## Context

Re-grading the stored breach matrix under a new judge version (ADR-0005) means thousands of judge calls. Run synchronously at the per-request price, a full re-judge is slow and expensive, and any mid-run crash (Neon cold-start, rate limit, transient 5xx) would waste all spend up to that point. ROGUE deliberately treats paid runs as money: costly scripts are run on demand, never on a loop/timer/cron.

## Decision

Cost-controlled re-grades go through the provider **Batch API** (roughly half-price, async) and are **resumable by batch id**: the pipeline submits batches, records their ids, and a resume step (`scripts/resume_rejudge.py`) reconciles completed batches back into the matrix so an interrupted run continues instead of restarting. The 2026-06-07 v3 matrix re-judge used `scripts/rejudge_batch.py --changeable-only` (skip cells whose verdict can't change) + `resume_rejudge.py`; sampling/second-grader passes use `scripts/rejudge_sample_v3.py` → `scripts/second_grader_pass.py`. `--changeable-only` plus the universal skip-cache philosophy means re-grades pay only for cells that can actually move.

## Consequences

- ~2× cheaper re-grades and crash-safe progress (resume by batch id), enabling whole-corpus re-judges that would otherwise be prohibitive.
- Higher latency per batch (async, minutes-to-hours) — acceptable for offline re-grades, not for live scans.
- The pattern generalizes to any large offline judging job (calibration sweeps, benchmark grading).

## What would reverse this

Provider removal of a batch tier, or a live-latency requirement for the same grading path — at which point synchronous + aggressive `--changeable-only` filtering becomes the fallback.
