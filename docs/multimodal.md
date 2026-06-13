# Multimodal red-team

How ROGUE turns harvested text attacks into real images and audio, auto-selects the modality, escalates across modalities until something breaches, and sources real-world carriers via Bright Data.

A jailbreak a model refuses as typed text often succeeds as a *picture* of that text — the OCR/vision path is less safety-aligned than the text path. ROGUE turns harvested text attacks into **real images and audio**, sends them to vision/speech models, and judges the result. Five published techniques are reimplemented as **deterministic, black-box renderers** (no model weights, no diffusion, byte-for-byte reproducible):

| Technique | Source | What it renders |
|---|---|---|
| **Promptfoo** | promptfoo.dev | text → image (the baseline) |
| **MML** | arXiv 2412.00473 | payload obfuscated into the image (base64 / word-replace / rotate / mirror) + a "decode-this" linkage prompt |
| **VPI** | arXiv 2506.02456 | attack drawn as authoritative UI chrome (system banner / chat / dialog / low-contrast), optionally composited onto a screenshot you supply |
| **PolyJailbreak** | arXiv 2510.17277 | cross-modal split — benign expert-roleplay text + payload hidden in a benign worksheet image |
| **ARMs** | arXiv 2510.02677 | a 17-strategy taxonomy + multi-turn escalation (crescendo / actor / acronym) |
| **CoJ** | arXiv 2410.03869 | multi-turn edit-step decomposition — split a refused request into benign sub-queries that reconstruct it (delete-then-insert / insert-then-delete / change-then-change-back) |

**Multimodality is native to the pipeline, not bolted on.** When ROGUE harvests an attack, the extractor records its *modality* on the `vector` field (`multimodal_image` / `multimodal_audio` vs text). Reproduction reads that and **automatically renders a multimodal-native attack as an image/audio and sends it to vision/speech models — no flag, no human, no "try text first."** The renderer itself is auto-selected by attack family. So the moment a multimodal jailbreak shows up in the wild, ROGUE reproduces it multimodally on the next run.

For *text* attacks the panel refused, those techniques compose into an **autonomous escalation ladder** that tries transforms in order and **stops at the first that breaches**, spanning all three modalities:

1. **image** — the payload rendered as a picture (typographic → OCR → MML → VPI)
2. **CoJ** — a deterministic edit-step chain (delete-then-insert / insert-then-delete / change-then-change-back)
3. **structured-data** — the payload re-cast as a JSON/CSV/YAML/XML document whose directive field carries it
4. **audio** — the payload spoken in each acoustic style (fast / noisy / …) against speech-capable models
5. **multi-turn escalation** — planner-authored, run as three sub-strategies in order: **crescendo → actor_attack → acronym** (optionally with the final turn rendered multimodally)

Tiers 1–4 need **no planner**, so the ladder keeps working even when the escalation planner refuses to author an attack; the planner backbone also auto-falls-back to a less-aligned model. **Composition beats the parts** — a multi-turn escalation whose final turn lands as an MML image has scored `full_breach` on models (GPT-5.4 Nano, Gemini) that resisted either the escalation or the image alone.

The ladder runs either as a standalone pass (`synthesize_escalations.py --ladder`) or **inline inside reproduce** (`reproduce_once.py --escalate`, off by default): when on, any primitive the whole panel refuses is laddered right after its cells finish, bounded by `--escalate-max-spend`.

## Real-world carriers via Bright Data

The renderers can draw a synthetic image — but a multimodal attack is far more realistic composited onto a **real** image. When extraction sees a multimodal attack that describes its carrier (e.g. *"overlay on a bank-login screenshot"*), it records that as `media_query`. A pipeline step (`../scripts/harvest/fetch_media_assets.py`) then uses **Bright Data** to fetch a matching real image — **SERP API** Google-Images search (`udm=2`) to find a candidate, **Web Unlocker** to download the bytes — and caches it under `../data/media_cache/`. The reproduction layer composites the attack overlay onto that real carrier and sends it to the vision panel.

So Bright Data does double duty: it **discovers** the attacks (SERP + Web Unlocker + Web Scraper + Scraping Browser + MCP) *and* **sources the real images** the multimodal attacks are tested against. The fetch is cached (deterministic replays, no re-spend) and gated (`$`-billed, run deliberately). `harvest → extract (media_query) → fetch-media (Bright Data) → reproduce (composite)`.
