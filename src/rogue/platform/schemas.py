"""Platform wire/service vocabulary (Pydantic) — the canonical types every surface speaks.

These mirror `docs/platform/ARCHITECTURE.md` §5. The SDK report objects (`ScanReport`/`Finding`/
`ValidationResult`/`BenchmarkReport`) are reused from `rogue.report`; this module adds the
orchestration-level types (the scan request, the persisted record, the status enum).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from rogue.schemas.governance import ClientPolicy


class ScanStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def is_terminal(self) -> bool:
        return self in (ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.CANCELED)


class TargetSpec(BaseModel):
    """What to scan. Either `endpoint` (custom OpenAI-compatible URL) or `provider` is required.

    `api_key` is the raw credential at the API boundary; the platform persists only a redacted
    reference (see tenancy/secrets) — it is excluded from any serialized `ScanRecord`.
    """

    endpoint: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    # Handle to the encrypted target key in the SecretStore (`secref_…`). On the hosted path the API
    # swaps the raw `api_key` for this before persist/enqueue; the worker resolves it just-in-time.
    api_key_ref: str | None = None
    system_prompt: str = ""

    @model_validator(mode="after")
    def _require_target(self) -> TargetSpec:
        if not self.endpoint and not self.provider:
            raise ValueError("TargetSpec needs either endpoint=... or provider=...")
        return self

    def redacted(self) -> dict:
        """A persist/log-safe snapshot (no raw secret)."""
        return {
            "endpoint": self.endpoint,
            "provider": self.provider,
            "model": self.model,
            "system_prompt_len": len(self.system_prompt),
            "has_api_key": self.api_key is not None or self.api_key_ref is not None,
        }


class ScanSpec(BaseModel):
    """A scan request — the body of POST /v1/scans (minus tenant fields, which come from auth)."""

    target: TargetSpec
    # "pack" = a small curated JSON pack (default/aggressive/compliance). "repertoire" = the live
    # harvested corpus (most-reproducible first). "ladder" = escalate each goal through the full
    # multi-tier arsenal (graduated techniques + CoJ + structured + image/audio renderers) — the
    # deepest + most expensive mode; budget defaults to a safe cap if unset. "policy" = scan a
    # decomposed ClientPolicy rule-by-rule against this cycle's corpus (build-04 §6 per-rule scanner);
    # requires `policy` to be set (a None policy in policy-mode fails clearly in the engine).
    mode: Literal["pack", "repertoire", "ladder", "policy"] = "pack"
    pack: str = "default"
    attacks: list[str] | None = None
    max_tests: int = Field(default=50, ge=1, le=1000)
    n_trials: int = Field(default=1, ge=1, le=10)
    budget: float | None = Field(default=None, ge=0)
    # policy-mode only: the decomposed customer policy (§3 output). Default None so every existing
    # spec is unchanged; the engine raises clearly if mode="policy" and this is None.
    policy: ClientPolicy | None = None
    # Surface-1 (Slack) context the cycle trigger threads through so the auto-signed attestation
    # entry is self-describing: {"agent": {...}, "families": [...], "ground_truth_refs": {...}}.
    # Default None so every existing spec — and every existing signed entry — is byte-identical;
    # build-06 §5 (ChangeWitness) reads this exact shape. Opaque JSON-able dict to the engine.
    surface1_context: dict | None = None


class ScanRecord(BaseModel):
    """The persisted status+result of a scan — what GET /v1/scans/{id} returns."""

    scan_id: str
    org_id: str
    project_id: str | None = None
    status: ScanStatus = ScanStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    n_tests: int = 0
    n_completed: int = 0
    n_breaches: int = 0
    top_attack: str | None = None
    score: float | None = None
    cost_usd: float = 0.0
    report_id: str | None = None
    error: str | None = None
    target: dict = Field(default_factory=dict)  # redacted TargetSpec snapshot
    pack: str = "default"
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"use_enum_values": False}


__all__ = ["ScanStatus", "TargetSpec", "ScanSpec", "ScanRecord"]
