"""Customer-facing reports for the ROGUE SDK.

Users get *objects*, never raw `BreachResult` / `AttackPrimitive` rows. A :class:`ScanReport` leads
with the numbers a security engineer acts on (target, tests, breaches, rate, top attack, cost) and
knows how to render itself for a terminal, a JSON pipeline, or a sales-demo HTML page.
"""

from __future__ import annotations

import html as _html
import json as _json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Display label per internal attack-family slug (so customers see "Crescendo", not "multi_turn_gradient").
_TECHNIQUE_DISPLAY: dict[str, str] = {
    "direct_instruction_override": "Direct Instruction Override",
    "role_hijack": "Role Hijack",
    "dan_persona": "DAN / Persona Jailbreak",
    "policy_roleplay": "Policy-Evasion Roleplay",
    "refusal_suppression": "Refusal Suppression",
    "multi_turn_gradient": "Crescendo",
    "chain_of_thought_hijack": "Chain-of-Thought Hijack",
    "system_prompt_leak": "System-Prompt Leak",
    "training_data_extraction": "Training-Data Extraction",
    "indirect_prompt_injection": "Indirect Prompt Injection",
    "tool_use_hijack": "Tool-Use Hijack",
    "obfuscation_encoding": "Obfuscation / Encoding",
    "language_switching": "Language Switching",
    "multimodal_injection": "Multimodal Injection",
    "multi_turn_persona_chain": "Multi-Turn Persona Chain",
}

# Display label per internal attack *vector* slug (so customers see "User turn", not "user_turn").
_VECTOR_DISPLAY: dict[str, str] = {
    "user_turn": "User turn",
    "user_multi_turn": "User (multi-turn)",
    "rag_document": "RAG document",
    "tool_output": "Tool output",
    "system_prompt": "System prompt",
    "multimodal_image": "Image",
    "multimodal_audio": "Audio",
}

# Display label per *static* escalation-ladder winning-strategy code.
_STRATEGY_DISPLAY: dict[str, str] = {
    "crescendo": "Crescendo (gradual escalation)",
    "actor_attack": "Actor/roleplay attack",
    "acronym": "Acronym obfuscation",
}

# Display template per *prefixed* winning-strategy code (`<prefix>:<arg>`).
_STRATEGY_PREFIX_DISPLAY: dict[str, str] = {
    "image": "Image-rendered payload ({arg})",
    "coj": "Chain-of-jailbreak edit ({arg})",
    "structured": "Structured-format wrapper ({arg})",
    "audio": "Audio-rendered payload ({arg})",
}

_SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _fmt_usd(x: float) -> str:
    """Format a USD cost: 2 decimals at/above a cent, finer precision below (so small scans
    don't read as a misleading ``$0.00``)."""
    if x >= 0.01:
        return f"${x:.2f}"
    if x > 0:
        return f"${x:.4f}"
    return "$0.00"


# A 26-char Crockford base32 ULID (Crockford excludes I, L, O, U).
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
# A raw/cryptic machine token: no whitespace, only lowercase/digits/_/:/- (the shape ladder
# codes and ids take). Humane labels carry capitals or spaces, so they fail this and pass through.
_RAW_CODE_RE = re.compile(r"^[a-z0-9_:-]+$")


def _looks_like_id(code: str) -> bool:
    """True for an internal id / raw machine token that must never reach a customer."""
    return bool(_ULID_RE.match(code) or _RAW_CODE_RE.match(code))


def technique_label(family: str) -> str:
    return _TECHNIQUE_DISPLAY.get(family, family.replace("_", " ").title())


def vector_label(vector: str) -> str:
    """Humanize an internal attack-vector slug (``user_turn`` → "User turn")."""
    return _VECTOR_DISPLAY.get(vector, vector.replace("_", " ").title())


def humanize_technique(code: str) -> str:
    """Map a raw escalation-ladder ``winning_strategy`` code to a human display label.

    The escalation ladder credits a breach with either a *static* strategy
    (``crescendo`` / ``actor_attack`` / ``acronym``), a *prefixed* transform
    (``image:<renderer>`` / ``coj:<op>`` / ``structured:<fmt>`` / ``audio:<style>``),
    or — when a harvested candidate graduates — the parent primitive's raw ULID.
    A ULID is an internal id and must NEVER reach a customer; map it (and any
    other raw/cryptic code) to a generic, honest label.

    This is also applied *defensively* at render time over `Finding.technique`,
    which in single/repertoire mode already holds a humane family label (e.g.
    "DAN / Persona Jailbreak"). Such already-humane labels are NOT codes, so they
    pass through unchanged. Pure + table-driven.
    """
    if not code:
        return "Harvested escalation technique"
    if code in _STRATEGY_DISPLAY:
        return _STRATEGY_DISPLAY[code]
    prefix, sep, arg = code.partition(":")
    if sep and prefix in _STRATEGY_PREFIX_DISPLAY and arg:
        return _STRATEGY_PREFIX_DISPLAY[prefix].format(arg=arg)
    # A graduated candidate persists its parent ULID (26-char Crockford base32, no I/L/O/U).
    # An internal id must never leak — map any id-shaped token to the generic label.
    if _looks_like_id(code):
        return "Harvested escalation technique"
    # Anything else is an already-humane label (single/repertoire mode) → leave untouched.
    return code


@dataclass
class Finding:
    """One reproduced vulnerability against the target — risk, not raw payload."""

    family: str
    technique: str
    vector: str
    severity: str
    title: str
    success_rate: float
    n_trials: int
    n_breach: int
    example_attack: str | None = None
    example_response: str | None = None

    @property
    def success_pct(self) -> str:
        return f"{round(self.success_rate * 100)}%"

    @property
    def breached(self) -> bool:
        return self.n_breach > 0


@dataclass
class ScanReport:
    """The result of ``client.scan()``."""

    target: str
    n_tests: int
    n_breaches: int
    cost_usd: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def breach_rate(self) -> float:
        return self.n_breaches / self.n_tests if self.n_tests else 0.0

    @property
    def breach_pct(self) -> str:
        return f"{round(self.breach_rate * 100)}%"

    def breached_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.breached]

    def top_findings(self, n: int = 5) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (_SEVERITY_RANK.get(f.severity, 0), f.success_rate),
            reverse=True,
        )[:n]

    @property
    def top_attack(self) -> str | None:
        breached = self.breached_findings()
        if not breached:
            return None
        top = max(breached, key=lambda f: (f.success_rate, _SEVERITY_RANK.get(f.severity, 0)))
        return humanize_technique(top.technique)

    # --- renderers ----------------------------------------------------------------------------

    def summary(self) -> str:
        """The terminal summary a security engineer reads first."""
        lines = [
            "Target:",
            f"  {self.target}",
            "Tests:",
            f"  {self.n_tests}",
            "Breaches:",
            f"  {self.n_breaches}",
            "Rate:",
            f"  {self.breach_pct}",
            "Top Attack:",
            f"  {self.top_attack or '— (none breached)'}",
            "Cost:",
            f"  {_fmt_usd(self.cost_usd)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        findings = []
        for f in self.findings:
            d = asdict(f)
            # Render-time humanization: a raw ULID/code stored in `technique` (from a
            # ladder scan) must never surface to a customer. `top_attack` is already humane.
            d["technique"] = humanize_technique(f.technique)
            d["vector"] = vector_label(f.vector)
            findings.append(d)
        return {
            "target": self.target,
            "n_tests": self.n_tests,
            "n_breaches": self.n_breaches,
            "breach_rate": round(self.breach_rate, 4),
            "top_attack": self.top_attack,
            "cost_usd": round(self.cost_usd, 6),
            "findings": findings,
        }

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = _json.dumps(self.to_dict(), indent=indent, default=str)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def to_html(self, path: str | Path | None = None) -> str:
        """A standalone HTML report — the artifact for a sales demo / email attachment."""
        rows = []
        for f in self.top_findings(50):
            mark = "🔴" if f.breached else "🟢"
            rows.append(
                "<tr>"
                f"<td>{mark}</td>"
                f"<td>{_html.escape(f.severity)}</td>"
                f"<td>{f.success_pct}</td>"
                f"<td>{_html.escape(humanize_technique(f.technique))}</td>"
                f"<td>{_html.escape(f.title)}</td>"
                "</tr>"
            )
        rate_color = "#d33" if self.breach_rate > 0 else "#2a2"
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ROGUE Scan Report</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:860px;margin:2rem auto;color:#1a1a1a}}
 h1{{font-size:1.4rem}} .kpis{{display:flex;gap:2rem;margin:1.5rem 0}}
 .kpi{{font-size:.85rem;color:#666}} .kpi b{{display:block;font-size:1.6rem;color:#111}}
 table{{border-collapse:collapse;width:100%;font-size:.9rem}}
 th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #eee}} th{{color:#888;font-weight:600}}
 .rate{{color:{rate_color}}}
</style></head><body>
<h1>ROGUE Threat Scan</h1>
<p>Target: <code>{_html.escape(self.target)}</code></p>
<div class="kpis">
 <div class="kpi">Tests<b>{self.n_tests}</b></div>
 <div class="kpi">Breaches<b>{self.n_breaches}</b></div>
 <div class="kpi">Breach rate<b class="rate">{self.breach_pct}</b></div>
 <div class="kpi">Top attack<b>{_html.escape(self.top_attack or '—')}</b></div>
 <div class="kpi">Cost<b>{_fmt_usd(self.cost_usd)}</b></div>
</div>
<table><thead><tr><th></th><th>Severity</th><th>Success</th><th>Technique</th><th>Finding</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan=5>No findings.</td></tr>'}</tbody></table>
</body></html>"""
        if path is not None:
            Path(path).write_text(body, encoding="utf-8")
        return body

    def __str__(self) -> str:  # pragma: no cover
        return self.summary()


@dataclass
class ValidationResult:
    """The result of ``client.validate()`` — cheap pre-flight before spending on a scan."""

    target: str
    reachable: bool
    authenticated: bool
    model_responds: bool
    supports_image: bool
    supports_audio: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.reachable and self.authenticated and self.model_responds

    def summary(self) -> str:
        def mark(b: bool) -> str:
            return "✓" if b else "✗"

        lines = [
            f"Target:           {self.target}",
            f"Reachable:        {mark(self.reachable)}",
            f"Authenticated:    {mark(self.authenticated)}",
            f"Model responds:   {mark(self.model_responds)}",
            f"Supports image:   {mark(self.supports_image)}",
            f"Supports audio:   {mark(self.supports_audio)}",
            f"Ready to scan:    {mark(self.ok)}",
        ]
        if self.error:
            lines.append(f"Error:            {self.error}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return _json.dumps(self.to_dict(), indent=indent, default=str)

    def __str__(self) -> str:  # pragma: no cover
        return self.summary()


@dataclass
class BenchmarkReport:
    """The result of ``client.benchmark()`` — research-grade ASR on a standard dataset."""

    dataset: str
    target: str
    n_goals: int
    n_success: int
    cost_usd: float
    winner_rank: int | None = None

    @property
    def asr(self) -> float:
        return self.n_success / self.n_goals if self.n_goals else 0.0

    @property
    def cost_per_success(self) -> float | None:
        return self.cost_usd / self.n_success if self.n_success else None

    def summary(self) -> str:
        cps = self.cost_per_success
        lines = [
            f"Benchmark:        {self.dataset}",
            f"Target:           {self.target}",
            f"Goals:            {self.n_goals}",
            f"ASR:              {round(self.asr * 100)}%  ({self.n_success}/{self.n_goals})",
            f"Cost:             {_fmt_usd(self.cost_usd)}",
            f"Cost / success:   {('$%.4f' % cps) if cps is not None else '—'}",
        ]
        if self.winner_rank is not None:
            lines.append(f"Rank vs field:    #{self.winner_rank}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(asr=round(self.asr, 4), cost_per_success=self.cost_per_success)
        return d

    def to_json(self, *, indent: int = 2) -> str:
        return _json.dumps(self.to_dict(), indent=indent, default=str)

    def __str__(self) -> str:  # pragma: no cover
        return self.summary()


__all__ = [
    "Finding",
    "ScanReport",
    "ValidationResult",
    "BenchmarkReport",
    "technique_label",
    "humanize_technique",
    "vector_label",
]
