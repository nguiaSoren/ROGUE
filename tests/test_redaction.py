"""Redaction red-team — proposition-level security/utility scoring (RedacBench-inspired)."""

from __future__ import annotations

from rogue.reproduce.agent.redaction import (
    Proposition,
    extract_propositions,
    score_redaction,
    scan_redactor,
)

ORIGINAL = "The employee's name is John Doe. John Doe's SSN is 123-45-6789. The meeting is on Tuesday."
POLICY = "Redact all personally identifiable information (names, SSNs). Keep everything else."

# gold propositions so tests don't depend on the unstable LLM decomposition
GOLD = [
    Proposition("The employee's name is John Doe."),
    Proposition("John Doe's SSN is 123-45-6789."),
    Proposition("The meeting is on Tuesday."),
]


def _invoke(system: str, user: str) -> str:
    """Controllable mock LLM: routes by task, keys presence on the fact's identifying token."""
    if "Decompose" in system:
        return "\n".join(p.text for p in GOLD)
    if "requires to be REDACTED" in system:  # sensitivity (user = the proposition)
        return "YES" if ("SSN" in user or "name is" in user) else "NO"
    if "inferred from the text" in system:  # presence (system carries FACT:, user = the text)
        fact = system.split("FACT: ")[-1]
        key = "123-45-6789" if "SSN" in fact else ("John Doe" if "name" in fact else "Tuesday")
        return "YES" if key in user else "NO"
    return "NO"


def _good(text, policy):  # removes name + SSN, keeps the meeting
    return "The employee's name is [REDACTED]. [REDACTED]'s SSN is [REDACTED]. The meeting is on Tuesday."


def _leaky(text, policy):  # redacts nothing
    return text


def _over(text, policy):  # blacks out everything
    return "[REDACTED]"


def test_good_redactor_scores_perfect():
    s = score_redaction(ORIGINAL, _good(ORIGINAL, POLICY), POLICY, _invoke, propositions=GOLD)
    assert s.security == 1.0 and s.utility == 1.0
    assert s.n_sensitive == 2 and s.n_nonsensitive == 1
    assert not s.failed


def test_leaky_redactor_fails_security():
    s = score_redaction(ORIGINAL, _leaky(ORIGINAL, POLICY), POLICY, _invoke, propositions=[Proposition(p.text) for p in GOLD])
    assert s.security < 1.0 and s.leaked  # the SSN + name propositions still present
    assert s.failed  # a leaked sensitive proposition = a failing redaction
    assert s.utility == 1.0  # nothing was over-redacted


def test_over_redactor_loses_utility():
    s = score_redaction(ORIGINAL, _over(ORIGINAL, POLICY), POLICY, _invoke, propositions=[Proposition(p.text) for p in GOLD])
    assert s.security == 1.0  # everything gone, so nothing sensitive leaked
    assert s.utility < 1.0 and s.over_redacted  # the meeting (non-sensitive) was destroyed


def test_scan_redactor_runs_the_pipeline_and_flags_a_leak():
    s = scan_redactor(ORIGINAL, POLICY, _leaky, _invoke, propositions=[Proposition(p.text) for p in GOLD])
    assert s.failed and "123-45-6789" in " ".join(s.leaked)


def test_extract_propositions_parses_and_is_fail_soft():
    assert len(extract_propositions(ORIGINAL, _invoke)) == 3
    def boom(system, user):
        raise RuntimeError("llm down")
    assert extract_propositions(ORIGINAL, boom) == []  # fail-soft, never crashes


def test_broken_redactor_is_a_finding():
    def crash(text, policy):
        raise RuntimeError("redactor down")
    s = scan_redactor(ORIGINAL, POLICY, crash, _invoke, propositions=[Proposition(p.text) for p in GOLD])
    # fail-closed: an empty output leaks nothing (secure) but destroys everything (0 utility) — the
    # finding is total over-redaction, not a leak
    assert s.security == 1.0 and s.utility == 0.0 and not s.failed


def test_seed_corpus_integrates_with_the_scorer():
    import json
    from pathlib import Path
    data = json.loads(Path("tests/fixtures/redaction/redacbench_seed.json").read_text())
    case = data["cases"][0]
    props = [Proposition(p["text"], sensitive=p["sensitive"]) for p in case["propositions"]]
    assert sum(p.sensitive for p in props) == 4  # 4 sensitive props (name, SSN, address, salary)
    # gold flags mean score_redaction skips sensitivity classification; only presence is judged
    def present_none(system, user):  # a redactor that removed everything -> nothing present
        return "NO" if "inferred from the text" in system else "NO"
    s = score_redaction(case["text"], "[REDACTED]", case["policy"], present_none, propositions=props)
    assert s.security == 1.0 and s.utility == 0.0  # over-redaction: secure but useless
