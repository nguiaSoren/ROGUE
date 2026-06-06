# Schemas

Extracted from ROGUE_PLAN.md §4.1. Pydantic v2 sources live in `src/rogue/schemas/`.

## `AttackPrimitive` (`schemas/attack_primitive.py`)

```python
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class AttackFamily(str, Enum):
    # 15 families — see docs/taxonomy.md
    DIRECT_INSTRUCTION_OVERRIDE = "direct_instruction_override"
    ROLE_HIJACK = "role_hijack"
    DAN_PERSONA = "dan_persona"
    POLICY_ROLEPLAY = "policy_roleplay"
    REFUSAL_SUPPRESSION = "refusal_suppression"
    MULTI_TURN_GRADIENT = "multi_turn_gradient"
    CHAIN_OF_THOUGHT_HIJACK = "chain_of_thought_hijack"
    SYSTEM_PROMPT_LEAK = "system_prompt_leak"
    TRAINING_DATA_EXTRACTION = "training_data_extraction"
    INDIRECT_PROMPT_INJECTION = "indirect_prompt_injection"
    TOOL_USE_HIJACK = "tool_use_hijack"
    OBFUSCATION_ENCODING = "obfuscation_encoding"
    LANGUAGE_SWITCHING = "language_switching"
    MULTIMODAL_INJECTION = "multimodal_injection"
    MULTI_TURN_PERSONA_CHAIN = "multi_turn_persona_chain"  # added 2026-05-27 (ActorAttack), §4.2 row 15


class AttackVector(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    USER_TURN = "user_turn"
    USER_MULTI_TURN = "user_multi_turn"
    TOOL_OUTPUT = "tool_output"
    RAG_DOCUMENT = "rag_document"
    MULTIMODAL_IMAGE = "multimodal_image"
    MULTIMODAL_AUDIO = "multimodal_audio"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SourceProvenance(BaseModel):
    # source_type / bright_data_product are `Literal` types in the real schema
    # (src/rogue/schemas/source_provenance.py); the ORM derives its CHECK
    # constraint vocabulary from those via typing.get_args — no duplication.
    url: HttpUrl
    source_type: str = Field(..., description="reddit | x | arxiv | github | huggingface | blog | mitre | owasp | vendor_safety_blog | discord_archive | community_archive | other")
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime
    archive_hash: str = Field(..., description="SHA-256 of raw fetched content")
    bright_data_product: str = Field(..., description="web_scraper_api | serp | web_unlocker | scraping_browser | mcp_server | fixture")


class DeploymentConfig(BaseModel):
    """The unit under test in the reproduction layer."""
    config_id: str
    customer_id: str
    name: str
    target_model: str = Field(..., description="e.g. 'openai/gpt-4o-mini'")
    system_prompt: str
    declared_tools: list[str] = Field(default_factory=list, description="e.g. ['web_fetch', 'code_exec']")
    forbidden_topics: list[str] = Field(default_factory=list)


class AttackPrimitive(BaseModel):
    """One reproducible attack technique, extracted from one or more open-web sources."""

    # Identity
    primitive_id: str = Field(..., description="ULID")
    cluster_id: Optional[str] = Field(None, description="set by dedup; canonical primitive shares its id")
    canonical: bool = Field(False)

    # Classification
    family: AttackFamily
    secondary_families: list[AttackFamily] = Field(default_factory=list, description="real attacks often combine 2-3")
    vector: AttackVector
    title: str = Field(..., max_length=120)
    short_description: str = Field(..., max_length=500)

    # The payload
    payload_template: str = Field(
        ...,
        description="Attack prompt with {slot} variables. Slot vocabulary in §4.3."
    )
    payload_slots: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Default substitution-slot values used when no customer override "
            "exists (§4.3 vocabulary). ALSO carries reproduce-layer "
            "renderer/strategy selectors read by render() — not substituted: "
            "image_strategy (typographic|ocr:<s>|mml:<m>|vpi:<s>|exif|polyjailbreak), "
            "mml_method, vpi_style, ocr_style, exif, polyjailbreak, base_image, "
            "audio_style, structured_data (json|csv|yaml|xml). See modality_renderers/."
        )
    )
    multi_turn_sequence: Optional[list[str]] = Field(
        None,
        description="For MULTI_TURN_GRADIENT and similar: ordered list of turn templates."
    )

    # Claims from the source
    target_models_claimed: list[str] = Field(default_factory=list)
    claimed_success_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    claimed_first_seen: Optional[datetime] = None

    # Quality
    reproducibility_score: int = Field(..., ge=0, le=10)
    requires_multi_turn: bool = False
    requires_system_prompt_access: bool = False
    requires_tools: list[str] = Field(default_factory=list)
    requires_multimodal: bool = False

    # Provenance
    sources: list[SourceProvenance] = Field(..., min_length=1)
    discovered_at: datetime

    # ROGUE-assigned severity
    base_severity: Severity
    severity_rationale: str = Field(..., max_length=800)

    notes: Optional[str] = Field(None, max_length=1000)
```

## `BreachResult` (`schemas/breach_result.py`)

```python
class JudgeVerdict(str, Enum):
    REFUSED = "refused"
    EVADED = "evaded"
    PARTIAL_BREACH = "partial_breach"
    FULL_BREACH = "full_breach"
    ERROR = "error"


class BreachResult(BaseModel):
    breach_id: str
    primitive_id: str                          # FK to AttackPrimitive
    deployment_config_id: str                  # FK to DeploymentConfig
    trial_index: int
    temperature: float
    rendered_payload: str                      # full prompt sent
    model_response: str                        # full response received
    verdict: JudgeVerdict
    judge_rationale: str = Field(..., max_length=500)
    judge_confidence: float = Field(..., ge=0.0, le=1.0)
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    ran_at: datetime
```

## Schema decisions worth justifying

- **Why `payload_template` + `payload_slots` instead of a single `payload` string?** Reproduction needs to vary the forbidden topic to compare across deployments fairly. Template lets us ask "does this *pattern* work for any forbidden topic, or only the one in the original post?" High success across topics → real pattern. High only on one topic → one-off.
- **Why ULIDs?** Lexicographically sortable, chronological feed renders cleanly, JSON exports read in order.
- **Why store `rendered_payload` + `model_response` on every BreachResult?** Reproducibility. A judge looking at the repo can replay the exact attack and verify the exact result.
- **Why `DeploymentConfig` and not just `customer_system_prompt_id`?** Because attacks like `TOOL_USE_HIJACK` need to know *which tools* the deployment exposes. A system prompt alone underspecifies the attack surface.
- **Why `secondary_families` list?** Because OWASP LLM01 indirect prompt injection often combines with TOOL_USE_HIJACK, and a single-label classifier hides that signal. Multi-label is a future paper; primary + secondaries is enough for the hackathon.
- **Why `multi_turn_sequence` separate from `payload_template`?** Multi-turn attacks (Crescendo, Many-shot) are not single strings. The reproduction layer's `render()` returns a list of messages for these primitives.

## `TechniqueProfile` (`schemas/technique_profile.py`)

Retrieval-optimised view of one attack technique. Used by the Technique Retrieval System (`src/rogue/retrieval/`) to match techniques to targets during escalation planning. Unlike `TechniqueSpec` (the extraction-time wire type), `TechniqueProfile` is the *retrieval-time* representation — it carries telemetry keys that align with `ladder_attempts.entity_id` and `ladder_rotation_membership.strategy_id`.

The `family` field is a **free string** and intentionally not bound to the frozen `AttackFamily` enum. The retrieval system must reason across ARMS patterns, taxonomy families, renderer tiers, and harvested-method categories in one field, and the frozen taxonomy must not be extended (§13 non-goal).

| Field | Type | Description |
|---|---|---|
| `label` | `str` (required) | Canonical retrieval + telemetry key matching `ladder_attempts.entity_id`, e.g. `"crescendo"`, `"image:mml:wr"` |
| `technique_id` | `str` (default `""`) | Strategy ULID when available; may equal `label` when no ULID is assigned |
| `name` | `str` (required) | Human-readable short name |
| `family` | `str` (required) | ARMS pattern / attack family / `"renderer_tier"` / `"harvested_method"` — free string |
| `description` | `str` (default `""`) | Prose description of what the technique does |
| `principle` | `str` (default `""`) | One-line design rationale (why the method works), paper-style |
| `steps` | `list[str]` (default `[]`) | Ordered method steps |
| `modalities` | `list[str]` (default `[]`) | How the technique is realised, e.g. `["text"]`, `["image"]`, `["multi_turn"]` |
| `historical_targets` | `list[str]` (default `[]`) | Vendor/family strings this label has confirmed breaches against, e.g. `["anthropic/haiku"]` |
| `origin` | `str` (default `"arms"`) | `"arms"` \| `"harvested"` \| `"tier"` |
| `tier` | `str` (default `""`) | `"image"` \| `"coj"` \| `"structured"` \| `"audio"` \| `"planner"` \| `""` |

## `TargetFingerprint` (`schemas/target_fingerprint.py`)

Capability profile of one deployment target. Used by the Technique Retrieval System to filter techniques to those that are actually executable against a given target (e.g. skip image-modality techniques when `supports_images=False`), and to warm-start retrieval ranking via the `known_successes` evidence list.

`target_key` is the canonical identifier — it matches the `target_model` string used throughout the reproduction layer.

| Field | Type | Description |
|---|---|---|
| `target_key` | `str` (required) | The `target_model` string, e.g. `"anthropic/claude-haiku-4-5"` |
| `vendor` | `str` (required) | Model vendor, e.g. `"anthropic"`, `"openai"` (from `adapters/model_specs.py:extract_vendor`) |
| `model_family` | `str` (required) | Model family within the vendor, e.g. `"claude-haiku"`, `"gpt-4o"` (from `extract_model_family`) |
| `supports_images` | `bool` (default `False`) | True iff the target accepts image inputs (enables image-modality techniques) |
| `supports_audio` | `bool` (default `False`) | True iff the target accepts audio inputs (enables audio-modality techniques) |
| `context_length` | `int \| None` (default `None`) | Maximum context length in tokens, or None if unknown |
| `reasoning_model` | `bool` (default `False`) | True iff the model is a chain-of-thought / reasoning model (e.g. o1, o3) |
| `known_successes` | `list[str]` (default `[]`) | Technique labels (matching `TechniqueProfile.label`) known to breach this target; populated from `ladder_attempts` when a DB session is available |

**Builder.** `src/rogue/retrieval/target_fingerprint.py:build_target_fingerprint(target_model, *, session=None, deployment_config=None)` assembles a `TargetFingerprint`. Capability flags are read from `adapters/model_specs.py`; `known_successes` is populated from `ladder_attempts` (winner rows) when a session is provided; all fields fail-safe (unknown models default to `False`/`None`).

## Grammar-component study types (`schemas/grammar_node.py`)

These types are the wire format and vocabulary for the grammar-component predictive-power study (observational, $0). They are **additive** — they do not touch `AttackFamily`, `AttackVector`, or any other locked enum, and they are stored in a dedicated side table (`primitive_grammar_labels`, migration `0027`) that does not modify the core schema.

### `GrammarNode` (enum)

A vocabulary of 23 structural grammar nodes that decompose attack primitives at the *how-it-is-constructed* level, sitting below the frozen `AttackFamily` *what-it-attempts* taxonomy. Values are lowercase snake_case and are used directly as Postgres enum values (no transformation). Source: `src/rogue/schemas/grammar_node.py:GrammarNode`.

**Family-mirroring nodes** (derived from `family` / `secondary_families` — controlled baseline):

| Value | Meaning |
|---|---|
| `role_hijack` | Attack overrides or hijacks the assistant's assigned role identity |
| `dan_persona` | Classic DAN / alter-ego jailbreak persona pattern |
| `policy_roleplay` | Role-play framing invoking fictional policy exceptions |
| `refusal_suppression` | Explicit instruction to suppress refusal responses |
| `direct_override` | Direct imperative explicitly superseding the system prompt |
| `system_prompt_leak` | Attack designed to elicit / exfiltrate the system prompt |
| `training_data_extraction` | Attack eliciting memorised training corpus fragments |
| `indirect_injection` | Malicious payload delivered through an indirect channel (RAG / URL / tool output) |
| `tool_invocation` | Attack exploiting or hijacking a tool / function-call surface |
| `chain_of_thought_hijack` | Attack steering or forging the model's CoT reasoning |
| `multimodal` | Payload carried in an image, audio, or non-text modality |

**Cross-family structural nodes** (derived from `payload_slots` keys and `requires_multi_turn` — the non-circular, analytically interesting set):

| Value | Derivation hint | Corpus n |
|---|---|---|
| `authority_frame` | `payload_slots` has `authority_claim` or `justification` non-empty | ~111 |
| `language_shift` | `payload_slots` has `language` non-empty; or `language_switching` family | ~3 |
| `encoding_obfuscation` | `payload_slots` has `encoding_scheme` non-empty; or `obfuscation_encoding` family | ~34 |
| `structured_output` | `payload_slots` has `target_output_format` or `NewResponseFormat` non-empty | ~57 |
| `fictional_framing` | `payload_slots` has role-description referencing narrative; and policy_roleplay/dan/role_hijack family | — |
| `multi_turn_escalation` | `requires_multi_turn == True`; or `multi_turn_gradient`/`multi_turn_persona_chain` family | ~42 |
| `trigger_backdoor` | `payload_slots` has `trigger_phrase` non-empty | ~59 |
| `exfiltration` | `payload_slots` has `exfil_destination` non-empty | ~45 |
| `persona_construction` | `payload_slots` has `role_name` and (`role_description` or `personality_trait`) non-empty | ~57+46 |
| `target_behavior_specification` | `payload_slots` has `target_behavior` and/or `target_topic` non-empty | ~206 |
| `invisible_injection` | `payload_slots` has `invisible_tag_instruction` non-empty; or zero-width Unicode in payload | ~4 |
| `rag_poisoning` | `payload_slots` has `rag_document` or `poison_payload` non-empty; and `indirect_prompt_injection` family | ~119 |

Full derivation logic and descriptions are in `GRAMMAR_NODE_META` (`src/rogue/schemas/grammar_node.py`).

### `GrammarLabel` (Pydantic)

A single grammar-node label assigned to one `AttackPrimitive`. One primitive carries multiple `GrammarLabel` instances — one per assigned node. Produced by the heuristic labeler (`src/rogue/grammar/labeler.py`). Source: `src/rogue/schemas/grammar_node.py:GrammarLabel`.

| Field | Type | Description |
|---|---|---|
| `primitive_id` | `str` (required, min_length=1) | ULID of the `AttackPrimitive` this label is attached to |
| `node` | `GrammarNode` (required) | The grammar node assigned to this primitive |
| `source` | `Literal["heuristic", "manual", "llm"]` (default `"heuristic"`) | How this label was produced |
| `confidence` | `float` in [0, 1] (default `1.0`) | Labeler confidence; heuristic labels default to 1.0; LLM labels should carry the model's probability estimate |

### `PrimitiveGrammarLabel` (ORM — `primitive_grammar_labels` table, migration `0027`)

The storage twin of `GrammarLabel`. One append-only row per `(primitive_id, node, source)` triple. Source: migration `src/rogue/db/migrations/versions/0027_primitive_grammar_labels.py`.

| Column | Type | Notes |
|---|---|---|
| `id` | `BigInteger` PK, autoincrement | Surrogate key |
| `primitive_id` | `String(40)` FK → `attack_primitives.primitive_id`, indexed | The labeled primitive |
| `node` | `Enum grammar_node` (Postgres), indexed | Value drawn from `GrammarNode` enum values (lowercase snake_case) |
| `source` | `String(20)`, server default `"heuristic"` | `"heuristic"` \| `"manual"` \| `"llm"` |
| `confidence` | `Float`, server default `1.0` | Labeler confidence |
| `created_at` | `DateTime(timezone=True)`, indexed, server default `now()` | Append-only timestamp |

**Unique constraint:** `uq_grammar_label_pid_node_source` on `(primitive_id, node, source)` — one label per source per (primitive, node); all three source variants can coexist on the same node for the same primitive.

**Postgres enum `grammar_node`:** created by migration `0027` from `GrammarNode.value` members (not names) to match the ORM's `values_callable` — wire and storage vocabularies cannot drift. Dropped on `downgrade`.

## Reproduce-layer types not in `schemas/` (referenced here for completeness)

These live in `src/rogue/reproduce/`, not `src/rogue/schemas/`, but a reader chasing the schema story will hit them:

- **`RenderedAttack`** (`reproduce/instantiator.py`) — the output of `render(primitive, config)`: the chat-message list plus **out-of-band multimodal payloads** `image_b64` / `image_media_type` (png or jpeg for EXIF) and `audio_b64` / `audio_format`. Carried out-of-band on purpose so `messages` stays plain text and only the dispatch layer (`target_panel`) is multimodal-aware — it attaches the image/audio as a provider-specific content block (OpenAI `image_url` data-URI / Anthropic `image.source.base64` / OpenAI-compat `input_audio`). This is the real-multimodal path (§10.8) that replaced the earlier text-only stub.
- **`BreachResult` (ORM, `db/models.py`)** carries extra columns beyond the wire model above for §10.7: `persona_used` (PAP A/B), `pair_iters_to_breach` + `pair_attacker_total_cost_usd` (iterative-attacker chains). The wire `BreachResult` here is the reproduction-core subset.
