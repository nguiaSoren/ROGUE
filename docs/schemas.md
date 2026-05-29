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
    url: HttpUrl
    source_type: str = Field(..., description="reddit | x | arxiv | github | huggingface | blog | mitre | owasp | other")
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime
    archive_hash: str = Field(..., description="SHA-256 of raw fetched content")
    bright_data_product: str = Field(..., description="web_scraper_api | serp | unlocker | scraping_browser")


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

## Reproduce-layer types not in `schemas/` (referenced here for completeness)

These live in `src/rogue/reproduce/`, not `src/rogue/schemas/`, but a reader chasing the schema story will hit them:

- **`RenderedAttack`** (`reproduce/instantiator.py`) — the output of `render(primitive, config)`: the chat-message list plus **out-of-band multimodal payloads** `image_b64` / `image_media_type` (png or jpeg for EXIF) and `audio_b64` / `audio_format`. Carried out-of-band on purpose so `messages` stays plain text and only the dispatch layer (`target_panel`) is multimodal-aware — it attaches the image/audio as a provider-specific content block (OpenAI `image_url` data-URI / Anthropic `image.source.base64` / OpenAI-compat `input_audio`). This is the real-multimodal path (§10.8) that replaced the earlier text-only stub.
- **`BreachResult` (ORM, `db/models.py`)** carries extra columns beyond the wire model above for §10.7: `persona_used` (PAP A/B), `pair_iters_to_breach` + `pair_attacker_total_cost_usd` (iterative-attacker chains). The wire `BreachResult` here is the reproduction-core subset.
