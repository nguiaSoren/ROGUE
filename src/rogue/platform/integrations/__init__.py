"""Outbound integrations — fan-out of scan-completed events to per-org destinations.

ROGUE finishes a scan and the result needs to reach the places a security team already lives:
Slack (an at-a-glance notification), Jira (a tracked, deduplicated ticket per critical finding),
and CI (the GitHub Action under ``.github/actions/rogue-scan/`` gates a pull request on score).

The shape is a single event → many destinations: the platform builds one ``ScanCompletedEvent``
from a persisted ``ScanRecord`` and hands it to an ``IntegrationDispatcher`` that has the org's
enabled destinations registered. Each destination is best-effort — a Slack outage or a Jira 500
logs a WARNING and is swallowed, never raising, exactly as ``threat_brief._maybe_post_to_slack``
does for the daily brief. One failing destination must not starve the others.

Destinations take an injectable async ``sender`` (Slack) or ``client`` (Jira) so tests exercise the
payload-building and dedup logic with zero real HTTP. The real default is a lazy ``httpx`` POST.
"""

from __future__ import annotations

from .dispatcher import (
    Destination,
    IntegrationDispatcher,
    ScanCompletedEvent,
)
from .jira import JiraDestination, JiraTicket, finding_id
from .slack import SlackDestination

__all__ = [
    "ScanCompletedEvent",
    "Destination",
    "IntegrationDispatcher",
    "SlackDestination",
    "JiraDestination",
    "JiraTicket",
    "finding_id",
]
