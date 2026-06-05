"""Deployment registration (Deliverable 4): the customer's deployment as a first-class object."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exceptions import ValidationError
from ..models.deployment import Deployment
from ..utils.validation import validate_deployment

if TYPE_CHECKING:
    from .rogue import Rogue


class DeploymentsClient:
    """CRUD for deployments. Reachable as ``rogue.deployments`` (or the ``rogue.register`` sugar)."""

    def __init__(self, rogue: Rogue):
        self._r = rogue

    def register(
        self,
        name: str | None = None,
        model: str | None = None,
        *,
        deployment: Deployment | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        forbidden_topics: list[str] | None = None,
        provider: str | None = None,
    ) -> Deployment:
        """Register a deployment and return it with a server-assigned id.

        Either pass a prebuilt :class:`Deployment` via ``deployment=``, or the fields directly.
        Validates locally before the network round-trip.
        """
        if deployment is None:
            validate_deployment(
                name=name,
                model=model,
                system_prompt=system_prompt,
                tools=tools,
                forbidden_topics=forbidden_topics,
            )
            deployment = Deployment(
                name=name,  # type: ignore[arg-type]
                model=model,  # type: ignore[arg-type]
                system_prompt=system_prompt,
                tools=tools or [],
                forbidden_topics=forbidden_topics or [],
                provider=provider,
            )
        else:
            validate_deployment(
                name=deployment.name,
                model=deployment.model,
                system_prompt=deployment.system_prompt,
                tools=deployment.tools,
                forbidden_topics=deployment.forbidden_topics,
            )
        data = self._r._request("POST", "/v1/deployments", json=deployment.to_create_payload())
        return Deployment.model_validate(data)

    def get(self, deployment_id: str) -> Deployment:
        data = self._r._request("GET", f"/v1/deployments/{deployment_id}")
        return Deployment.model_validate(data)

    def update(self, deployment: Deployment | str, **changes) -> Deployment:
        """Update a registered deployment.

        ``rogue.update(dep, system_prompt="...")`` patches specific fields; passing a mutated
        :class:`Deployment` with no kwargs sends its current writable fields.
        """
        dep_id = deployment.id if isinstance(deployment, Deployment) else deployment
        if not dep_id:
            raise ValidationError("deployment must be registered (have an id) before updating.")
        if changes:
            body = changes
        elif isinstance(deployment, Deployment):
            body = deployment.to_create_payload()
        else:
            raise ValidationError("nothing to update: pass field=value changes.")
        data = self._r._request("PATCH", f"/v1/deployments/{dep_id}", json=body)
        return Deployment.model_validate(data)

    def list(self, *, limit: int = 50) -> list[Deployment]:
        data = self._r._request("GET", "/v1/deployments", params={"limit": limit})
        return [Deployment.model_validate(d) for d in data.get("deployments", [])]

    def delete(self, deployment: Deployment | str) -> None:
        dep_id = deployment.id if isinstance(deployment, Deployment) else deployment
        if not dep_id:
            raise ValidationError("deployment must be registered (have an id) before deleting.")
        self._r._request("DELETE", f"/v1/deployments/{dep_id}")


__all__ = ["DeploymentsClient"]
