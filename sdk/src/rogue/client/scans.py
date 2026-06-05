"""Scan API (Deliverable 5): start a red-team job, poll it, fetch its report.

A scan is a server-side async job. :meth:`start` returns immediately with a :class:`Scan` handle;
the blocking ``rogue.scan(...)`` convenience (on the facade) starts one and waits for the report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..exceptions import ValidationError
from ..models.deployment import Deployment
from ..models.report import Report
from ..models.scan import Scan

if TYPE_CHECKING:
    from .rogue import Rogue


class ScansClient:
    """Reachable as ``rogue.scans``. Each returned :class:`Scan` is bound back to this client."""

    def __init__(self, rogue: Rogue):
        self._r = rogue

    def start(
        self,
        deployment: Deployment | str | None = None,
        *,
        deployment_id: str | None = None,
        n_trials: int = 5,
        options: dict[str, Any] | None = None,
    ) -> Scan:
        """Start a scan job against a deployment. Returns a non-blocking :class:`Scan` handle."""
        dep_id = self._resolve_id(deployment, deployment_id)
        body: dict[str, Any] = {"deployment_id": dep_id, "n_trials": n_trials}
        if options:
            body["options"] = options
        data = self._r._request("POST", "/v1/scans", json=body)
        return Scan.model_validate(data)._bind(self)

    def get(self, scan_id: str) -> Scan:
        data = self._r._request("GET", f"/v1/scans/{scan_id}")
        return Scan.model_validate(data)._bind(self)

    def list(self, *, deployment_id: str | None = None, limit: int = 50) -> list[Scan]:
        params: dict[str, Any] = {"limit": limit}
        if deployment_id:
            params["deployment_id"] = deployment_id
        data = self._r._request("GET", "/v1/scans", params=params)
        return [Scan.model_validate(s)._bind(self) for s in data.get("scans", [])]

    def cancel(self, scan_id: str) -> Scan:
        data = self._r._request("POST", f"/v1/scans/{scan_id}/cancel")
        return Scan.model_validate(data)._bind(self)

    def report_for(self, scan: Scan | str) -> Report:
        sid = scan.id if isinstance(scan, Scan) else scan
        data = self._r._request("GET", f"/v1/scans/{sid}/report")
        return Report.model_validate(data)

    @staticmethod
    def _resolve_id(deployment: Deployment | str | None, deployment_id: str | None) -> str:
        if deployment_id:
            return deployment_id
        if isinstance(deployment, Deployment):
            if not deployment.id:
                raise ValidationError(
                    "deployment is not registered; call rogue.register(...) first.",
                    field="deployment",
                )
            return deployment.id
        if isinstance(deployment, str) and deployment:
            return deployment
        raise ValidationError(
            "provide a registered Deployment or deployment_id to scan.", field="deployment"
        )


__all__ = ["ScansClient"]
