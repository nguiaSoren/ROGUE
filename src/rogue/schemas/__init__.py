"""Public schema surface for ROGUE.

Re-exports every Pydantic type + enum + helper that downstream layers (harvest,
extract, dedupe, reproduce, diff, mcp_server, api) consume. Import through this
module — never reach into a sibling file directly — so the wire contract has a
single, greppable entry point:

    from rogue.schemas import AttackPrimitive, BreachResult, DeploymentConfig

The sibling modules are split by lifecycle, not by domain:
  - attack_primitive.py   — produced by the extraction layer, consumed by everyone
  - breach_result.py      — produced by the reproduction layer, consumed by diff
  - deployment_config.py  — fixed input; defines the unit under test (+ the Acme demo)
  - raw_document.py       — transient harvest→extract wire type (not persisted)
  - source_provenance.py  — attached to AttackPrimitive.sources by the harvest layer

Spec: ROGUE_PLAN.md §4 (schema + taxonomy + slot vocabulary).
"""

from .attack_primitive import (
    FAMILY_WEIGHTS,
    VECTOR_WEIGHTS,
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    Severity,
    severity_from_score,
)
from .breach_result import (
    BREACH_VERDICTS,
    FULL_BREACH_VERDICTS,
    BreachResult,
    ExfiltrationMethod,
    JudgeVerdict,
)
from .deployment_config import (
    ACME_FORBIDDEN_TOPICS,
    ACME_SYSTEM_PROMPT,
    DeploymentConfig,
    demo_deployment_configs,
)
from .raw_document import RawDocument
from .source_provenance import (
    BrightDataProduct,
    SourceProvenance,
    SourceType,
)
from .renderer_manifest import (
    LIFECYCLE_ORDER,
    SYNTHESIS_ONLY_STATES,
    RendererManifest,
    RendererOrigin,
    RendererStatus,
)
from .technique_spec import (
    AUTO_INTEGRABLE_MODALITIES,
    Modality,
    RetireReason,
    StrategyStatus,
    TechniqueSpec,
)
from .technique_profile import TechniqueProfile
from .target_fingerprint import TargetFingerprint
from .grammar_node import (
    GrammarNode,
    GRAMMAR_NODE_META,
    GrammarLabel,
)
from .generator import PayloadGenerator
from .agent_tool import (
    AgentToolSpec,
    InjectionGoal,
    InjectionGoalKind,
    LiveToolTarget,
    ToolBackendKind,
    ToolCategory,
    ToolSensitivity,
)
from .agent_transcript import (
    AgentBreachSignal,
    AgentTranscript,
    AgentTurn,
    DeterminismHeader,
    PlantedSecret,
    ReturnProvenance,
    ToolCallRecord,
    ToolResultRecord,
    TraceFinding,
    TranscriptEvent,
    TurnRole,
)

__all__ = [
    # attack primitive
    "AttackPrimitive",
    "AttackFamily",
    "AttackVector",
    "Severity",
    "FAMILY_WEIGHTS",
    "VECTOR_WEIGHTS",
    "severity_from_score",
    # breach result
    "BreachResult",
    "JudgeVerdict",
    "ExfiltrationMethod",
    "BREACH_VERDICTS",
    "FULL_BREACH_VERDICTS",
    # deployment config
    "DeploymentConfig",
    "ACME_SYSTEM_PROMPT",
    "ACME_FORBIDDEN_TOPICS",
    "demo_deployment_configs",
    # raw document
    "RawDocument",
    # source provenance
    "SourceProvenance",
    "SourceType",
    "BrightDataProduct",
    # technique spec (self-growing technique library — §10.9)
    "TechniqueSpec",
    "Modality",
    "StrategyStatus",
    "RetireReason",
    "AUTO_INTEGRABLE_MODALITIES",
    # renderer manifest (executable capability governance — §10.9 Phase 3b)
    "RendererManifest",
    "RendererStatus",
    "RendererOrigin",
    "LIFECYCLE_ORDER",
    "SYNTHESIS_ONLY_STATES",
    # technique retrieval system — profiles + target fingerprints
    "TechniqueProfile",
    "TargetFingerprint",
    # grammar-node vocabulary (structural predictive-power study)
    "GrammarNode",
    "GRAMMAR_NODE_META",
    "GrammarLabel",
    # agent execution harness — tool surface + replayable trace (docs/v2/agent_harness)
    "PayloadGenerator",
    "AgentToolSpec",
    "LiveToolTarget",
    "ToolCategory",
    "ToolSensitivity",
    "ToolBackendKind",
    "InjectionGoal",
    "InjectionGoalKind",
    "AgentTranscript",
    "AgentTurn",
    "TurnRole",
    "ToolCallRecord",
    "ToolResultRecord",
    "ReturnProvenance",
    "PlantedSecret",
    "DeterminismHeader",
    "TranscriptEvent",
    "TraceFinding",
    "AgentBreachSignal",
]
