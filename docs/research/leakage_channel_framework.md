# Observable leakage channels — a provenance-instrumentation framework (P5)

**Elevator pitch.** *ROGUE turns hidden agent-internal channels — tool-call arguments, reasoning traces, persistent memory — into observable, provenance-labeled leakage channels that can be measured with deterministic canaries.* Everything below is an instance of that one idea.

**Contribution (stated once).** We do **not** contribute a new attack. We contribute a **reusable, provenance-based instrumentation framework** that makes leakage on any internal execution channel measurable with deterministic, ground-truth canary tracking — and we demonstrate it generalizes by instantiating three channels on one substrate, cross-session persistent memory being the newest.

**Status:** framework spec + 3 instantiated channels shipped (tool-args, reasoning-traces, persistent-memory); retrieval next. The reuse and the provenance-attribution accuracy are demonstrated at $0 (below); the cross-model *prevalence* finding is the open empirical question (§7) and needs a live run.

## 1. Why output-only auditing is not enough

A leak is not only what a model *says*. A tool-using, memory-bearing agent exposes a value through many observable execution channels, and an audit of the final response is blind to all of them. This is measured, not asserted: AgentLeak (2602.11510) finds **41.7% of traces are "false-clean"** — the output passes every check while an internal channel leaked. Trace-logging tools (LangSmith, Phoenix, and agent observability generally) *see* those channels — they record tool calls and memory ops — but they log **what happened**, not **whether a secret leaked** or **where it came from**. The gap this framework fills is adversarial, ground-truth leakage *measurement* with provenance, not trace visibility (§6).

## 2. The channel abstraction (formal)

> **Definition 1 (Leakage channel).** A leakage channel is a tuple **C = ⟨S, P, J, E⟩** where
> - **S — source:** a function that plants a ground-truth secret `κ` at a known site on the channel (an HMAC-minted, unguessable canary in a tool return / a context window / a memory record). Unguessability gives the key property: `κ` cannot appear downstream unless the model actually read it off the channel, so any match is near-zero-FP.
> - **P — provenance:** a labeling `π(v) → {planted, retrieval, memory, parametric, ambiguous}` attributing an emitted value `v` to its origin along the execution graph (single-hop v1).
> - **J — judge:** a deterministic predicate over the replayable trace that decides leak / no-leak per the channel's egress semantics (temporal + sink-graded), with no LLM in the headline path.
> - **E — evidence:** a bank of what the agent *learned* on the channel, so a non-verbatim exfil (a decoded/paraphrased copy of `κ`) is still caught (non-headline hardening).

> **Algorithm 1 (Instrument a channel).**
> ```
> plant κ via S at a known site                     # ground truth
> run the agent, record the replayable trace T      # execution graph
> for each emitted value v in T:
>     if v derives from κ (verbatim | E-decoded):    # J: near-zero-FP by |κ| unguessability
>         label ← P(v)                               # provenance: where κ entered
>         emit finding(channel=C, provenance=label, egress=sink?(v))
> ```

Adding a channel means supplying **S** (a new plant site) and one new **P** label; **J** and **E** are reused unchanged. That is the framework's claim, and §3 shows it holds by construction, not by assertion.

## 3. Proof of reuse (not an assertion)

The substrate — **S** (`canaries.py`, 94 LOC) · **P** (`pii_provenance.py`, 94) · **J**-core (`trace_judge.py` minus per-channel methods, ~460) · **E** (`evidence_bank.py`, 91) ≈ **740 LOC** — is written once and shared **byte-identical**. Each channel supplies only a plant site, one provenance label, and one judge predicate:

| Channel | S (canary) | P (provenance) | J (judge core) | E (evidence) | channel-specific new code |
|---|:---:|:---:|:---:|:---:|---|
| tool-call args (baseline) | ✅ | ✅ `RETRIEVAL` | ✅ | ✅ | *defines the substrate* |
| reasoning traces | ✅ | ✅ | ✅ | ✅ | `reasoning_leak.py` — **165 LOC** |
| persistent memory | ✅ | ✅ **+`MEMORY`** label | ✅ **+79-LOC** method | ✅ | `memory_channel.py` 224 + judge 79 + tools 70 ≈ **373 LOC** |

That is "reusable framework" made **measurable**: a new internal-leak channel costs one plant site + one provenance label + one judge predicate (≈165–373 LOC) against **~740 LOC of reused, byte-identical substrate** — not a new evaluation pipeline. The memory instance's own share is a `MemoryStore` + tool pair (the new **S**), one `PIIProvenance.MEMORY` label (**P**), and a 79-LOC `judge_memory_exfil` (**J**'s egress predicate), reusing J's substring/temporal/sink logic and E untouched.

## 4. The memorable path (persistent memory as the cross-session instance)

```
        SESSION 1  (benign)                         SESSION 2  (fresh, unrelated)
     ┌──────────────────────┐                    ┌────────────────────────────────┐
     │ user task             │                    │ sensitive-topic trigger         │
     │   └─ save_memory(κ) ──┼──►  MemoryStore ───┼─► recall_memory() ─► κ surfaces │
     └──────────────────────┘   (dormant, N=100  │        │                        │
                                  benign sessions)│        └─► send_email(… κ …)    │
                                                  └──────────────┬─────────────────┘
                                                                 ▼
                                          J: MEMORY_SURFACED (recall) → MEMORY_EXFIL (sink)
                                          P: provenance = MEMORY (cross-session)
```

The one axis that makes memory its own instance, not "retrieval again," is **temporal persistence**: it is the only channel where the plant and the leak happen in *different sessions* and the payload re-enters as *trusted* context. That is the boundary an output-only or single-session instrument cannot cross.

## 5. What each component buys (ablation)

| Remove… | Consequence | Evidence |
|---|---|---|
| the **canary** (use a plain secret) | matches benign text → false positives; no ground truth to attribute | design rationale; unguessable `κ` is the near-zero-FP guarantee (Def 1) |
| the **evidence bank** | a base64/hex/reversed copy of `κ` evades the verbatim match | **measured $0** — the decode tier catches non-verbatim copies the substring scan misses (`evidence_bank` tests) |
| the **deterministic judge** (use an LLM judge) | trace evaluation enters the ~31% false-positive regime | cited (ToolEmu); ROGUE's headline path is deterministic by design |
| **provenance** | you get a leak *count* but not *where from* — cannot separate retrieval vs cross-session memory vs parametric | **measured $0** — 3-way provenance accuracy **1.00** on a 36-item labeled set (`pii_provenance.py`); it is what turns "83 leaks" into "tool-args / reasoning / memory" (§7) |

## 6. Positioning vs observability tools

| | traces tool calls / memory ops | plants ground-truth canaries | provenance attribution | deterministic breach verdict |
|---|:---:|:---:|:---:|:---:|
| observability / tracing (LangSmith, Phoenix, agent loggers) | ✓ | ✕ | ✕ | ✕ |
| **ROGUE leakage channels** | ✓ | ✓ | ✓ | ✓ |

*Honesty note:* observability platforms genuinely capture the traces (that's their job); the differentiator is not visibility but **adversarial leakage measurement** — planting ground truth, attributing provenance, and rendering a deterministic breach verdict. This row is a positioning claim on the *leakage-measurement* axis, to be re-checked against each tool's current features, not a certified feature audit.

## 7. Cost, and the open empirical question

**Cost (measured / bounded, $0 parts).** Off by default → **zero** overhead when disabled (byte-identical). The judge is a deterministic canary match → **no LLM judge call** (unlike a graded scan, this channel adds no per-trial judge cost). The store is `O(records)` in memory (a dict). The only real spend is the target model calls of the live probe itself — which is the paid arm, not framework overhead.

**The finding (the paid run).** The framework is the instrument; the science is what it reads, and none of it is answered offline:
- **Prevalence & spread** — how often does each channel leak, per model? The memorable sentence ("cross-session memory leaks in X of Y models") lives only in a live run.
- **Provenance *changes what you learn*** — the demonstration is the per-channel breakdown: an output-only audit sees `N` leaks; provenance splits them into `tool-args / reasoning / memory`, which is *why* the whole-graph audit matters. The attribution machinery is measured (1.00, §5); the cross-channel breakdown numbers are the live experiment's output.
- **Architecture dependence** — explicit/list memory vs vector/semantic memory; a retrieval top-k policy. The deterministic exact-match store **cannot** answer this (an honest gap, not a covered case), so the measured *rate* does not generalize even though the *engineering* does.

Until those land the contribution is an instrument, not a finding — and a live result could be compelling (a cross-model spread) or flat (uniform ~0%); the framework is useful either way, but the empirical impact is not. That outcome is stated up front, not hedged after.

## 8. Conclusion

Independent of the live run, the result is that **provenance-based leakage instrumentation generalizes**: the same S → P → J → E substrate that audits tool-call arguments and reasoning traces extends — ~740 LOC reused byte-identical, ~80 channel-specific — to persistent memory, a *cross-session* channel no output-only or single-session instrument can reach. Persistent memory is the third instance and the proof the abstraction holds; retrieval is next; the cross-model prevalence study (§7) is the scoped next step.

## Instances (code)
- `memory_exfil_channel.md` — persistent-memory provenance (this framework's cross-session instance).
- Tool-args and reasoning-trace channels: `src/rogue/reproduce/agent/` (`trace_judge.py` signals, `reasoning_leak.py`, `evidence_bank.py`, `pii_provenance.py`).
