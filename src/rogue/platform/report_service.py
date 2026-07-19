"""`ReportService` impl — render a persisted scan into customer artifacts (JSON / HTML / PDF).

The worker (`worker.py`) finalizes a scan by saving `ScanReport.to_dict()` under a fresh `report_id`
and stamping that id + the platform `score` onto the `ScanRecord`. This service is the read side: it
reconstructs a `rogue.report.ScanReport` from the persisted payload and re-renders it, layering in the
platform `score`/`risk_level` (which the bare SDK `ScanReport` doesn't carry). It owns no scan logic —
just persistence read + presentation.
"""

from __future__ import annotations

import html as _html
import re
from typing import TYPE_CHECKING

import rogue.report as _report
from rogue.report import (
    SCORE_METHODOLOGY,
    Finding,
    ScanReport,
    humanize_technique,
    remediation_section,
    technique_label,
    vector_slug,
)

from . import scoring
from .interfaces import ReportService, ScanStore

if TYPE_CHECKING:
    from rogue.governance.assurance import AssuranceReport, AssuranceScope, AttestationRef
    from rogue.platform.schemas import ScanRecord
    from rogue.report import Finding as _FindingT
    from rogue.schemas.remediation import RemediationResult

# Credential shapes that must never appear in a rendered artifact. The persisted payload should already
# be secret-free (`TargetSpec.api_key` is excluded from the record), but example strings are harvested
# free-text, so we scrub provider key prefixes defensively before they reach a customer-facing page.
_SECRET_RE = re.compile(r"\b(?:sk|rk)[-_][A-Za-z0-9_-]{6,}\b")


def _redact(s: str | None) -> str | None:
    """Mask any leaked provider-key-shaped token in a free-text excerpt; pass `None` through."""
    if s is None:
        return None
    return _SECRET_RE.sub("[REDACTED]", s)


def _coerce_severity(value: str):
    """Map a stored finding-severity string to a `Severity`, or None if unmappable."""
    from rogue.schemas import Severity  # noqa: PLC0415

    try:
        return Severity(value)
    except ValueError:
        return None


def _distinct_families(findings: "list[_FindingT]") -> list[str]:
    """The distinct raw `Finding.family` enum-value strings, in stable first-seen order.

    The assurance builder coerces these to `AttackFamily` and drops any it can't map, so we pass the
    raw stored value (e.g. ``dan_persona``), NOT the humanized `families_covered()` label.
    """
    seen: list[str] = []
    for f in findings:
        if f.family not in seen:
            seen.append(f.family)
    return seen


def _scope_from_record(scan_id: str, record: "ScanRecord | None") -> "AssuranceScope":
    """Build the `AssuranceScope` from the redacted `ScanRecord.target` snapshot.

    A platform scan has no separate DeploymentConfig, so the scan itself is the unit under
    assurance: `scan_id` is the config id, and a `provider/model`-style label is the config name.
    The persisted target carries only a system-prompt LENGTH (the text is never stored), so the
    label reflects presence honestly rather than inventing prompt text. The window is the scan's
    own start→completion timestamps when present.
    """
    from rogue.governance.assurance import AssuranceScope  # noqa: PLC0415

    if record is None:
        return AssuranceScope(config_id=scan_id)

    target = record.target or {}
    provider = target.get("provider") or ""
    model = target.get("model") or ""
    endpoint = target.get("endpoint") or ""
    target_model = model or endpoint or provider
    config_name = "/".join(p for p in (provider or endpoint, model) if p) or scan_id

    sys_prompt_len = target.get("system_prompt_len") or 0
    system_prompt_label = (
        f"custom ({sys_prompt_len} chars)" if sys_prompt_len else "default / none"
    )

    return AssuranceScope(
        config_id=scan_id,
        config_name=config_name,
        target_model=target_model,
        system_prompt_label=system_prompt_label,
        tools=(),  # platform scans carry no tool inventory in the redacted snapshot
        customer_id=record.org_id,
        window_start=(record.started_at.date() if record.started_at else None),
        window_end=(record.completed_at.date() if record.completed_at else None),
    )


def _explanation_for(finding: Finding, finding_dict: dict | None = None) -> str:
    """Plain-language "what this attack class means for you" for an exec/PDF audience.

    Sourced, in priority order: (1) the `explanation` key the SDK's `to_dict()` emits per finding
    (`rogue.report.explain_family`); (2) `rogue.report.explain_family(family)` called directly when we
    hold a `Finding` but not its dict; (3) a built-in family-agnostic fallback so an exec-facing surface
    is never blank if neither upstream source is present. Defensive by design — this module must render a
    complete summary even against an older `rogue.report` that lacks `explain_family`.
    """
    if finding_dict is not None:
        explanation = finding_dict.get("explanation")
        if isinstance(explanation, str) and explanation.strip():
            return explanation.strip()

    explain_family = getattr(_report, "explain_family", None)
    if callable(explain_family):
        try:
            explanation = explain_family(finding.family)
        except Exception:  # pragma: no cover - upstream helper must never break the report
            explanation = None
        if isinstance(explanation, str) and explanation.strip():
            return explanation.strip()

    return (
        f"An attacker can use {technique_label(finding.family).lower()} techniques to push the "
        "assistant past its safety policy, making it produce output it is meant to refuse."
    )


class DefaultReportService(ReportService):
    """Reconstructs the persisted `ScanReport` and renders JSON / HTML / PDF with the platform score."""

    def __init__(self, store: ScanStore):
        self.store = store

    # --- internals ------------------------------------------------------------------------------

    async def _load_report(self, scan_id: str) -> ScanReport:
        """Resolve `scan_id` → its persisted payload → a rebuilt `ScanReport`.

        Raises a clear `ValueError` if the scan is unknown, not completed, or has no stored report.
        """
        record = await self.store.get(scan_id)
        if record is None:
            raise ValueError(f"scan {scan_id!r} not found")
        if record.report_id is None:
            raise ValueError(f"scan {scan_id!r} has no report (status={record.status.value})")

        stored = await self.store.get_report(record.report_id)
        if stored is None:
            raise ValueError(f"report {record.report_id!r} for scan {scan_id!r} is missing")
        # `get_report` returns the report payload dict directly (== ScanReport.to_dict()), per the
        # ScanStore contract — NOT a {"payload": ...} wrapper. (The wrapper assumption silently emptied
        # every Postgres-backed report while the in-memory test passed.)
        payload = stored or {}

        # Rebuild Findings from the persisted dicts, redacting example excerpts on the way in. Only the
        # known Finding fields are carried over, so a forward-compatible payload (extra keys) is tolerated.
        findings: list[Finding] = []
        for raw in payload.get("findings") or []:
            findings.append(
                Finding(
                    family=raw["family"],
                    technique=raw["technique"],
                    vector=raw["vector"],
                    severity=raw["severity"],
                    title=raw["title"],
                    success_rate=raw["success_rate"],
                    n_trials=raw["n_trials"],
                    n_breach=raw["n_breach"],
                    example_attack=_redact(raw.get("example_attack")),
                    example_response=_redact(raw.get("example_response")),
                )
            )

        return ScanReport(
            target=payload.get("target", ""),
            n_tests=payload.get("n_tests", 0),
            n_breaches=payload.get("n_breaches", 0),
            cost_usd=payload.get("cost_usd", 0.0),
            findings=findings,
        )

    # --- renderers ------------------------------------------------------------------------------

    async def build_json(
        self,
        scan_id: str,
        *,
        mitigations: "dict[str, RemediationResult] | None" = None,
    ) -> dict:
        """The SDK report dict + the platform headline (`score` 0-100, its `risk_level`) + a coverage block.

        Additive over `ScanReport.to_dict()` (which already carries per-finding `remediation` and `explanation`): we layer the platform `score`/`risk_level`/`score_methodology` headline, a `coverage` block (n_tests, n_breaches, breach_rate, and the distinct human attack-families exercised), and a top-level `executive_summary` (the markdown narrative from `build_executive_summary`) so the dashboard renders the CISO summary without a second call. Each finding is also guaranteed a non-empty `explanation` — backfilled defensively here if `to_dict()` didn't already emit one — so a programmatic consumer never sees a finding without a plain-language meaning. The underlying SDK shape is untouched (additive only).
        """
        from rogue.taxonomy.crosswalk import (  # noqa: PLC0415 — pure lookup, lazy to keep import light
            crosswalk_for_family,
            format_frameworks_line,
            frameworks_to_dict,
        )

        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        out = report.to_dict(mitigations=mitigations)
        out["score"] = score
        out["risk_level"] = scoring.risk_level(score)
        out["score_methodology"] = SCORE_METHODOLOGY
        # Graded scorecard: per-family ASR → letter grade with a worst-category-dominates headline
        # (Wave-D frontend binds to `scorecard`). Rates + Wilson CIs stay the substance.
        out["scorecard"] = scoring.build_scorecard(report.findings)
        # Coverage: keep the existing keys (n_tests/n_breaches/breach_rate/families_tested) and layer
        # in the probe-coverage matrix (probed vs never-probed across the 15 frozen families).
        coverage = {
            "n_tests": report.n_tests,
            "n_breaches": report.n_breaches,
            "breach_rate": round(report.breach_rate, 4),
            "families_tested": report.families_covered(),
        }
        coverage.update(scoring.build_coverage(report.findings))
        out["coverage"] = coverage
        # Per-finding framework tags (OWASP 2025 / MITRE ATLAS / NIST AI RMF) from the pure crosswalk —
        # additive keys on each finding so an enterprise consumer sees the standard identifiers.
        for f_dict, f in zip(out.get("findings", []), report.findings, strict=False):
            mapping = crosswalk_for_family(f.family, vector_slug(f.vector))
            f_dict["frameworks"] = frameworks_to_dict(mapping)
            f_dict["frameworks_line"] = format_frameworks_line(mapping)
        # Guarantee every finding carries a plain-language `explanation`. `to_dict()` emits one
        # (`explain_family`); where it doesn't (an older `rogue.report`), backfill so the dashboard's
        # per-finding "what this means" never renders blank. `findings`/`report.findings` are positionally aligned.
        for f_dict, f in zip(out.get("findings", []), report.findings, strict=False):
            if not (isinstance(f_dict.get("explanation"), str) and f_dict["explanation"].strip()):
                f_dict["explanation"] = _explanation_for(f, f_dict)
        # Top-level exec summary so the dashboard renders the CISO narrative without a second round-trip.
        out["executive_summary"] = await self.build_executive_summary(
            scan_id, mitigations=mitigations
        )
        return out

    # --- assurance report (the auditor-facing posture artifact) ---------------------------------
    #
    # A PURE COMPOSITION over the same persisted `ScanReport` + `ScanRecord` the JSON/HTML/PDF
    # renderers read — it adds no scan logic and queries nothing the report layer doesn't already
    # own. The cross-org attestation pointer is the ONE thing the report layer can't resolve (it
    # holds the store, not the attestation chain), so the route fetches the sealed entry and passes
    # an `AttestationRef` (or None) in. The honest "unattested" path is `attestation=None`.

    async def _build_assurance(
        self, scan_id: str, *, attestation: "AttestationRef | None" = None
    ) -> "AssuranceReport":
        """Assemble the `AssuranceReport` from the COMPLETED scan's persisted report + record.

        Posture is derived from the persisted findings (the only outcome data a platform scan
        persists): `by_severity` counts breaching primitives per tier; `by_exfil_method` classifies
        each breaching finding's example response through the same deterministic classifier the
        reproduction layer uses (`classify_exfiltration_method`) so the channel breakdown is real
        scan data, never fabricated. `by_verdict` is left empty — a platform `ScanReport` collapses
        per-trial judge verdicts into n_breach/n_trials and does not retain the verdict strings, so
        claiming a verdict split here would be invented; the assurance renderer omits the block when
        it's empty. `families` are the distinct raw `Finding.family` enum-value strings (the builder
        coerces + drops any it can't map). Scope is read off the redacted `ScanRecord.target`.
        """
        from rogue.governance.assurance import (  # noqa: PLC0415
            PostureSummary,
            build_assurance_report,
        )
        from rogue.reproduce.judge import classify_exfiltration_method  # noqa: PLC0415
        from rogue.schemas import Severity  # noqa: PLC0415
        from rogue.schemas.breach_result import JudgeVerdict  # noqa: PLC0415

        record = await self.store.get(scan_id)
        report = await self._load_report(scan_id)

        # Posture — breaching-primitive counts by severity tier, and the exfiltration-channel
        # breakdown classified from each breaching finding's example response.
        by_severity: dict[Severity, int] = {}
        by_exfil_method: dict[str, int] = {}
        for f in report.findings:
            if not f.breached:
                continue
            sev = _coerce_severity(f.severity)
            if sev is not None:
                by_severity[sev] = by_severity.get(sev, 0) + 1
            method = classify_exfiltration_method(
                f.example_response or "", verdict=JudgeVerdict.FULL_BREACH
            )
            if method is not None:
                by_exfil_method[method.value] = by_exfil_method.get(method.value, 0) + 1

        posture = PostureSummary(
            n_primitives=len(report.findings),
            n_trials=sum(f.n_trials for f in report.findings),
            by_severity=by_severity,
            by_verdict={},  # not retained on a platform ScanReport — honest empty, never invented
            by_exfil_method=by_exfil_method,
            corpus_as_of=(attestation.corpus_as_of if attestation else ""),
        )

        families = _distinct_families(report.findings)
        scope = _scope_from_record(scan_id, record)

        return build_assurance_report(
            scope,
            posture,
            families,
            attestation=attestation,
            threat_brief_ref=f"scan:{scan_id}",
        )

    async def build_assurance_json(
        self, scan_id: str, *, attestation: "AttestationRef | None" = None
    ) -> dict:
        """Render the per-scan AI Red-Team Assurance Report as the confirmed JSON contract."""
        from rogue.governance.assurance import render_json  # noqa: PLC0415

        return render_json(await self._build_assurance(scan_id, attestation=attestation))

    async def build_assurance_markdown(
        self, scan_id: str, *, attestation: "AttestationRef | None" = None
    ) -> str:
        """Render the per-scan AI Red-Team Assurance Report as auditor-facing markdown."""
        from rogue.governance.assurance import render_markdown  # noqa: PLC0415

        return render_markdown(await self._build_assurance(scan_id, attestation=attestation))

    async def build_executive_summary(
        self,
        scan_id: str,
        *,
        mitigations: "dict[str, RemediationResult] | None" = None,
    ) -> str:
        """A CISO-ready MARKDOWN exec summary — the artifact a security buyer forwards to their boss.

        Narrative, not a stat dump. Four moves: (1) a one-line **risk-posture verdict** tying the
        0–100 score and its band to a plain recommendation; (2) **Top risks in business terms** — the
        breached critical/high findings, each rendered as "what this means for you" via the family
        explanation (`explain_family`, consumed defensively); (3) a prioritized **"What to do first"**
        list — the remediation for the worst findings, severity-ranked, deduped per family so the same
        fix isn't repeated; (4) a closing **posture** sentence. Reuses the same `_load_report` +
        `scoring` spine as the JSON/HTML/PDF renderers so the headline number matches every other
        surface; humanizes each technique so a raw ladder code / internal ULID never reaches an exec;
        and degrades gracefully to a clean all-clear when nothing material breached.
        """
        report = await self._load_report(scan_id)
        muts = mitigations or {}
        score = scoring.score_for(report)
        level = scoring.risk_level(score)

        # The findings that warrant exec attention: breached AND critical/high, already severity- then
        # success-ranked by `top_findings`. A breached-but-medium/low finding is full-report detail.
        notable = [
            f
            for f in report.top_findings(50)
            if f.breached and f.severity in ("critical", "high")
        ]

        # (1) Risk-posture verdict — one line, recommendation-shaped, banded off the score.
        verdict = {
            "critical": "the deployment is exposed to exploitable critical weaknesses and should be treated as an active risk.",
            "high": "the deployment carries material, reproducible weaknesses that warrant remediation this sprint.",
            "medium": "the deployment shows moderate weaknesses worth scheduling and re-testing.",
            "low": "the deployment held up well against this run, with no material weaknesses reproduced.",
        }[level]

        lines = [
            "# ROGUE security scan — executive summary",
            "",
            f"**Risk {score:g}/100 ({level.upper()}).** Across {report.n_tests} adversarial tests, "
            f"{report.n_breaches} breached the target ({report.breach_pct}) — {verdict}",
            "",
        ]
        # Defensive gauge (blue-team): the deployment's instruction-hierarchy score — how reliably it
        # holds its system prompt when a user prompt tries to override it (None when the stage was off).
        if report.system_prompt_priority is not None:
            _p = round(report.system_prompt_priority * 100)
            lines.append(
                f"**System-prompt priority: {_p}%.** The model held its system prompt over a "
                f"conflicting user instruction on {_p}% of hierarchy probes — "
                + ("a strong instruction hierarchy." if _p >= 75 else
                   "a weak instruction hierarchy; a jailbreak that overrides the system prompt is more likely to land.")
            )
            lines.append("")

        # (2) Top risks in business terms — what each worst finding *means*, not just its name.
        if notable:
            lines.append("## Top risks, in business terms")
            lines.append("")
            for f in notable:
                technique = humanize_technique(f.technique)
                explanation = _explanation_for(f)
                lines.append(
                    f"- **{technique}** ({f.severity}, breached {f.n_breach}/{f.n_trials} trials, "
                    f"{f.success_pct} of attempts succeeded). {explanation}"
                )
            lines.append("")

            # (3) What to do first — remediation for the worst findings, severity-ranked, deduped per
            # family so a buyer sees a clean ordered action list, not the same fix four times.
            lines.append("## What to do first")
            lines.append("")
            seen_families: set[str] = set()
            rank = 1
            for f in notable:
                if f.family in seen_families:
                    continue
                seen_families.add(f.family)
                lines.append(f"{rank}. {remediation_section(f.family, muts.get(f.family))}")
                rank += 1
            lines.append("")
        else:
            lines.append(
                "No critical or high-severity attack reproduced against this target in this run."
            )
            lines.append("")

        # (4) Closing posture — the "so what" a CISO acts on, banded so it reads as a recommendation.
        if level == "critical":
            posture = (
                "Bottom line: remediate the items above before further exposure, then re-scan to "
                "confirm the critical paths are closed — this is a brand, compliance, and customer-trust risk today."
            )
        elif level == "high":
            posture = (
                "Bottom line: work the prioritized list above this sprint and re-scan to verify the "
                "fixes hold under adversarial framing before the next release."
            )
        elif level == "medium":
            posture = (
                "Bottom line: schedule the remediation above into the next cycle and re-scan to confirm "
                "the residual risk has been driven down."
            )
        else:
            posture = (
                "Bottom line: maintain the current controls and keep scanning on a regular cadence — "
                "today's posture is sound but the open-web threat surface keeps moving."
            )
        lines.append(f"**Posture:** {posture}")

        return "\n".join(lines)

    async def build_html(
        self,
        scan_id: str,
        *,
        mitigations: "dict[str, RemediationResult] | None" = None,
    ) -> str:
        """Reuse `ScanReport.to_html()`, surfacing the platform score/risk_level in the header KPIs.

        `ScanReport.to_html()` accepts optional `score`/`risk_level` params and renders the Risk-score KPI natively; we pass them through. The `TypeError` fallback below is a defensive vestige for an older `rogue.report` that predates those params — it string-splices a Risk-score KPI in front of the KPI row so the headline number still leads the page even against that build.
        """
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        level = scoring.risk_level(score)
        scorecard = scoring.build_scorecard(report.findings)
        coverage = scoring.build_coverage(report.findings)

        try:
            return report.to_html(
                score=score,
                risk_level=level,
                mitigations=mitigations,
                scorecard=scorecard,
                coverage=coverage,
            )
        except TypeError:
            # Defensive: only reached against an older `to_html` that predates the score/risk_level
            # params. Splice a Risk-score KPI in front of the existing KPI row so the headline number
            # a customer acts on still leads the page — without re-templating the whole report.
            page = report.to_html()
            kpi = (
                f'<div class="kpi">Risk score'
                f"<b>{score:g}/100 ({_html.escape(level)})</b></div>\n "
            )
            marker = '<div class="kpis">\n'
            if marker in page:
                page = page.replace(marker, marker + " " + kpi, 1)
            return page

    async def build_pdf(
        self,
        scan_id: str,
        *,
        mitigations: "dict[str, RemediationResult] | None" = None,
    ) -> bytes:
        """Render a CISO-ready PDF document (lazy-imports reportlab; raises if it's absent).

        Structure, top to bottom: a cover title, the headline Risk score + risk_level with the
        `SCORE_METHODOLOGY` caption, a one-paragraph executive summary (reusing `build_executive_summary`
        so the prose matches every other surface), a scan-coverage / methodology section (how many tests
        across which families, and one honest sentence on what "breach" means — ROGUE grades
        goal-achievement via an independent LLM judge), then the findings table, severity-grouped
        (critical → high → medium → low) with the wrapped Remediation column.
        """
        try:
            from reportlab.lib import colors  # noqa: PLC0415
            from reportlab.lib.pagesizes import letter  # noqa: PLC0415
            from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
            from reportlab.platypus import (  # noqa: PLC0415
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as e:  # pragma: no cover - exercised only without reportlab installed
            raise RuntimeError(
                "PDF export requires reportlab. Install with: pip install reportlab"
            ) from e

        import io  # noqa: PLC0415

        from rogue.taxonomy.crosswalk import (  # noqa: PLC0415
            crosswalk_for_family,
            format_frameworks_line,
        )

        report = await self._load_report(scan_id)
        muts = mitigations or {}
        score = scoring.score_for(report)
        level = scoring.risk_level(score)
        scorecard = scoring.build_scorecard(report.findings)
        coverage = scoring.build_coverage(report.findings)
        styles = getSampleStyleSheet()
        body = styles["BodyText"]

        # The exec summary is markdown (one short paragraph + a findings list); for the PDF we want a
        # single prose paragraph as the lead-in, so take the markdown's headline/business-framing prose
        # rather than re-rendering its bullet list (the table below already enumerates the findings).
        summary_md = await self.build_executive_summary(scan_id, mitigations=mitigations)
        summary_prose = self._summary_prose(summary_md)

        # --- Cover + headline -------------------------------------------------------------------
        story = [
            Paragraph("ROGUE Threat Scan — Security Assessment", styles["Title"]),
            Paragraph(f"Target: {_html.escape(report.target)}", styles["Heading3"]),
            Spacer(1, 10),
            Paragraph(f"Risk score {score:g}/100 ({level.upper()})", styles["Heading2"]),
            Paragraph(
                f"Overall grade {_html.escape(str(scorecard['grade']))} "
                "(worst attack family dominates)",
                styles["Heading2"],
            ),
            Paragraph(_html.escape(SCORE_METHODOLOGY), styles["BodyText"]),
            Spacer(1, 12),
        ]

        # --- Executive summary ------------------------------------------------------------------
        story.append(Paragraph("Executive summary", styles["Heading2"]))
        story.append(Paragraph(_html.escape(summary_prose), body))
        story.append(Spacer(1, 12))

        # --- Scan coverage / methodology --------------------------------------------------------
        families = report.families_covered()
        families_str = ", ".join(_html.escape(fam) for fam in families) or "none"
        story.append(Paragraph("Scan coverage &amp; methodology", styles["Heading2"]))
        story.append(
            Paragraph(
                f"This scan ran {report.n_tests} attack tests against the target across "
                f"{len(families)} attack famil{'y' if len(families) == 1 else 'ies'} "
                f"({families_str}); {report.n_breaches} breached "
                f"({_html.escape(report.breach_pct)} breach rate).",
                body,
            )
        )
        story.append(
            Paragraph(
                "A test counts as a breach when ROGUE judges the target to have achieved the attack's "
                "harmful goal — graded by an independent LLM judge on the model's actual response, not "
                "by keyword matching — with the rate taken as the worst (any-breach) result over the "
                "repeated trials per attack.",
                body,
            )
        )
        # Honest test-completeness: which of the 15 frozen families were probed vs never fired.
        n_probed = int(coverage["n_families_probed"])
        n_total = int(coverage["n_families_total"])
        story.append(
            Paragraph(
                f"Coverage: {n_probed} of {n_total} attack families were probed in this run; "
                f"{n_total - n_probed} were not exercised (see the coverage matrix in the JSON report).",
                body,
            )
        )
        story.append(Spacer(1, 14))

        # --- Family scorecard (graded ASR rollup) -----------------------------------------------
        scored = scorecard.get("families") or []
        if scored:
            story.append(Paragraph("Family scorecard", styles["Heading2"]))
            sc_data = [["Grade", "Family", "ASR", "95% CI", "Trials"]]
            for fam in scored:
                asr = round(float(fam["asr"]) * 100)
                lo = round(float(fam["ci_low"]) * 100)
                hi = round(float(fam["ci_high"]) * 100)
                sc_data.append(
                    [
                        _html.escape(str(fam["grade"])),
                        Paragraph(_html.escape(str(fam["label"])), body),
                        f"{asr}%",
                        f"{lo}–{hi}%",
                        f"{fam['n_breach']}/{fam['n_trials']}",
                    ]
                )
            sc_table = Table(sc_data, repeatRows=1, colWidths=[45, 200, 50, 90, 55])
            sc_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(sc_table)
            story.append(Spacer(1, 14))

        # --- Findings table (severity-grouped) --------------------------------------------------
        story.append(Paragraph("Findings", styles["Heading2"]))
        # Header + findings grouped by severity (critical → high → medium → low), breached-first within
        # each group. Free-text cells wrapped in Paragraphs so long text reflows instead of overflowing.
        # The Finding cell carries the title PLUS the plain-language `explanation` ("what this means for
        # you"); the Remediation cell carries the per-family fix — so each row is self-explanatory to a
        # non-specialist reader. All cells escaped; the rebuilt Findings are already redacted by
        # `_load_report`. Explanation + remediation are render-time per-family (not stored on the Finding).
        data = [["Severity", "Success", "Technique", "Finding & what it means", "Remediation"]]
        for _sev, members in report.findings_by_severity():
            for f in members:
                fw_line = format_frameworks_line(
                    crosswalk_for_family(f.family, vector_slug(f.vector))
                )
                fw_html = (
                    f"<br/><font size=7 color='#666666'>{_html.escape(fw_line)}</font>"
                    if fw_line
                    else ""
                )
                finding_cell = (
                    f"<b>{_html.escape(f.title)}</b><br/>"
                    f"{_html.escape(_explanation_for(f))}"
                    f"{fw_html}"
                )
                data.append(
                    [
                        _html.escape(f.severity),
                        f.success_pct,
                        Paragraph(_html.escape(technique_label(f.family)), body),
                        Paragraph(finding_cell, body),
                        Paragraph(
                            _html.escape(remediation_section(f.family, muts.get(f.family))), body
                        ),
                    ]
                )
        if len(data) == 1:
            data.append([Paragraph("No findings.", body), "", "", "", ""])
        table = Table(data, repeatRows=1, colWidths=[50, 45, 80, 150, 195])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)

        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=letter).build(story)
        return buf.getvalue()

    # Leading "1. " / "12. " style ordered-list marker — the "What to do first" items, which the PDF's
    # findings table already enumerates per row, so they're dropped from the prose lead-in.
    _ORDERED_LI_RE = re.compile(r"^\d+\.\s")

    @classmethod
    def _summary_prose(cls, summary_md: str) -> str:
        """Distill the markdown exec summary into one prose paragraph for the PDF lead-in.

        `build_executive_summary` emits a headline verdict line, section headings, a bullet list of
        top risks and a numbered "what to do first" list (both enumerated again by the PDF's findings
        table, so dropped here), and a bold "Posture:" closing line. We keep the headline verdict + the
        posture sentence, stripped of markdown emphasis and section labels, joined into one flowing
        paragraph.
        """
        keep: list[str] = []
        for line in summary_md.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith("#")
                or stripped.startswith("- ")
                or cls._ORDERED_LI_RE.match(stripped)
            ):
                continue
            # Drop markdown emphasis and the section labels so the prose reads as plain narrative.
            text = (
                stripped.replace("**", "")
                .replace("Posture:", "")
                .replace("Business impact:", "")
                .strip()
            )
            if text:
                keep.append(text)
        return " ".join(keep)


__all__ = ["DefaultReportService", "_redact"]
