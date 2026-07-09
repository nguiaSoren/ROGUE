# Payload embeddings carry a technique signal too weak to separate (Tier-A pilot)

*Lab note · ROGUE retrieval/embedding layer · 2026-06-11. Corroborates the HF-datasets "0 new families" result (in the research backlog) and extends arXiv 2506.12685 to ROGUE's production embedder.*

## The question
A proposed paper imagined a **unified multimodal + multilingual embedding** over payload / technique / primitive — a shared space that indexes, dedups, and detects novelty across modalities and languages. Before any of that, one precondition has to hold: **do attack payloads even cluster by TECHNIQUE (family) in a real embedding space — or does surface form / topic dominate, with technique only faintly recoverable?** If payload text doesn't separate by technique in a strong embedder, a "technique/primitive embedding backbone" is weak before modality or language ever enters. This pilot tests exactly that, on data already on disk, for ~$0.

## Setup
- **Corpus:** the 45 unique judged payloads in `data/calibration/sample_50*.full.json` — `rendered_payload_excerpt` text, labelled by `family` (13 classes, lumpy: max 9, four singletons), `judge_verdict`, and `target_model`. Text-only, English-only.
- **Embedders:** SHA-256 hash (`deterministic_embed_fn`, a **null control**) · `all-MiniLM-L6-v2` (local) · `text-embedding-3-small` (ROGUE's **production** embedder).
- **Metrics, per embedder × labelling:** leave-one-out 1-NN accuracy under cosine (vs the majority-class baseline → *lift*), and cosine silhouette (global cluster separation).

## Result (2026-06-11)

| Embedder | family lift | verdict lift | model lift | silhouette (family) |
|---|---|---|---|---|
| hash (null control) | −0.13 | −0.24 | −0.11 | −0.08 |
| MiniLM (local) | **+0.18** | +0.02 | +0.00 | −0.03 |
| OpenAI 3-small (prod) | **+0.11** | −0.11 | −0.07 | −0.03 |

*(lift = LOO 1-NN accuracy − majority baseline; baselines: family 0.20, verdict 0.69, model 0.27.)*

Three things, all consistent across the two real embedders:
1. **The metric is valid.** The hash control sits at/below chance on every labelling (negative lift, silhouette ≈ 0) — random vectors carry no structure, as they must. The positive signals below are real, not artifacts.
2. **A faint technique signal exists — and it is the only real one.** `family` is the **only** labelling with a positive 1-NN lift in *both* real embedders (≈1.5–2× chance). `verdict` and `target_model` show ~zero or negative lift, so payload geometry does **not** encode the confounds — the signal you want (technique) shows up and the ones you'd fear (outcome, which model) don't. Robust to embedder choice (the MiniLM-vs-OpenAI gap is ~3 items at n=45 — noise).
3. **But it does not separate.** Silhouette ≈ 0 (slightly negative) for `family` in both real embedders: same-family payloads are pulled *slightly* closer than chance locally, but families heavily overlap — there are no globally separable technique clusters.

## Why it matters
The precondition is **only weakly met**, and it lands on the negative-result side arXiv 2506.12685 predicted: in payload-text embedding space, **surface/topic dominates and technique is only faintly recoverable.** Concretely — a technique/primitive embedding backbone built on payload text alone is a *weak* technique-level retrieval/dedup signal. This independently explains two things ROGUE already exhibits: the production deduplicator pairs cosine with a structural function-word JS-divergence secondary check (`src/rogue/dedupe/`), and the HF-dataset novelty run found **0 new families** because low cosine distance was lexical, not technique, novelty. Embedding distance is not a technique-novelty judgment.

## Honest caveats (no overclaim)
- **n = 45, one corpus, text-only, English-only.** A pilot signal, not a powered result. Families are lumpy and four are singletons that *structurally* cannot score a family-NN hit, so 0.31–0.38 modestly understates family coherence — but it does not move silhouette off ~0, which is the dominant finding.
- **This does NOT test the headline (modality/language invariance).** The corpus has no modality or language variation; the multilingual fixture is effectively one materialised language and the multimodal samples are images/audio. Testing invariance needs a true joint encoder (CLIP/CLAP/ImageBind) over native multimodal payloads — Tier B, which ROGUE does not have and which the multimodal discovery arms have not yet yielded data for.
- **1-NN at n=45 is noisy.** Treat lifts as directional, not precise.

## What would make it a paper
Tier B: a joint text+image+audio encoder over a *collected, labelled, multi-surface* corpus (same technique across modalities + languages at usable n), testing whether technique identity is modality/language-invariant — and whether a taxonomy-anchored space beats the flat baseline on a powered dedup/novelty task with ground-truth dup/novel labels (neither exists today). As of this pilot the contribution is **scope-blocked** (no on-disk multimodal/multilingual data, no labelled novelty set) **and scoop-exposed** (2506.12685; WildTeaming; "Guarding the Guardrails"; Con Instruction). Recommendation: do not stand it up as its own study — this note is the record so the idea isn't re-litigated. ⚑ Negative result, on file.

*Reproduce: `uv run --with sentence-transformers --with scikit-learn python scripts/calibration/tier_a_embedding_pilot.py` (3 embedders × 3 labellings; deterministic except the OpenAI call).*
