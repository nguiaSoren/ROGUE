"""AI Red-Team Assurance Report — the customer-facing posture artifact.

What this is
------------
A single coherent report a customer hands to THEIR auditors to demonstrate their
AI security posture. It is a PURE COMPOSITION over artifacts ROGUE already
produces — it introduces no new primitives and runs no pipeline:

* **Scope & posture** — what DeploymentConfig was tested (model × system_prompt ×
  tools), over what window, how many attacks reproduced, breach counts by
  severity and by judge verdict. Supplied by the caller (a threat-brief summary
  or breach-result rollup); this module never queries the DB.
* **Framework coverage** — the credibility centrepiece. The set of attack
  families in scope is run through ``rogue.taxonomy.crosswalk_for_families`` to
  surface which OWASP LLM Top 10 / MITRE ATLAS / NIST AI RMF items the red-team
  actually exercised. Honest by construction: the crosswalk only emits verified,
  currently-existing IDs (see ``rogue.taxonomy.crosswalk``).
* **Evidence / attestation** — the report REFERENCES the latest signed pool
  attestation (its hash, signature, sequence, ``corpus_as_of``) so the posture
  claim is verifiable, not merely asserted. It never re-signs and never rebuilds
  the chain; it embeds a pointer at an entry the attestation engine already
  sealed (``rogue.memory.attestation`` / ``rogue.attestation``).

Honest framing (ROGUE hard rule — every claim traces to something true)
-----------------------------------------------------------------------
This is **red-team evidence, not a certification.** The rendered report carries
an explicit non-certification disclaimer: it is threat-informed assurance tested
against the open-web corpus as of a date, NOT a SOC 2 / ISO 27001 / FedRAMP
accreditation, and ROGUE asserts no accreditation it does not hold. The
disclaimer is non-negotiable and always rendered (see ``NON_CERTIFICATION``).

Position relative to the existing report modules
------------------------------------------------
Lives in ``rogue.governance`` alongside ``governance.report`` (the per-rule
breach report) and mirrors its idioms: pure ``build_* → render_markdown /
render_json`` shape, frozen input dataclasses, no DB/network in the render path.
It composes — never duplicates — ``rogue.diff.threat_brief`` (breach rollups)
and the crosswalk; it consumes the attestation payload rather than producing it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from rogue.schemas import AttackFamily, Severity
from rogue.taxonomy import (
    FrameworkMapping,
    crosswalk_for_families,
    format_frameworks_line,
)
from rogue.taxonomy.crosswalk import OWASP_2025_TITLES, frameworks_to_dict

# --------------------------------------------------------------------------- #
# Non-negotiable framing — red-team evidence, NOT a certification.
# --------------------------------------------------------------------------- #
NON_CERTIFICATION: str = (
    "This is an AI red-team **assurance / posture report — it is red-team evidence, "
    "NOT a certification.** It records what was MEASURED by reproducing known "
    "adversarial prompts against the deployment under test, anchored to the open-web "
    "corpus as of the stated date and continuously re-verified. It is **not** a SOC 2, "
    "ISO 27001, FedRAMP, or any other accreditation, and it does not assert any "
    "accreditation, audit opinion, or safety guarantee that ROGUE does not hold. "
    "Absence of a breach is evidence against the tested corpus, not proof of safety."
)


# --------------------------------------------------------------------------- #
# Input contract — frozen dataclasses the caller fills from already-computed
# data (a threat-brief object, a breach-result rollup, the signed attestation).
# Nothing here touches the DB or the network; the report is a pure render.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AssuranceScope:
    """What was tested, over what window — the DeploymentConfig under assurance.

    All fields default so callers with partial data (e.g. no tool list) still
    render a coherent report. ``window_start``/``window_end`` bound the assurance
    period; either may be ``None`` when the caller only knows a point-in-time.
    """

    config_id: str = ""
    config_name: str = ""
    target_model: str = ""
    system_prompt_label: str = ""
    tools: tuple[str, ...] = ()
    customer_id: str = ""
    window_start: Optional[date] = None
    window_end: Optional[date] = None


@dataclass(frozen=True)
class PostureSummary:
    """The measured red-team posture: how much was tested, what breached.

    ``n_primitives`` / ``n_trials`` are the breadth of the exercise; the
    breakdown maps are the outcome. ``by_severity`` is keyed on :class:`Severity`
    (breaching primitives per tier); ``by_verdict`` is keyed on the judge-verdict
    value string (trials per verdict); ``by_exfil_method`` is keyed on the
    :class:`rogue.schemas.ExfiltrationMethod` value string (count of breaching
    trials that egressed through that channel). All three are plain copies the
    caller computed from the brief / breach rollup — this module sums them, never
    recomputes a rate. ``corpus_as_of`` is the assurance anchor date (string, as
    carried on the attestation), kept honest and explicit.
    """

    n_primitives: int = 0
    n_trials: int = 0
    by_severity: Mapping[Severity, int] = field(default_factory=dict)
    by_verdict: Mapping[str, int] = field(default_factory=dict)
    by_exfil_method: Mapping[str, int] = field(default_factory=dict)
    corpus_as_of: str = ""

    @property
    def n_breaching_primitives(self) -> int:
        """Total primitives that breached at least one config, across all tiers."""
        return sum(self.by_severity.values())


@dataclass(frozen=True)
class AttestationRef:
    """A verifiable pointer at an ALREADY-SIGNED attestation entry — evidence, not a re-sign.

    Built from a sealed attestation entry (``rogue.memory.attestation`` /
    ``rogue.attestation``): the per-org chain ``entry_hash``, its ``signature``,
    monotonic ``seq``, and the entry's ``corpus_as_of`` + framing line. The report
    embeds these so an auditor can re-resolve the entry against the chain. None of
    it is recomputed here.
    """

    entry_hash: str = ""
    signature: str = ""
    seq: Optional[int] = None
    corpus_as_of: str = ""
    framing: str = ""
    org_id: str = ""

    @classmethod
    def from_entry(cls, entry: Any) -> "AttestationRef":
        """Build a ref from a sealed attestation entry (object or dict).

        Reads the standard fields off either an ``AttestationEntry``-like object
        or a plain dict; ``corpus_as_of`` / ``framing`` are pulled from the entry
        payload when present (that is where the attestation builder stores them).
        Missing fields default empty — the ref degrades, it never raises.
        """

        def _get(obj: Any, key: str, default: Any = "") -> Any:
            if isinstance(obj, Mapping):
                return obj.get(key, default)
            return getattr(obj, key, default)

        payload = _get(entry, "payload", {}) or {}
        return cls(
            entry_hash=str(_get(entry, "entry_hash", "") or ""),
            signature=str(_get(entry, "signature", "") or ""),
            seq=_get(entry, "seq", None),
            corpus_as_of=str(_get(payload, "corpus_as_of", "") or ""),
            framing=str(_get(payload, "framing", "") or ""),
            org_id=str(_get(entry, "org_id", "") or ""),
        )


@dataclass(frozen=True)
class AssuranceReport:
    """The assembled, render-ready assurance artifact.

    The product of :func:`build_assurance_report`: scope + posture + the unioned
    framework coverage over the families in scope + an optional attestation ref.
    Pure data — render it with :func:`render_markdown` / :func:`render_json`.
    """

    scope: AssuranceScope
    posture: PostureSummary
    families: tuple[AttackFamily, ...]
    coverage: FrameworkMapping
    attestation: Optional[AttestationRef] = None
    threat_brief_ref: str = ""


# --------------------------------------------------------------------------- #
# Builder — pure composition over already-computed inputs.
# --------------------------------------------------------------------------- #


def build_assurance_report(
    scope: AssuranceScope,
    posture: PostureSummary,
    families: Sequence[AttackFamily | str],
    *,
    attestation: Optional[AttestationRef] = None,
    threat_brief_ref: str = "",
) -> AssuranceReport:
    """Compose an :class:`AssuranceReport` from already-computed inputs.

    ``families`` is the set of attack families that appeared in the report's
    scope (enum or DB-string); their framework coverage is computed via
    ``crosswalk_for_families`` — the single source of OWASP/ATLAS/NIST coverage,
    deduped and order-stable. Unknown family strings are skipped by the crosswalk
    and dropped from the report's family list (honest: only families we can map
    are claimed). ``attestation`` is an optional pointer at a sealed attestation
    entry referenced as evidence; ``threat_brief_ref`` is an optional link/path
    to the underlying threat brief. No DB, no network, no re-signing.
    """
    coverage = crosswalk_for_families(list(families))

    # Keep only the families we could actually resolve to the frozen taxonomy, so
    # the report never names a family it cannot crosswalk. Order-stable, deduped.
    resolved: list[AttackFamily] = []
    for f in families:
        fam = f if isinstance(f, AttackFamily) else _coerce_family(f)
        if fam is not None and fam not in resolved:
            resolved.append(fam)

    return AssuranceReport(
        scope=scope,
        posture=posture,
        families=tuple(resolved),
        coverage=coverage,
        attestation=attestation,
        threat_brief_ref=threat_brief_ref,
    )


def _coerce_family(value: str) -> Optional[AttackFamily]:
    try:
        return AttackFamily(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Render — markdown (for humans / auditors).
# --------------------------------------------------------------------------- #


def render_markdown(report: AssuranceReport) -> str:
    """Render the assurance report as auditor-facing markdown.

    Layout::

        # AI Red-Team Assurance Report
        > non-certification disclaimer (always present)
        ## Scope & Posture
        ## Framework Coverage   (OWASP / ATLAS / NIST — the centrepiece)
        ## Evidence & Attestation
        ## Limitations & Framing

    The non-certification disclaimer and the framework-coverage section are
    always emitted; an empty-scope report renders all sections with explicit
    "none in scope" lines rather than dropping them (an auditor reads structure).
    """
    s = report.scope
    p = report.posture
    lines: list[str] = []

    lines.append("# AI Red-Team Assurance Report")
    lines.append("")
    lines.append(f"> {NON_CERTIFICATION}")
    lines.append("")

    # --- Scope & posture -------------------------------------------------- #
    lines.append("## Scope & Posture")
    lines.append("")
    lines.append(f"- **Customer:** `{s.customer_id or '—'}`")
    lines.append(
        f"- **Deployment under test:** "
        f"{s.config_name or '—'} (`{s.config_id or '—'}`)"
    )
    lines.append(f"- **Target model:** `{s.target_model or '—'}`")
    lines.append(f"- **System prompt:** {s.system_prompt_label or '—'}")
    tools_str = ", ".join(f"`{t}`" for t in s.tools) if s.tools else "none"
    lines.append(f"- **Tools in scope:** {tools_str}")
    lines.append(f"- **Assurance window:** {_window_str(s.window_start, s.window_end)}")
    lines.append(f"- **Corpus as of:** {p.corpus_as_of or '—'}")
    lines.append("")
    lines.append(
        f"- **Attacks reproduced:** {p.n_primitives} primitives "
        f"over {p.n_trials} trials"
    )
    lines.append(
        f"- **Breaching primitives:** {p.n_breaching_primitives}"
    )
    lines.append("")
    lines.append("Breaches by severity:")
    for tier in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW):
        lines.append(f"- **{tier.value.upper()}:** {p.by_severity.get(tier, 0)}")
    if p.by_verdict:
        lines.append("")
        lines.append("Trials by judge verdict:")
        for verdict in sorted(p.by_verdict):
            lines.append(f"- `{verdict}`: {p.by_verdict[verdict]}")
    lines.append("")
    lines.append("Breaches by exfiltration channel:")
    if p.by_exfil_method:
        for method in sorted(p.by_exfil_method):
            lines.append(f"- `{method}`: {p.by_exfil_method[method]}")
    else:
        lines.append(
            "- _No data-exfiltration channel was observed in the breaching trials._"
        )
    lines.append("")

    # --- Framework coverage (the credibility centrepiece) ----------------- #
    lines.append("## Framework Coverage")
    lines.append("")
    if report.families:
        fam_str = ", ".join(f"`{f.value}`" for f in report.families)
        lines.append(
            f"The red-team exercised **{len(report.families)}** attack "
            f"{'family' if len(report.families) == 1 else 'families'} "
            f"in this scope: {fam_str}."
        )
        lines.append("")
        lines.append(
            "These map to the following industry-framework items "
            "(verified IDs only — see the ROGUE taxonomy crosswalk):"
        )
        lines.append("")
        lines.extend(_coverage_lines(report.coverage))
        lines.append("")
        line = format_frameworks_line(report.coverage)
        if line:
            lines.append(f"_Compact tag:_ {line}")
            lines.append("")
    else:
        lines.append(
            "_No attack families were in scope for this report — no framework "
            "coverage is claimed._"
        )
        lines.append("")

    # --- Evidence & attestation ------------------------------------------- #
    lines.append("## Evidence & Attestation")
    lines.append("")
    a = report.attestation
    if a is not None and (a.entry_hash or a.signature):
        lines.append(
            "The posture above is anchored to a signed, append-only attestation "
            "entry (ROGUE's per-organization hash chain). An auditor can re-resolve "
            "it against the chain — this report references it, it does not re-sign it."
        )
        lines.append("")
        if a.org_id:
            lines.append(f"- **Organization:** `{a.org_id}`")
        if a.seq is not None:
            lines.append(f"- **Chain sequence:** {a.seq}")
        if a.entry_hash:
            lines.append(f"- **Entry hash:** `{a.entry_hash}`")
        if a.signature:
            lines.append(f"- **Signature:** `{a.signature}`")
        if a.corpus_as_of:
            lines.append(f"- **Attested corpus as of:** {a.corpus_as_of}")
        if a.framing:
            lines.append(f"- **Attested framing:** {a.framing}")
        lines.append("")
    else:
        lines.append(
            "_No signed attestation is referenced for this report — the posture "
            "above is unattested and should be treated as informational only._"
        )
        lines.append("")
    if report.threat_brief_ref:
        lines.append(f"Underlying threat brief: `{report.threat_brief_ref}`")
        lines.append("")

    # --- Limitations & framing -------------------------------------------- #
    lines.append("## Limitations & Framing")
    lines.append("")
    lines.append(NON_CERTIFICATION)
    lines.append("")

    return "\n".join(lines)


def _coverage_lines(coverage: FrameworkMapping) -> list[str]:
    """Render the per-framework coverage bullets (OWASP titled, ATLAS, NIST)."""
    out: list[str] = []
    if coverage.owasp:
        out.append("- **OWASP LLM Top 10 (2025):**")
        for code in coverage.owasp:
            title = OWASP_2025_TITLES.get(code, "")
            out.append(f"    - {code}{f' — {title}' if title else ''}")
    if coverage.atlas:
        out.append("- **MITRE ATLAS:** " + ", ".join(coverage.atlas))
    if coverage.nist:
        out.append(f"- **NIST AI RMF:** {coverage.nist}")
    if not out:
        out.append("- _No framework signal for the families in scope._")
    return out


def _window_str(start: Optional[date], end: Optional[date]) -> str:
    if start and end:
        return f"{start.isoformat()} → {end.isoformat()}"
    if end:
        return f"as of {end.isoformat()}"
    if start:
        return f"from {start.isoformat()}"
    return "—"


# --------------------------------------------------------------------------- #
# Render — JSON (for the dashboard / API).
# --------------------------------------------------------------------------- #


def render_json(report: AssuranceReport) -> dict[str, Any]:
    """Render the assurance report as a JSON-serializable dict.

    Structurally complete: every section the markdown renders has a key here, so
    the dashboard/API and the human document never diverge. ``frameworks`` reuses
    the crosswalk's ``frameworks_to_dict`` shape (titled OWASP/ATLAS objects);
    ``non_certification`` carries the full disclaimer string so any consumer can
    surface it. Plain Python types throughout — directly ``json.dumps``-able.
    """
    s = report.scope
    p = report.posture
    a = report.attestation

    return {
        "report_type": "ai_red_team_assurance",
        "non_certification": NON_CERTIFICATION,
        "scope": {
            "customer_id": s.customer_id,
            "config_id": s.config_id,
            "config_name": s.config_name,
            "target_model": s.target_model,
            "system_prompt_label": s.system_prompt_label,
            "tools": list(s.tools),
            "window_start": s.window_start.isoformat() if s.window_start else None,
            "window_end": s.window_end.isoformat() if s.window_end else None,
        },
        "posture": {
            "corpus_as_of": p.corpus_as_of,
            "n_primitives": p.n_primitives,
            "n_trials": p.n_trials,
            "n_breaching_primitives": p.n_breaching_primitives,
            "by_severity": {
                tier.value: p.by_severity.get(tier, 0)
                for tier in (
                    Severity.CRITICAL,
                    Severity.HIGH,
                    Severity.MEDIUM,
                    Severity.LOW,
                )
            },
            "by_verdict": dict(p.by_verdict),
            "by_exfil_method": dict(p.by_exfil_method),
        },
        "families": [f.value for f in report.families],
        "frameworks": frameworks_to_dict(report.coverage),
        "frameworks_line": format_frameworks_line(report.coverage),
        "attestation": (
            {
                "org_id": a.org_id,
                "seq": a.seq,
                "entry_hash": a.entry_hash,
                "signature": a.signature,
                "corpus_as_of": a.corpus_as_of,
                "framing": a.framing,
            }
            if a is not None and (a.entry_hash or a.signature)
            else None
        ),
        "threat_brief_ref": report.threat_brief_ref or None,
    }


__all__ = [
    "NON_CERTIFICATION",
    "AssuranceScope",
    "PostureSummary",
    "AttestationRef",
    "AssuranceReport",
    "build_assurance_report",
    "render_markdown",
    "render_json",
]
