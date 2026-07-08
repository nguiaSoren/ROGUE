# Observable leakage channels — a provenance-instrumentation framework (P5)

**Status:** framework spec + 3 instantiated channels shipped (tool-args, reasoning-traces, persistent-memory); retrieval next. The cross-model *prevalence* study is the open empirical question (see §7). This doc is the framework; the per-channel docs are its instances.

## 1. The claim

A leak is not only what a model *says*. A tool-using, memory-bearing agent exposes a value through many **observable execution channels** — tool-call arguments, reasoning traces, persistent memory, retrieval context — and an audit that inspects only the final response is structurally blind to all of them. The framework's claim is narrow and testable: **the instrumentation needed to catch a leak on any one channel is the same across channels**, so you build it once and instantiate per channel, and the interesting object is not any single channel but the *reusable instrument* and what it reveals when pointed at many channels at once.

The kernel is **provenance, not detection**. That a value appeared is one question; *where along the execution graph it originated* — retrieved, recalled from a prior session, or produced from parameters — is the harder, more useful one, and it is what turns a pile of channel logs into an attributable audit.

## 2. Why output-only detection is not enough (the baseline)

The simplest alternative is to scan the final answer for the secret. It cannot, by construction, see a secret that leaves through a tool argument, a private reasoning trace, or a recalled memory — the channels never touch the answer. This is measurable, not rhetorical: AgentLeak (2602.11510) reports that **41.7% of traces are "false-clean"** — the output passes every privacy check while an internal channel leaked. Naive per-channel logging is a second baseline: it records *that* a value appeared on a channel but not *where it came from*, so it cannot separate a genuine cross-session leak from the model legitimately echoing something it was just handed. The framework's value over both is **whole-graph auditing with attributable provenance**, and that is the comparison a paper should draw (a measured provenance-accuracy vs logging-accuracy gap is the natural experiment).

## 3. The channel abstraction

A channel is a tuple **⟨source, provenance, judge, evidence⟩**:

- **source (plant).** How a *ground-truth* secret is introduced at a known site so any later appearance is attributable — an HMAC-minted, unguessable **canary** planted in a tool return / a system-prompt context / a memory record. Unguessability is what makes a downstream match near-zero-false-positive: the model cannot emit the literal without actually reading it off the channel.
- **provenance.** The label attributing an emitted value to its origin along the execution graph — `PLANTED / RETRIEVAL / MEMORY / PARAMETRIC / AMBIGUOUS` (single-hop v1). This is the shared kernel; adding a channel is, in essence, adding one provenance label + the site that produces it.
- **judge.** A *deterministic* scorer over the replayable execution trace that decides leak / no-leak per the channel's egress semantics (sink-graded, temporal), with no LLM in the headline path — which is why the core rate escapes the ~31% false-positive regime of LLM-judged trace evaluation.
- **evidence.** An evidence bank of what the agent *learned* on the channel, so a non-verbatim exfil (a base64/hex/paraphrased copy) is still caught — a hardening tier, deliberately non-headline (the semantic sub-tier is an uncalibrated LLM).

The framework's structural bet: these four are **channel-agnostic**. `canaries.py`, `pii_provenance.py`, the trace-judge substring/temporal/sink logic, and `evidence_bank.py` are written once; a channel supplies only its plant site and its provenance label.

## 4. Instances

| Channel | source (plant site) | provenance | judge egress | distinguishing axis |
|---|---|---|---|---|
| **tool-call args** ✅ | canary in a SOURCE tool return | `RETRIEVAL` | canary in a later SINK call's args | within-session tool I/O |
| **reasoning traces** ✅ | secret in system-prompt / context | (RT-scoped) | secret in the reasoning channel, *absent from the answer* | private scratchpad |
| **persistent memory** ✅ | canary in a *dormant* memory record | `MEMORY` | recalled *cross-session* → SINK | **temporal persistence** |
| **retrieval (RAG)** — next | canary in a retrieved document | `RETRIEVAL` | surfaced from retrieved context | semantic recall |

Everything left of "distinguishing axis" is shared machinery; the rightmost column is the only thing each channel genuinely adds. That ratio — a lot of reused substrate, a little channel-specific novelty — is the systems contribution, and the paper must keep saying so: the value is the deployed, reusable instrument, not any one channel's plant.

## 5. What makes each channel distinct — and why memory earns its own instance

The temptation is to fold memory into retrieval (both "surface a stored value"). They differ on the one axis that matters here: **temporal persistence.** Tool-args, reasoning, and retrieval all plant and leak *within one session*; persistent memory is the only channel where the plant and the leak occur in **different sessions**, and where the payload re-enters a later session as **trusted** context rather than an untrusted tool output. That temporal gap is the whole attack surface — dormancy, a delayed topic-triggered activation, survival across many benign sessions — and it is not expressible as a within-session retrieval. So memory is not "retrieval again"; it is the channel that makes the audit *cross-session*, which is exactly the boundary an output-only or single-session instrument cannot cross.

## 6. Scope — what this is and is not

- It **is** instrumentation: a way to *measure* leakage across channels with attributable provenance, deployed continuously, off by default and byte-identical when off.
- It is **not** an attempt to improve any attack. The attacks are prior work (Trojan Hippo for memory, the injection literature for tool-args, Leaky Thoughts for reasoning); we operationalize and measure them, we do not raise their ASR. Reviewers should not compare a channel's leak rate against an attack paper's ASR — different objective, different threat model.
- The offline, deterministic validation proves **implementation correctness** (plant → surface → judge fires, off is byte-identical, no double-count), not **effectiveness on real models**. Those are different claims; §7 is the second.

## 7. The open empirical question (what deployment measures)

The framework is the instrument; the science is what it reads. None of the following is answered offline — they need a live cross-model run, and they are the paper's empirical core, honestly unfinished until it lands:

- **Prevalence & spread.** How often does each channel leak, per model? A memorable one-sentence result ("cross-session memory leaks in X% of agents; model Y never leaked") lives here, not in the plumbing.
- **Architecture dependence.** Does explicit/list memory leak differently from vector/semantic memory? Does a retrieval top-k policy change the rate? (Our deterministic store cannot answer this — it is an honest gap, §honest-boundaries in the memory doc.)
- **Trigger structure.** Which sensitive-topic trigger classes dominate cross-session activation?
- **Provenance accuracy cross-channel.** Does the single-hop provenance kernel attribute correctly as channels multiply — and what is the detection-vs-provenance gap (caught but mis-attributed) that justifies the whole-graph audit over naive logging (§2)?

Until these are measured the contribution is an instrument, not a finding. The instrument's value is that it makes them *measurable and comparable* under one framework — but a reviewer who wants the finding is right to, and the answer is the gated run, not more prose.

## 8. Conclusion

The result of this work, independent of the live run, is that **provenance-based leakage instrumentation generalizes**: the same source-canary → provenance → deterministic-judge → evidence-bank substrate that audits tool-call arguments and reasoning traces extends, unchanged in its core, to persistent memory — a channel that is *cross-session*, which no output-only or single-session instrument can reach. Persistent memory is the third instance and the proof that the abstraction holds; retrieval is the next. The cross-model prevalence study (§7) is the natural, and deliberately scoped, next step.

## Instances (code)
- `memory_exfil_channel.md` — persistent-memory provenance (this framework's cross-session instance).
- The tool-args and reasoning-trace channels are instantiated in the agent-exec harness: `src/rogue/reproduce/agent/` (`trace_judge.py` signals, `reasoning_leak.py`, `evidence_bank.py`, `pii_provenance.py`).
