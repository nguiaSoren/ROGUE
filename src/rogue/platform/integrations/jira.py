"""Jira destination — opens (and converges on) a tracked ticket per critical finding.

Lifecycle (idempotent by design, so re-scans don't spam the board):

  * CREATE  — on a scan event, for each finding whose severity is ``critical`` we compute a stable
              ``finding_id = sha256(org|target|family|vector)``. If no open ticket carries that id,
              we create one (title / severity / remediation) and stamp the id into a label so the
              next scan can find it.
  * DEDUP   — a re-scan that reproduces the same critical finding yields the same ``finding_id``;
              the matching open ticket already exists, so we no-op (optionally drop a comment). Two
              identical findings therefore converge to exactly one ticket.
  * AUTO-CLOSE — a finding that was critical and is no longer present (or dropped below critical) on
              a later scan has its open ticket transitioned to Done. Implemented here as a documented
              hook (``auto_close``) the platform calls with the set of currently-critical ids; the
              live Jira transition is delegated to the injected client.

The Jira client is injected so tests drive create/dedup/auto-close with an in-memory fake — no HTTP.
Like every destination, ``notify`` never raises; remote errors are logged and swallowed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Protocol, runtime_checkable

from rogue.platform.integrations.dispatcher import ScanCompletedEvent

logger = logging.getLogger(__name__)

CRITICAL = "critical"


def finding_id(org_id: str, target: str, family: str, vector: str) -> str:
    """Stable identity for a finding across re-scans.

    ``sha256(org|target|family|vector)`` — deterministic and collision-resistant, so the same
    vulnerability on the same target always maps to the same Jira ticket regardless of when it is
    re-discovered. The pipe-joined fields can't be confused with each other (no field contains a raw
    pipe in practice; this is an id, not a parser, so a defensive escape isn't required).
    """
    raw = f"{org_id}|{target}|{family}|{vector}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class JiraTicket:
    """The ticket payload ROGUE asks Jira to create — risk framing, not a raw exploit dump."""

    finding_id: str
    title: str
    severity: str
    remediation: str


@runtime_checkable
class JiraClient(Protocol):
    """The minimal Jira surface a ``JiraDestination`` needs; the real impl wraps the REST API.

    All methods are async to compose with the dispatcher's concurrent fan-out. ``find_open`` returns
    a truthy issue key/handle when an OPEN ticket already carries ``fid`` (matched via its label),
    else ``None`` — that's the dedup pivot.
    """

    async def find_open(self, fid: str) -> str | None: ...

    async def create(self, ticket: JiraTicket) -> str: ...

    async def close(self, issue_key: str) -> None: ...

    async def list_open(self) -> dict[str, str]:
        """Map of ``finding_id -> issue_key`` for all currently-open ROGUE tickets (auto-close)."""
        ...


@dataclass(frozen=True)
class FindingInput:
    """A finding projected for ticketing — family/vector drive the id; severity gates creation."""

    family: str
    vector: str
    severity: str
    title: str
    remediation: str = ""


# A pluggable "give me this event's findings" callable. Injected so production reads from the report
# store while tests pass a fixture list; defaults to "no findings" in the destination's constructor.
FindingsResolver = Callable[[ScanCompletedEvent], "list[FindingInput]"]


class JiraDestination:
    """Creates/converges Jira tickets for the critical findings of a scan."""

    name = "jira"

    def __init__(
        self,
        client: JiraClient,
        *,
        findings_for: "FindingsResolver | None" = None,
    ) -> None:
        self._client = client
        # How the destination obtains the scan's findings. Injected so it can read from the platform
        # report store in production and from a fixture in tests. Defaults to "no findings" — a bare
        # event carries only aggregates, not the per-finding breakdown ticketing needs.
        self._findings_for = findings_for or (lambda _event: [])

    async def notify(self, event: ScanCompletedEvent) -> None:
        """Open a ticket for each NEW critical finding; dedup converges re-scans. Never raises."""
        try:
            findings = self._findings_for(event)
            for f in findings:
                if (f.severity or "").lower() != CRITICAL:
                    continue
                fid = finding_id(event.org_id, event.target, f.family, f.vector)
                existing = await self._client.find_open(fid)
                if existing:
                    # Dedup: the same vulnerability is already tracked — converge, don't duplicate.
                    logger.info("jira: finding %s already open as %s — skipping create", fid, existing)
                    continue
                ticket = JiraTicket(
                    finding_id=fid,
                    title=f"[ROGUE][CRITICAL] {f.title} ({f.family}/{f.vector})",
                    severity=f.severity,
                    remediation=f.remediation or "See the ROGUE scan report for reproduction and remediation.",
                )
                issue_key = await self._client.create(ticket)
                logger.info("jira: created %s for finding %s", issue_key, fid)
        except Exception as exc:  # noqa: BLE001 - a Jira outage must never break dispatch
            logger.warning("jira: notify failed for scan %s (%s) — scan result still recorded", event.scan_id, exc)

    async def auto_close(self, current_critical_ids: Iterable[str]) -> None:
        """Close any open ROGUE ticket whose finding is no longer critical in the latest scan.

        The platform passes the set of ``finding_id``s that are critical *right now*; every open
        ticket not in that set is a resolved finding and gets transitioned to Done. Best-effort.
        """
        current = set(current_critical_ids)
        try:
            for fid, issue_key in (await self._client.list_open()).items():
                if fid not in current:
                    await self._client.close(issue_key)
                    logger.info("jira: auto-closed %s (finding %s no longer critical)", issue_key, fid)
        except Exception as exc:  # noqa: BLE001 - auto-close is best-effort
            logger.warning("jira: auto-close pass failed (%s)", exc)


__all__ = [
    "JiraDestination",
    "JiraTicket",
    "JiraClient",
    "FindingInput",
    "FindingsResolver",
    "finding_id",
]
