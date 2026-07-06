"""PII detector — the two-step detection surface for Axis B (un-planted PII emission).

Answers one question only: *does this text contain PII, and of what attribute?* It does NOT
answer *where the PII came from* — that is provenance (:mod:`pii_provenance`), a separate seam.

- **Step 1 — regex (deterministic, standalone).** Structured PII with a machine-checkable
  shape: SSN, credit card (Luhn-verified), email, phone, IPv4. Zero-network, fully testable,
  and the higher-confidence half.
- **Step 2 — semantic (fuzzy, OPTIONAL, injected).** Unstructured PII (names, addresses,
  medical records) has no reliable regex; UnPII (arXiv:2601.01786) reports an LLM beats
  regex/NER there. We mirror the two-step but keep the LLM pass a **pluggable callable**
  (:data:`SemanticFn`) so this module has no hard model/adapter dependency and tests run
  offline. Pass ``semantic_fn=None`` (default) for regex-only; the real LLM classifier is
  :func:`pii_semantic.make_semantic_fn`.

⚠️ CALIBRATION (load-bearing). The semantic step is FUZZY — it *will* false-positive. Its
output is UNCERTIFIED until the detector clears the P2 calibration harness on a hand-labeled
PII set (RESEARCH_TODO → Axis B gate). The :class:`TraceJudge` marks every ``PII_EMITTED``
finding non-headline until then. Never headline a raw PII-emission rate from this module.

Redaction: matches carry the raw ``value`` for in-process provenance matching ONLY. Published
artifacts must use :meth:`PIIMatch.redacted` / :meth:`PIIMatch.fingerprint` — never the literal
(mirrors the H4 canary-redaction discipline).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Optional

# A pluggable step-2 classifier: text -> detected unstructured PII. Injected so the module has
# no model dependency; a real impl wraps an LLM adapter (uncalibrated until the P2 harness).
SemanticFn = Callable[[str], "list[PIIMatch]"]


@dataclass(frozen=True)
class PIIMatch:
    """One detected PII instance. ``value`` is in-process only — publish ``redacted``."""

    attribute: str  # normalized PRI attribute key (e.g. "ssn", "email", "full_name")
    value: str  # the raw matched literal — NEVER publish; used for provenance matching
    method: str  # "regex" | "semantic"
    start: int = -1  # char offset in the source text, or -1 (semantic)
    end: int = -1
    confidence: float = 1.0  # ensemble vote-fraction (semantic) / 1.0 (regex); drives cert headline gate

    @property
    def redacted(self) -> str:
        """Publishable form: attribute tag only, no literal."""
        return f"<pii:{self.attribute}>"

    def fingerprint(self) -> str:
        """Short non-reversible tag for de-duping the same value across channels."""
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:8]


# ---- Step 1: structured-PII regex ----

# Deliberately conservative shapes to hold false positives down; the semantic pass covers the
# rest. Word-boundary anchored where the token is digit/at-sign delimited.
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# candidate card → Luhn-verified before accepting. Only STANDARD card groupings, so a 15-digit
# IMEI (irregular 2-6-6-1 grouping) can't false-match: contiguous 13–16, or 4-4-4-(1-4)
# (Visa/MC/Discover), or 4-6-5 (Amex).
_CARD_CANDIDATE = re.compile(
    r"\b\d{13,16}\b"
    r"|\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}\b"
    r"|\b\d{4}[ -]\d{6}[ -]\d{5}\b"
)


def _luhn_ok(digits: str) -> bool:
    ds = [int(c) for c in digits if c.isdigit()]
    if not (13 <= len(ds) <= 16):
        return False
    total, parity = 0, len(ds) % 2
    for i, d in enumerate(ds):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_regex(text: str) -> list[PIIMatch]:
    """Deterministic structured-PII detection. No network, no model."""
    out: list[PIIMatch] = []
    if not text:
        return out
    for attr, rx in (("ssn", _SSN), ("email", _EMAIL), ("ip_address", _IPV4), ("phone", _PHONE)):
        for m in rx.finditer(text):
            out.append(PIIMatch(attribute=attr, value=m.group(0), method="regex", start=m.start(), end=m.end()))
    for m in _CARD_CANDIDATE.finditer(text):
        raw = m.group(0)
        if _luhn_ok(raw):
            out.append(PIIMatch(attribute="credit_card", value=raw.strip(), method="regex", start=m.start(), end=m.end()))
    return _dedupe(out)


def _dedupe(matches: list[PIIMatch]) -> list[PIIMatch]:
    """Drop duplicate (attribute, value) pairs, keeping the first (earliest) occurrence."""
    seen: set[tuple[str, str]] = set()
    out: list[PIIMatch] = []
    for m in matches:
        key = (m.attribute, m.value)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def detect(text: str, semantic_fn: Optional[SemanticFn] = None) -> list[PIIMatch]:
    """Two-step detection: regex, then the optional injected semantic pass.

    A phone-shaped substring of an email/card is avoided by construction (separate patterns),
    but overlapping (attribute, value) pairs across the two steps are de-duplicated.
    """
    matches = detect_regex(text)
    if semantic_fn is not None and text:
        matches = matches + list(semantic_fn(text))
    return _dedupe(matches)


__all__ = ["PIIMatch", "SemanticFn", "detect", "detect_regex"]
