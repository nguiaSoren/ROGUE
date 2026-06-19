"""TechniqueSpec — the unit of the *self-growing technique library* (§10.9).

ROGUE harvests two different things from the open web:
  - **Payloads** (a specific jailbreak prompt) → `AttackPrimitive`. Already automated.
  - **Techniques** (a reusable *method*: "render text as an image", "escalate over
    3 turns") → `TechniqueSpec`. This is the new, self-growing surface.

A `TechniqueSpec` is the structured-extraction output for a document the
3-way classifier labels `technique` (vs `payload` / `commentary`). It is the
wire/ storage twin of an entry in the hand-written strategy library
(`reproduce/arms_strategies.py`) — the `directive` field is the same operational
prompt fragment the `EscalationPlanner` injects, so harvested and hand-written
strategies are interchangeable (§10.9 risk-note 3: the table is the single source).

Lifecycle (`status`):
  - `candidate`            — freshly harvested; not yet trusted. NOT used by the planner.
  - `active`              — graduated: it actually breached something in a reproduction
                            run (Phase 4 gate). The planner reads these.
  - `needs_implementation`— a renderer technique (image/audio) whose *spec* is extracted
                            but whose *code* a human (or a sandbox, Phase 3b Option B)
                            must still write. Never auto-runs generated code unsandboxed.

Spec: ROGUE_PLAN.md §10.9 Phase 2.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------- Enums ----------


class Modality(str, Enum):
    """How a technique is realized. Splits the autonomy boundary (§10.9):

    - ``text`` / ``multi_turn`` are *just text directives* → auto-integrable, no new
      code (Phase 3a).
    - ``image`` / ``audio`` need a new renderer (new Python) → human/sandbox
      (Phase 3b); such techniques land as ``status=needs_implementation``.
    """

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    MULTI_TURN = "multi_turn"


#: Modalities that need no new code — a harvested technique in one of these can be
#: turned into a planner directive automatically (Phase 3a).
AUTO_INTEGRABLE_MODALITIES: frozenset[Modality] = frozenset(
    {Modality.TEXT, Modality.MULTI_TURN}
)


class StrategyStatus(str, Enum):
    """Lifecycle state of a harvested technique (§10.9 Phase 4).

    ``candidate → active → retired → archived`` is the graduation/retirement path;
    ``needs_implementation`` is the parallel terminal state for image/audio renderer
    techniques (Phase 3b). Retirement is *soft* — a ``retired`` technique is skipped
    in routine sweeps but can resurrect (back to ``active``) if it later breaches a
    new config/model (jailbreak effectiveness is non-stationary).
    """

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"
    ARCHIVED = "archived"
    NEEDS_IMPLEMENTATION = "needs_implementation"


class RetireReason(str, Enum):
    """Why a technique was retired (§10.9 Phase 4). Soft, reversible — kept for
    longitudinal robustness analytics, never hard-deleted."""

    NEVER_BREACHED_N_RUNS = "never_breached_n_runs"  # Rule A: evidence-based
    EXPIRED_TTL = "expired_ttl"  # Rule B: staleness
    MANUAL = "manual"
    BUDGET = "budget"


# ---------- The schema ----------


class TechniqueSpec(BaseModel):
    """One reusable attack *technique* (method), extracted from one open-web source.

    Identity is ``technique_id`` (ULID, stable across runs). Unlike `AttackPrimitive`,
    a technique is a *method* not an instance — it describes how to attack, not a
    specific prompt.
    """

    # ----- Identity -----
    technique_id: str = Field(
        ..., description="ULID, stable across runs", min_length=10
    )
    name: str = Field(
        ..., max_length=200, description="human-readable short name of the method"
    )

    # ----- Classification -----
    modality: Modality = Field(
        ..., description="text|image|audio|multi_turn — sets the autonomy boundary"
    )

    # ----- The method -----
    principle: str = Field(
        ...,
        max_length=2_000,
        description="one-line design rationale (why the method works), paper-style",
    )
    steps: list[str] = Field(
        default_factory=list,
        description="ordered method steps describing how to carry out the technique",
    )
    params: dict[str, str] = Field(
        default_factory=dict,
        description="tunable knobs of the method (e.g. {'n_turns': '3', 'font': 'mono'})",
    )
    example: Optional[str] = Field(
        None,
        max_length=20_000,
        description="a concrete illustration of the method applied (not a reusable payload)",
    )

    # ----- Realization -----
    directive: Optional[str] = Field(
        None,
        max_length=4_000,
        description=(
            "operational prompt fragment the EscalationPlanner injects to steer an "
            "attack toward this technique — the same shape as arms_strategies entries. "
            "Auto-synthesized for text|multi_turn techniques (Phase 3a); None until a "
            "renderer technique is implemented."
        ),
    )

    # ----- Provenance -----
    source_url: Optional[str] = Field(
        None, description="URL of the source document the technique was harvested from"
    )

    # ----- Lifecycle -----
    status: StrategyStatus = Field(
        StrategyStatus.CANDIDATE,
        description="candidate→active graduation gate (Phase 4); needs_implementation for renderers",
    )
    claimed_first_seen: Optional[datetime] = Field(
        None, description="when the source claims the technique first appeared"
    )

    @property
    def needs_new_code(self) -> bool:
        """True iff this technique requires a new renderer (image/audio) → human/sandbox."""
        return self.modality not in AUTO_INTEGRABLE_MODALITIES
