# Observable leakage channels — a provenance-instrumentation framework (P5)

**Elevator pitch.** *ROGUE turns hidden agent-internal channels — tool-call arguments, reasoning traces, persistent memory, retrieval — into observable, provenance-labeled leakage channels that can be measured with deterministic canaries.* Everything below is an instance of that one idea.

**Contribution (stated once).** We do **not** contribute a new attack. We contribute a **reusable, provenance-based instrumentation framework** that makes leakage measurable — with deterministic, ground-truth canary tracking — on observable internal execution channels *that admit a plantable secret and a discrete egress*. We demonstrate it on **four** channels sharing one substrate (cross-session persistent memory being the newest headline; retrieval the newest and cheapest), argue in §2.5 which channels do and do not fit, and are explicit that "four instances" is evidence *for* the abstraction, not a proof it covers every conceivable channel.

**Status:** framework spec + **4 instantiated channels** shipped (tool-args, reasoning-traces, persistent-memory, retrieval). The reuse and the provenance-attribution accuracy are demonstrated at $0 (below); the cross-model *prevalence* finding is the open empirical question (§7) and needs a live run.

## 1. Why output-only auditing is not enough

A leak is not only what a model *says*. A tool-using, memory-bearing agent exposes a value through many observable execution channels, and an audit of the final response is blind to all of them. This is measured, not asserted: AgentLeak (2602.11510) finds **41.7% of traces are "false-clean"** — the output passes every check while an internal channel leaked. Trace-logging tools (LangSmith, Phoenix, and agent observability generally) *see* those channels — they record tool calls and memory ops — but they log **what happened**, not **whether a secret leaked** or **where it came from**. The gap this framework fills is adversarial, ground-truth leakage *measurement* with provenance, not trace visibility (§6).

**Why provenance, not just detection.** Existing audits detect that a value leaked but cannot *attribute the channel*. Provenance lets us distinguish whether a leaked value originated from a tool output, a reasoning trace, retrieval, or persistent memory — which is what enables **channel-specific defenses** (you cannot patch a channel you cannot name) and **longitudinal measurement** (each channel's leak rate tracked across models and over time). Detection says *that* you leaked; provenance says *where from* — the actionable half, and the reason the per-channel breakdown in §7 is the result worth measuring, not the aggregate count.

## 2. The channel abstraction (formal)

> **Definition 1 (Leakage channel).** A leakage channel is a tuple **C = ⟨S, P, J, E⟩** where
> - **S — source:** a function that plants a ground-truth secret `κ` at a known site on the channel (an HMAC-minted, unguessable canary in a tool return / a context window / a memory record). Unguessability gives the key property: `κ` cannot appear downstream unless the model actually read it off the channel, so any match is near-zero-FP.
> - **P — provenance:** a labeling `π(v) → {planted, retrieval, memory, parametric, ambiguous}` attributing an emitted value `v` to its origin along the execution graph (single-hop v1). The `memory` label is what lets provenance extend **across execution boundaries** — origin can be a *prior* session, not just this execution.
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

## 2.5 Why these four — sufficiency, ground truth, and boundaries

The LOC in §3 shows the components *reuse*; this section argues they are the *right* components — a conceptual claim, not a code-reuse one.

**Sufficiency.** Measuring a leak with attribution requires answering exactly four questions, and each maps to one component. (1) *Did a **known** secret leak?* — you need ground truth, so you plant it (**S**). (2) *Where did it come from?* — origin attribution (**P**). (3) *Did it actually leave?* — an egress decision per the channel's exit semantics (**J**). (4) *Was it verbatim or transformed?* — representation-independence (**E**). Drop any one and a capability collapses: no **S** → no ground truth, so false positives; no **P** → a count without attribution (the aggregate, not the actionable breakdown); no **J** → detection with no leak/no-leak decision; no **E** → a verbatim-only blind spot. The four are the minimal decomposition of "measure a leak with attribution," which is why they recur across channels rather than being fitted to each.

**Ground truth is the point, not a weakness.** A fair objection is that our provenance is "source labeling, not inference" — the label is known because *we* planted the canary. Correct, and deliberate. Inferring the origin of an *arbitrary* emitted value is undecidable in general; planting a ground-truth secret trades that away for a **deterministic, near-zero-FP measurement**. That trade is exactly what separates a measurement *instrument* from a heuristic *detector*: we do not claim to attribute any value in the wild, we claim to *measure* leakage on a channel we control the plant on. Oracle ground truth is the enabling assumption, stated plainly.

**Detection ⟂ representation (the evidence bank is a principle, not a feature).** **E** encodes a clean separation the framework leans on: *detection* ("did the secret leak?") is decoupled from *representation* ("verbatim / base64 / paraphrased"). A leak is a leak whether the secret leaves raw, encoded, or derived; **E** is what lets **J** decide leak/no-leak independent of surface form. That decoupling — not the base64 decoder itself — is the conceptually load-bearing idea.

**Boundaries — channels that do NOT fit (so "everything fits" isn't by construction).** The abstraction has real edges. (a) *No plantable ground truth* — timing / resource / cache side-channels carry information with no site to plant a canary, so **S** has no instance; out of scope by design. (b) *Multi-hop, distributed provenance* — a secret passing through several agents needs **P** to be a taint *graph*, which the single-hop v1 **P** cannot express; that channel would require extending **P**, not reusing it. (c) *No discrete egress event* — gradual behavioral influence (a model nudged over many turns) has no sink for **J** to grade. Naming these is the honest test that the four components are a real abstraction with a boundary, not a definition stretched until everything fits.

**Relation to taint tracking / information-flow control.** IFC and dynamic taint tracking answer a superset question — track *all* flows — but require white-box access to instrument the runtime, are heavy, and do not apply to a black-box frontier model behind an API. This framework is the black-box dual: it plants a *known* secret and observes egress across observable channels with **no model internals**. It is deliberately *unsound* (it measures verbatim + decoded + planted-canary flows — a lower bound, never a completeness claim), and that is the trade that buys deployability against proprietary agents where taint/IFC cannot run. Complementary, not competing: IFC for systems you can instrument, canary-measurement for agents you can only observe.

## 3. Proof of reuse (not an assertion)

The substrate — **S** (`canaries.py`, 94 LOC) · **P** (`pii_provenance.py`, 94) · **J**-core (`trace_judge.py` minus per-channel methods, ~460) · **E** (`evidence_bank.py`, 91) ≈ **740 LOC** — is written once and shared **byte-identical**. Each channel supplies only a plant site, one provenance label, and one judge predicate. New vs reused, with real LOC:

| Channel | S | P | J | E | **new LOC** | **reused LOC** |
|---|:-:|:-:|:-:|:-:|--:|--:|
| tool-call args (baseline) | ✅ | ✅ `RETRIEVAL` | ✅ | ✅ | ~113 (signal-b+c) | ~740 |
| reasoning traces | ✅ | ✅ | ✅ | ✅ | 165 | ~740 |
| persistent memory | ✅ | ✅ +`MEMORY` | ✅ | ✅ (decode tier) | 82 judge (+224 store) | ~740 |
| retrieval (RAG) | ✅ | ✅ `RETRIEVAL` | ✅ | ✅ | **~15 (one source tool, 0 new judge)** | ~740 |

The retrieval row is the sharpest evidence for the abstraction: the 4th channel reuses the judge, the provenance label, and the evidence bank **unchanged** — it is a `retrieve_documents` source + the existing `RETRIEVAL` label, and its exfil is caught by the *same* signal-(b) predicate that serves tool-args. A new internal-leak channel that costs ~15 LOC and **zero new judge code** is what "reusable framework" means when it is true rather than asserted.

And per **component**, for the memory instance — what is reused vs written new:

| Component | Reused (shared) | New (memory instance) |
|---|---|---|
| canary mint (`canaries.py`) | ✅ 94 LOC | — (reused; only the plant *site* differs) |
| provenance (`pii_provenance.py`) | ✅ 94 LOC | +1 label (`MEMORY`) |
| judge core (`trace_judge.py`) | ✅ ~460 LOC | +82-LOC predicate (`judge_memory_exfil`) |
| evidence bank (`evidence_bank.py`) | ✅ 91 LOC | — (decode tier reused) |
| memory store (`memory_channel.py`) | — | **224 LOC** (new — the cross-session persistence) |
| honeytool pair (recall/save) | — | **70 LOC** (new) |

That is "reusable framework" made **measurable**: a new internal-leak channel costs one plant site + one provenance label + one judge predicate (**82–165 LOC**) against **~740 LOC of reused, byte-identical substrate** — not a new pipeline. The memory instance's own share is an 82-LOC `judge_memory_exfil` predicate + one `PIIProvenance.MEMORY` label, reusing J's substring/temporal/sink logic and E's decode tier (a base64/hex copy of the canary is still caught, non-headline — verified by test). Memory additionally needs a 224-LOC cross-session `MemoryStore` the within-session channels don't — the one place its LOC is higher, and precisely *because* it is the cross-session channel.

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
- **Provenance *changes what you learn*** — the demonstration is the per-channel breakdown. Without provenance an audit reports one number: `N` leaks. With it, the same `N` splits across the four channels — `tool-args a / reasoning b / memory c / retrieval d` — and *that* table is what makes leaks comparable and defenses targetable (you patch the channel that dominates). The attribution machinery is measured ($0: 3-way accuracy 1.00, §5); the cross-channel breakdown *values* are the live experiment's output, and are the single result that turns the instrument into a finding.
- **Architecture dependence** — explicit/list memory vs vector/semantic memory; a retrieval top-k policy. The deterministic exact-match store **cannot** answer this (an honest gap, not a covered case), so the measured *rate* does not generalize even though the *engineering* does.

Until those land the contribution is an instrument, not a finding — and a live result could be compelling (a cross-model spread) or flat (uniform ~0%); the framework is useful either way, but the empirical impact is not. That outcome is stated up front, not hedged after.

## 8. Conclusion

Independent of the live run, the result is that **provenance-based leakage instrumentation generalizes**: the same S → P → J → E substrate that audits tool-call arguments and reasoning traces extends — ~740 LOC reused byte-identical, ~80 channel-specific — to persistent memory, a *cross-session* channel no output-only or single-session instrument can reach. Persistent memory is the third instance and the proof the abstraction holds; retrieval is next; the cross-model prevalence study (§7) is the scoped next step.

## Instances (code)
- `memory_exfil_channel.md` — persistent-memory provenance (this framework's cross-session instance).
- Tool-args and reasoning-trace channels: `src/rogue/reproduce/agent/` (`trace_judge.py` signals, `reasoning_leak.py`, `evidence_bank.py`, `pii_provenance.py`).
