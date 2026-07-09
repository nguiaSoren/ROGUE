# Observable leakage channels — a provenance-instrumentation framework

**Elevator pitch.** *ROGUE turns hidden agent-internal channels — tool-call arguments, reasoning traces, persistent memory, retrieval — into observable, provenance-labeled leakage channels that can be measured with deterministic canaries.* Everything below is an instance of that one idea.

**Contribution (stated once).** We do **not** contribute a new attack. We contribute a **reusable, provenance-based instrumentation framework** that makes leakage measurable — with deterministic, ground-truth canary tracking — on observable internal execution channels *that admit a plantable secret and a discrete egress*. We demonstrate it on **four** channels sharing one substrate (persistent memory the hardest instance, retrieval the cheapest), argue in §2.5 which channels do and do not fit, and are explicit that "four instances" is evidence *for* the abstraction, not a proof it covers every conceivable channel.

**Status:** framework spec + **4 instantiated channels** shipped (tool-args, reasoning-traces, persistent-memory, retrieval). The reuse and the provenance-attribution accuracy are demonstrated at $0 (below); the cross-model *prevalence* finding is the open empirical question (§7) and needs a live run.

## 1. Why output-only auditing is not enough

A leak is not only what a model *says*. A tool-using, memory-bearing agent exposes a value through many observable execution channels, and an audit of the final response is blind to all of them. This is measured, not asserted: AgentLeak (2602.11510) finds **41.7% of traces are "false-clean"** — the output passes every check while an internal channel leaked. Trace-logging tools (LangSmith, Phoenix, and agent observability generally) *see* those channels — they record tool calls and memory ops — but they log **what happened**, not **whether a secret leaked** or **where it came from**. The gap this framework fills is adversarial, ground-truth leakage *measurement* with provenance, not trace visibility (§6).

**Why provenance, not just detection.** Existing audits detect that a value leaked but cannot *attribute the channel*. Provenance lets us distinguish whether a leaked value originated from a tool output, a reasoning trace, retrieval, or persistent memory — which is what enables **channel-specific defenses** (you cannot patch a channel you cannot name) and **longitudinal measurement** (each channel's leak rate tracked across models and over time). Detection says *that* you leaked; provenance says *where from* — the actionable half, and what the per-channel breakdown in §7 is for.

## 2. The channel abstraction (formal)

> **Definition 1 (Leakage channel).** A leakage channel is a tuple **C = ⟨S, P, J, E⟩** where
> - **S — source:** a function that plants a ground-truth secret `κ` at a known site on the channel (an HMAC-minted, unguessable canary in a tool return / a context window / a memory record). Unguessability gives the key property: `κ` cannot appear downstream unless the model actually read it off the channel, so any match is near-zero-FP.
> - **P — provenance:** a labeling `π(v) → {planted, retrieval, memory, parametric, ambiguous}` attributing an emitted value `v` to its origin along the execution graph (single-hop v1). The `memory` label is what lets provenance extend **across execution boundaries** — origin can be a *prior* session, not just this execution.
> - **J — judge:** a deterministic predicate over the replayable trace that decides leak / no-leak per the channel's egress semantics (temporal + sink-graded), with no LLM in the deterministic-rate path.
> - **E — evidence:** a bank of what the agent *learned* on the channel, so a non-verbatim exfil (a decoded/paraphrased copy of `κ`) is still caught (a hardening tier that does not enter the deterministic rate).

> **Algorithm 1 (Instrument a channel).**
> ```
> plant κ via S at a known site                     # ground truth
> run the agent, record the replayable trace T      # execution graph
> for each emitted value v in T:
>     if v derives from κ (verbatim | E-decoded):    # J: near-zero-FP by |κ| unguessability
>         label ← P(v)                               # provenance: where κ entered
>         emit finding(channel=C, provenance=label, egress=sink?(v))
> ```

> **Proposition 1 (deterministic matching has negligible false positives).** If `κ` is computationally unguessable (≥ 80 bits of HMAC entropy) and every detection requires observing `κ` verbatim or via one of a fixed set of allowed decode transforms, then the probability that a model emits a `κ`-derived value *without* having read `κ` off the channel is negligible (≤ 2⁻⁸⁰ per independent guess for a verbatim match; bounded by the finite transform set for a decoded match). *Sketch:* the model has no access to `κ` except by reading it on the instrumented channel, and reproducing an 80-bit value by chance is negligible; the decode tier only widens the accepted forms by a fixed, enumerable family, which does not change the order of the bound.

Adding a channel means supplying **S** (a new plant site) and one new **P** label; **J** and **E** are reused unchanged. That is the framework's claim, and §3 shows it holds by construction, not by assertion.

## 2.5 Why these four — sufficiency, ground truth, and boundaries

The LOC in §3 shows the components *reuse*; this section argues they are the *right* components — a conceptual claim, not a code-reuse one.

**Sufficiency (for this class).** Measuring a leak with attribution requires answering exactly four questions, and each maps to one component. (1) *Did a **known** secret leak?* — you need ground truth, so you plant it (**S**). (2) *Where did it come from?* — origin attribution (**P**). (3) *Did it actually leave?* — an egress decision per the channel's exit semantics (**J**). (4) *Was it verbatim or transformed?* — representation-independence (**E**). Drop any one and a capability collapses: no **S** → no ground truth, so false positives; no **P** → a count without attribution; no **J** → detection with no leak/no-leak decision; no **E** → a verbatim-only blind spot. For the **class of observable leakage channels considered here** — those admitting a plantable secret and a discrete egress — these four are the minimal decomposition. We claim sufficiency for this class, **not universally**: a channel requiring probabilistic or confidence-based attribution (a diffuse, uncertain origin) would *extend* the abstraction rather than fit it (see boundaries).

**Ground truth is the point, not a weakness.** A fair objection is that our provenance is "source labeling, not inference" — the label is known because *we* planted the canary. Correct, and deliberate. Inferring the origin of an *arbitrary* emitted value is undecidable in general; planting a ground-truth secret trades that away for a **deterministic, near-zero-FP measurement** (Proposition 1). That trade is what separates a measurement *instrument* from a heuristic *detector*: we do not claim to attribute any value in the wild, we claim to *measure* leakage on a channel we control the plant on.

**Ambiguity is the harder, more interesting case.** The easy case — a canary planted on one channel, observed on that channel — is deterministic by construction, so its "accuracy" is not the interesting number. The real provenance question is **multi-source ambiguity**: a value observable from *two* channels at once (e.g. the same datum sitting in both a retrieved document and a recalled memory). The single-hop v1 resolves such conflicts by a fixed precedence and emits an explicit `AMBIGUOUS` label when a planted value also surfaces from a non-planting source; genuine *equal-attribution* across channels is not decidable single-hop and is exactly the multi-hop boundary below. Naming this is more honest than headlining the easy-case number: the single-hop provenance eval *does* measure **1.00 accuracy on a 36-item labeled set** (`pii_provenance.py`), but that is the easy case — deterministic by construction — not the interesting one.

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

The tables are the evidence; the argument is conceptual: a new channel is *one plant site, one provenance label, one judge predicate* against a fixed substrate. Memory is the outlier that needs materially more new code — a persistent store — precisely because it is the only cross-session channel; the within-session channels need none.

## 4. The cross-session path (persistent memory instance)

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
| the **deterministic judge** (use an LLM judge) | trace evaluation enters the ~31% false-positive regime | cited (ToolEmu); ROGUE's core rate is deterministic by design |
| **provenance** | you get a leak *count*, not the per-channel breakdown that makes leaks comparable and defenses targetable | attribution on the *planted* value is deterministic by construction (Prop 1); the hard case is multi-source ambiguity (§2.5). The breakdown *values* are the live experiment (§7) |

## 6. Positioning vs observability tools

| | traces tool calls / memory ops | plants ground-truth canaries | provenance attribution | deterministic breach verdict |
|---|:---:|:---:|:---:|:---:|
| observability / tracing (LangSmith, Phoenix, agent loggers) | ✓ | ✕ | ✕ | ✕ |
| **ROGUE leakage channels** | ✓ | ✓ | ✓ | ✓ |

*Honesty note:* observability platforms genuinely capture the traces (that's their job); the differentiator is not visibility but **adversarial leakage measurement** — planting ground truth, attributing provenance, and rendering a deterministic breach verdict. This row is a positioning claim on the *leakage-measurement* axis, to be re-checked against each tool's current features, not a certified feature audit.

## 7. Cost, and the open empirical question

**Cost (measured / bounded, $0 parts).** Off by default → **zero** overhead when disabled (byte-identical). The judge is a deterministic canary match → **no LLM judge call** (unlike a graded scan, this channel adds no per-trial judge cost). The store is `O(records)` in memory (a dict). The only real spend is the target model calls of the live probe itself — which is the paid arm, not framework overhead.

**The framework is evaluated for correctness offline (§5); prevalence is evaluated online.** The correctness properties above are complete; the empirical questions below are not answered offline by construction:
- **Prevalence & spread** — how often does each channel leak, per model? A statistically significant cross-model result ("cross-session memory leaks in X of Y models") comes only from a live run.
- **Provenance changes what you learn** — without provenance an audit reports one number, `N` leaks; with it, the same `N` splits across the four channels (`tool-args a / reasoning b / memory c / retrieval d`), which is what makes leaks comparable and defenses targetable. The attribution machinery is validated offline (1.00 on a 36-item labeled set, `pii_provenance.py`), and a first provenance-*stratified* rate is already measured on the PII-emission axis; the cross-channel leak-rate breakdown *values* are the remaining live piece.
- **Architecture dependence** — explicit/list memory vs vector/semantic memory; a retrieval top-k policy. The deterministic exact-match store **cannot** answer this (an honest gap), so the measured *rate* does not generalize even though the *engineering* does.

Until those land the contribution is an instrument, not an empirical finding — and a live result could be a meaningful cross-model spread or a flat ~0%; the framework is useful either way, but the empirical impact differs. Stated up front, not hedged after.

## 8. Conclusion

Independent of the live run, the result is that **provenance-based leakage instrumentation generalizes**: one S → P → J → E substrate extends across four channels — tool-args, reasoning, persistent memory, and retrieval — the last two demonstrating both the hardest case (cross-session) and the cheapest (a source tool, no new judge). The cross-model prevalence study (§7) is the scoped next step that turns the instrument into an empirical finding.

## Instances (code)
- `memory_exfil_channel.md` — persistent-memory provenance (this framework's cross-session instance).
- Tool-args and reasoning-trace channels: `src/rogue/reproduce/agent/` (`trace_judge.py` signals, `reasoning_leak.py`, `evidence_bank.py`, `pii_provenance.py`).
