"""The :class:`Finding` — one reproduced vulnerability against a deployment.

Customers see *risk*, not *attacks*: severity, how often it succeeds, and what to do about it.
Maps to an internal breaching ``AttackPrimitive`` cell, but the internal payload-engineering detail
(slots, embeddings, PAIR instrumentation) is hidden — only an illustrative excerpt is exposed.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from .common import Severity, explain_family, remediation_for, technique_label


class Finding(BaseModel):
    """A single vulnerability ROGUE reproduced against the deployment."""

    id: str
    severity: Severity
    family: str = Field(description="ROGUE attack-family slug, e.g. 'indirect_prompt_injection'.")
    technique: str = Field(default="", description="Human display label for the family.")
    vector: str = Field(description="Where the payload enters, e.g. 'rag_document', 'user_turn'.")
    title: str
    description: str = ""
    success_rate: float = Field(ge=0.0, le=1.0, description="Any-breach rate over n_trials.")
    n_trials: int = Field(ge=0, default=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    example_attack: str | None = Field(default=None, description="Illustrative payload excerpt.")
    example_response: str | None = Field(default=None, description="Illustrative model-response excerpt.")
    explanation: str = Field(
        default="", description="Plain-language 'what this is + why it matters' (synthesized by family)."
    )
    remediation: str = Field(default="", description="Mitigation guidance (synthesized by family).")
    source_url: str | None = None
    first_seen: datetime | None = None

    @field_validator("technique", mode="before")
    @classmethod
    def _fill_technique(cls, v, info):
        # Derive the display label from the family slug if the server didn't send one.
        if v:
            return v
        fam = info.data.get("family")
        return technique_label(fam) if fam else ""

    def model_post_init(self, __context) -> None:
        if not self.technique and self.family:
            object.__setattr__(self, "technique", technique_label(self.family))
        if not self.explanation and self.family:
            object.__setattr__(self, "explanation", explain_family(self.family))
        if not self.remediation and self.family:
            object.__setattr__(self, "remediation", remediation_for(self.family))

    @property
    def success_pct(self) -> str:
        """Success rate as a display percentage, e.g. '81%'."""
        return f"{round(self.success_rate * 100)}%"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity.value.upper()}] {self.title} — {self.success_pct} ({self.technique})"


__all__ = ["Finding"]
