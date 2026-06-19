"""The common event + fan-out core every integration shares.

A scan completes → the platform builds one ``ScanCompletedEvent`` (a flat, serialization-safe
projection of the persisted ``ScanRecord``) → an ``IntegrationDispatcher`` fans it out to every
destination the org has enabled. Destinations conform to the ``Destination`` protocol (a single
``async notify(event)``); the dispatcher calls each one best-effort, logging and swallowing any
exception so a single broken destination never blocks the rest or bubbles up into the scan worker.

This mirrors ``rogue.diff.threat_brief._maybe_post_to_slack``'s posture (network failure → WARNING,
never raise) but generalizes it from one hard-coded webhook to N per-tenant destinations.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rogue.platform.schemas import ScanRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanCompletedEvent:
    """A flat, immutable snapshot of a finished scan — the one payload every destination consumes.

    Built from a ``ScanRecord`` via :meth:`from_record`; deliberately a small projection (no raw
    target secret, no full report body) so it is cheap to pass around and safe to serialize.
    """

    scan_id: str
    org_id: str
    target: str
    score: float
    n_breaches: int
    n_tests: int
    top_attack: str | None
    status: str
    report_url: str | None = None

    @classmethod
    def from_record(
        cls,
        record: ScanRecord,
        *,
        report_url: str | None = None,
    ) -> ScanCompletedEvent:
        """Project a persisted ``ScanRecord`` into the fan-out event.

        ``target`` is taken from the record's redacted target snapshot (provider/model/endpoint),
        falling back to the org id so the event always has a human-readable subject. ``score``
        defaults to 0.0 when a scan failed before scoring. ``status`` is normalized to its string
        value whether the record carries an enum or a raw string.
        """
        target_snapshot = record.target or {}
        target = (
            target_snapshot.get("model")
            or target_snapshot.get("provider")
            or target_snapshot.get("endpoint")
            or record.org_id
        )
        status = getattr(record.status, "value", record.status)
        return cls(
            scan_id=record.scan_id,
            org_id=record.org_id,
            target=str(target),
            score=float(record.score) if record.score is not None else 0.0,
            n_breaches=record.n_breaches,
            n_tests=record.n_tests,
            top_attack=record.top_attack,
            status=str(status),
            report_url=report_url,
        )


@runtime_checkable
class Destination(Protocol):
    """One outbound integration. ``name`` identifies it in logs; ``notify`` delivers the event.

    Implementations MUST NOT raise from ``notify`` for transient/remote failures — they should log
    and swallow. The dispatcher also wraps every call defensively as a second line of defense.
    """

    name: str

    async def notify(self, event: ScanCompletedEvent) -> None: ...


class IntegrationDispatcher:
    """Holds an org's enabled destinations and fans a single event out to all of them.

    ``dispatch`` runs every destination concurrently and waits for all to settle. Each call is
    isolated: an exception (or a destination that forgot to swallow its own) is caught here, logged
    at WARNING, and does not affect the others — the dispatch as a whole always completes normally.
    """

    def __init__(self, destinations: list[Destination] | None = None) -> None:
        self._destinations: list[Destination] = list(destinations or [])

    def register(self, destination: Destination) -> None:
        """Enable a destination for this org."""
        self._destinations.append(destination)

    @property
    def destinations(self) -> list[Destination]:
        return list(self._destinations)

    async def dispatch(self, event: ScanCompletedEvent) -> None:
        """Fan ``event`` out to every registered destination, best-effort and concurrently."""
        if not self._destinations:
            logger.debug("dispatch: no destinations registered for scan %s", event.scan_id)
            return

        async def _safe(dest: Destination) -> None:
            # Per-destination isolation: a broken Slack hook or Jira 500 must not starve siblings
            # nor propagate into the scan worker. Mirrors threat_brief's "log + swallow" posture.
            try:
                await dest.notify(event)
            except Exception as exc:  # noqa: BLE001 - one destination must never break dispatch
                logger.warning(
                    "integration %r failed for scan %s (%s) — other destinations unaffected",
                    getattr(dest, "name", dest.__class__.__name__),
                    event.scan_id,
                    exc,
                )

        await asyncio.gather(*(_safe(dest) for dest in self._destinations))


__all__ = ["ScanCompletedEvent", "Destination", "IntegrationDispatcher"]
