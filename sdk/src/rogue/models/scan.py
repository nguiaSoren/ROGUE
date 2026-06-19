"""The :class:`Scan` — a server-side red-team job against one deployment.

A scan runs ROGUE's attack repertoire against a deployment. It takes minutes to tens of minutes
and costs real LLM spend, so it is a **server-side async job**: you start it and poll. ``Scan`` is a
data model, but the owning client injects itself (private attr) so a job reads ergonomically::

    job = rogue.scan_async(deployment)
    job.wait()                 # blocks until terminal
    report = job.report()
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, PrivateAttr

from ..exceptions import ScanFailedError, ScanTimeoutError
from .common import ScanStatus

if TYPE_CHECKING:  # avoid a runtime import cycle (client imports models)
    from .report import Report


class Scan(BaseModel):
    """Status handle for a red-team job. Poll with :meth:`refresh` or block with :meth:`wait`."""

    id: str
    deployment_id: str
    status: ScanStatus
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    n_attacks: int | None = None
    n_completed: int | None = None
    report_id: str | None = None
    error: str | None = None

    _client: Any = PrivateAttr(default=None)

    def _bind(self, client: Any) -> Scan:
        """Attach the owning ScansClient so .refresh()/.wait()/.report() work. Internal."""
        self._client = client
        return self

    # --- lifecycle helpers --------------------------------------------------------------------

    @property
    def done(self) -> bool:
        """True once the job reached a terminal state (completed/failed/canceled)."""
        return self.status.is_terminal

    @property
    def succeeded(self) -> bool:
        return self.status == ScanStatus.COMPLETED

    def refresh(self) -> Scan:
        """Re-fetch this scan's current state from the API and update in place. Returns self."""
        self._require_client("refresh")
        fresh = self._client.get(self.id)
        for name in self.__class__.model_fields:
            object.__setattr__(self, name, getattr(fresh, name))
        return self

    def wait(self, *, timeout: float | None = None, poll_interval: float = 3.0) -> Scan:
        """Block until the scan reaches a terminal state.

        Raises :class:`ScanFailedError` if it ends ``failed``, or :class:`ScanTimeoutError` if
        ``timeout`` (seconds) elapses while still running. Returns self on success.
        """
        self._require_client("wait")
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.done:
            if deadline is not None and time.monotonic() >= deadline:
                raise ScanTimeoutError(
                    f"scan {self.id} still {self.status.value} after {timeout}s", scan=self
                )
            time.sleep(max(0.0, poll_interval))
            self.refresh()
        if self.status == ScanStatus.FAILED:
            raise ScanFailedError(self.error or f"scan {self.id} failed", scan=self)
        return self

    def report(self) -> Report:
        """Fetch the report for this (completed) scan.

        Blocks via :meth:`wait` first if the scan is not yet terminal.
        """
        self._require_client("report")
        if not self.done:
            self.wait()
        return self._client.report_for(self)

    def cancel(self) -> Scan:
        """Request cancellation of a running scan."""
        self._require_client("cancel")
        fresh = self._client.cancel(self.id)
        return self.refresh() if fresh is None else self._adopt(fresh)

    def _adopt(self, other: Scan) -> Scan:
        for name in self.__class__.model_fields:
            object.__setattr__(self, name, getattr(other, name))
        return self

    def _require_client(self, op: str) -> None:
        if self._client is None:
            raise RuntimeError(
                f"Scan.{op}() needs an attached client; obtain scans via Rogue, not by hand."
            )

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        pct = f"{round(self.progress * 100)}%"
        return f"Scan {self.id} · {self.status.value} · {pct}"


__all__ = ["Scan"]
