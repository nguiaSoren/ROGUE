"""Derive a document's *source date* (when the attack was first disclosed in the
wild) from a harvested RawDocument — the day-level signal that upgrades campaign
metrics (discovery rate, backlog growth, time-to-graduation/implementation).

Resolution, best-available-first:
  1. arXiv "Submitted on DD Mon YYYY" parsed from the page body  → DAY-level.
  2. arXiv id YYMM (from the URL)                                → MONTH-level (1st of month).
  3. a date in the plugin-supplied RawDocument.metadata          → whatever the plugin had.
  4. None — never fabricate (callers leave claimed_first_seen NULL rather than lie;
     `fetched_at` is the harvest time, not the source date, so it is NOT used as a
     fallback — that would silently label every technique "today").

This is a pure function (no clock, no network) so it stays deterministic and testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rogue.schemas import RawDocument

# arXiv abstract/HTML dateline, e.g. "[Submitted on 3 Jun 2026]" or
# "Submitted on 14 May 2026 (v1), last revised ...". Day + month-name + year.
_SUBMITTED = re.compile(
    r"submitted on\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", re.IGNORECASE
)
# arXiv id YYMM.NNNNN anywhere in the URL → year-month.
_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{2})(\d{2})\.\d{4,5}", re.I)
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 0)}
_METADATA_DATE_KEYS = ("published", "published_at", "created", "created_at",
                       "created_utc", "date", "post_date", "timestamp", "pushed_at")


def _parse_metadata_date(meta: dict | None) -> datetime | None:
    if not isinstance(meta, dict):
        return None
    for k in _METADATA_DATE_KEYS:
        v = meta.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, (int, float)):  # unix epoch (e.g. reddit created_utc)
                return datetime.fromtimestamp(float(v), tz=timezone.utc)
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (ValueError, OSError):
            continue
    return None


def derive_source_date(doc: "RawDocument") -> tuple[datetime | None, str]:
    """Return ``(source_date, precision)`` where precision ∈ {"day", "month",
    "metadata", "none"} — so callers can record HOW precise the date is."""
    body = doc.raw_content or ""
    url = str(doc.url)

    # 1. arXiv day-level submission date from the body.
    m = _SUBMITTED.search(body)
    if m:
        day, mon, year = int(m.group(1)), _MONTHS.get(m.group(2)[:3].lower()), int(m.group(3))
        if mon and 1 <= day <= 31 and 2000 <= year <= 2100:
            try:
                return datetime(year, mon, day, tzinfo=timezone.utc), "day"
            except ValueError:
                pass

    # 2. plugin metadata date (reddit/github/blog often carry the real post date).
    md = _parse_metadata_date(doc.metadata)
    if md is not None:
        return md, "metadata"

    # 3. arXiv id → month-level (1st of month).
    a = _ARXIV_ID.search(url)
    if a:
        yy, mm = int(a.group(1)), int(a.group(2))
        if 1 <= mm <= 12:
            return datetime(2000 + yy, mm, 1, tzinfo=timezone.utc), "month"

    return None, "none"
