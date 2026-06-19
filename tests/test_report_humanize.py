"""Customer-facing reports must never leak raw internal ids (ULIDs) or cryptic
winning-strategy codes. `humanize_technique` maps every ladder `winning_strategy`
shape to a human label; the renderers apply it defensively so already-persisted
reports (e.g. a graduated harvested candidate that stored its parent ULID) display
cleanly too.
"""

from __future__ import annotations

import pytest

from rogue.report import Finding, ScanReport, humanize_technique, vector_label

# A real ULID (26-char Crockford base32) — the shape a graduated candidate persists.
ULID = "01KT3AT601W2CBWRT2Y6SHV55B"


@pytest.mark.parametrize(
    "code,expected",
    [
        ("crescendo", "Crescendo (gradual escalation)"),
        ("actor_attack", "Actor/roleplay attack"),
        ("acronym", "Acronym obfuscation"),
        ("image:mml", "Image-rendered payload (mml)"),
        ("image:ocr", "Image-rendered payload (ocr)"),
        ("coj:rewrite", "Chain-of-jailbreak edit (rewrite)"),
        ("structured:json", "Structured-format wrapper (json)"),
        ("audio:fast", "Audio-rendered payload (fast)"),
    ],
)
def test_humanize_known_codes(code: str, expected: str) -> None:
    assert humanize_technique(code) == expected


def test_humanize_ulid_never_leaks_raw_id() -> None:
    out = humanize_technique(ULID)
    assert out == "Harvested escalation technique"
    assert ULID not in out


@pytest.mark.parametrize("code", ["", "wat", "image:", ":mml", "unknown:thing", ULID.lower()])
def test_humanize_raw_codes_are_generic(code: str) -> None:
    # Empty, ULID, or any raw machine token (lowercase/snake/colon) → generic; never the raw value.
    assert humanize_technique(code) == "Harvested escalation technique"


@pytest.mark.parametrize(
    "label",
    ["DAN / Persona Jailbreak", "Crescendo", "Refusal Suppression", "Direct Instruction Override"],
)
def test_humanize_passes_humane_family_labels_through(label: str) -> None:
    # Single/repertoire mode stores an already-humane family label in `technique`; the
    # defensive render-time humanization must leave it untouched (it isn't a raw code).
    assert humanize_technique(label) == label


def test_vector_label_map() -> None:
    assert vector_label("user_turn") == "User turn"
    assert vector_label("user_multi_turn") == "User (multi-turn)"
    assert vector_label("rag_document") == "RAG document"
    assert vector_label("tool_output") == "Tool output"
    assert vector_label("system_prompt") == "System prompt"
    assert vector_label("multimodal_image") == "Image"
    assert vector_label("multimodal_audio") == "Audio"
    # Unknown slug → title-cased fallback, never raw underscores.
    assert vector_label("some_new_vector") == "Some New Vector"


def _ulid_report() -> ScanReport:
    """A persisted-style report whose breaching finding stored a raw ULID technique."""
    return ScanReport(
        target="https://api.example.com/v1",
        n_tests=1,
        n_breaches=1,
        cost_usd=0.42,
        findings=[
            Finding(
                family="indirect_prompt_injection",
                technique=ULID,
                vector="multimodal_image",
                severity="high",
                title="Exfiltrate system prompt",
                success_rate=1.0,
                n_trials=5,
                n_breach=1,
            )
        ],
    )


def test_scanreport_summary_no_raw_ulid() -> None:
    report = _ulid_report()
    summary = report.summary()
    assert ULID not in summary
    assert "Harvested escalation technique" in summary
    assert report.top_attack == "Harvested escalation technique"


def test_scanreport_html_no_raw_ulid() -> None:
    report = _ulid_report()
    page = report.to_html()
    assert ULID not in page
    assert "Harvested escalation technique" in page


def test_scanreport_dict_humanizes_technique_and_vector() -> None:
    report = _ulid_report()
    d = report.to_dict()
    assert d["top_attack"] == "Harvested escalation technique"
    finding = d["findings"][0]
    assert finding["technique"] == "Harvested escalation technique"
    assert ULID not in finding["technique"]
    assert finding["vector"] == "Image"


def test_humanize_does_not_break_family_labels() -> None:
    # A non-ladder (single/repertoire) report already stores a humane family label in
    # `technique`; humanize_technique leaves recognized prefixes/strategies alone but a
    # family label like "Crescendo" is not a code → falls through to the generic label
    # only if it isn't one of the known forms. Guard the renderers still humanize cleanly.
    report = ScanReport(
        target="m",
        n_tests=1,
        n_breaches=1,
        cost_usd=0.0,
        findings=[
            Finding(
                family="multi_turn_gradient",
                technique="crescendo",
                vector="user_multi_turn",
                severity="high",
                title="t",
                success_rate=1.0,
                n_trials=5,
                n_breach=1,
            )
        ],
    )
    assert report.top_attack == "Crescendo (gradual escalation)"
    assert report.to_dict()["findings"][0]["vector"] == "User (multi-turn)"
