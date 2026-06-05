"""The :class:`Deployment` — the customer's LLM deployment under test.

Maps to internal ``DeploymentConfig`` server-side, but the customer only ever sees this shape.
A deployment is identified by ``(model × system_prompt × tools)``; ``customer_id`` is implicit from
the authenticated session and never appears here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Deployment(BaseModel):
    """A deployed LLM configuration to red-team.

    Construct one locally to describe what you run in production, then
    :meth:`Rogue.register` it to get a server-assigned ``id``::

        dep = rogue.register(name="Support Agent", model="gpt-5", system_prompt="...")
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, description="Server-assigned id; None until registered.")
    name: str = Field(description="Human label for this deployment.")
    model: str = Field(description="Model identifier, e.g. 'gpt-5' or 'anthropic/claude-opus-4-8'.")
    system_prompt: str | None = Field(default=None, description="The deployed system prompt.")
    tools: list[str] = Field(default_factory=list, description="Tool names exposed to the model.")
    forbidden_topics: list[str] = Field(
        default_factory=list, description="Topics this deployment must refuse."
    )
    provider: str | None = Field(
        default=None, description="Provider slug (openai/anthropic/vertex/custom); optional."
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_registered(self) -> bool:
        return self.id is not None

    def to_create_payload(self) -> dict:
        """The body for ``POST /v1/deployments`` (writable fields only)."""
        return {
            "name": self.name,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "forbidden_topics": self.forbidden_topics,
            "provider": self.provider,
        }

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        tag = self.id or "(unregistered)"
        return f"Deployment {tag} · {self.name!r} · {self.model}"


__all__ = ["Deployment"]
