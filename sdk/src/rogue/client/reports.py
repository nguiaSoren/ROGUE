"""Report retrieval (Deliverable 6). Reports are produced by completed scans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models.report import Report
from ..models.scan import Scan

if TYPE_CHECKING:
    from .rogue import Rogue


class ReportsClient:
    """Reachable as ``rogue.reports``."""

    def __init__(self, rogue: Rogue):
        self._r = rogue

    def get(self, report_id: str) -> Report:
        data = self._r._request("GET", f"/v1/reports/{report_id}")
        return Report.model_validate(data)

    def for_scan(self, scan: Scan | str) -> Report:
        """Fetch the report belonging to a (completed) scan."""
        return self._r.scans.report_for(scan)


__all__ = ["ReportsClient"]
