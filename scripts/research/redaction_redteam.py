#!/usr/bin/env python
"""Red-team a redaction / DLP pipeline — the wired entry for `rogue.reproduce.agent.redaction`
(RedacBench 2603.20208).

Scores a redactor on SECURITY (policy-sensitive propositions removed) and UTILITY (the rest preserved)
over the seed corpus. With --live it uses a real LLM for the proposition decomposition + sensitivity +
semantic-leak judgments; otherwise it runs a built-in demo redactor set against gold propositions ($0).

Usage:
    uv run python scripts/research/redaction_redteam.py            # $0 demo (good/leaky/over redactors)
    uv run python scripts/research/redaction_redteam.py --live     # live LLM judge over the seed corpus
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rogue.reproduce.agent.redaction import Proposition, score_redaction  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "redaction" / "redacbench_seed.json"


def _live_invoke(model: str):
    from openai import OpenAI  # lazy
    key = os.getenv("OPENROUTER_API_KEY")
    client = (OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key) if key
              else OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, api_key=os.getenv("OPENAI_API_KEY")))

    def _invoke(system: str, user: str) -> str:
        r = client.chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content or ""

    return _invoke


def _redactors():
    """A benign redactor panel: a competent one, a leaky one, an over-redactor."""
    def good(text, policy):  # blanks obvious PII tokens
        import re
        out = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED]", text)       # SSNs
        out = re.sub(r"\$[\d,]+", "[REDACTED]", out)                      # salaries
        for name in ("Jane Miller", "Robert Chen", "14 Oak Lane", "GA-77120", "epilepsy",
                     "Jane", "Robert", "Chen", "Miller"):  # standalone first/last names too
            out = out.replace(name, "[REDACTED]")
        return out
    def leaky(text, policy):  # does nothing
        return text
    def over(text, policy):   # blacks everything out
        return "[REDACTED]"
    return {"good": good, "leaky": leaky, "over": over}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="use a live LLM judge (else gold-proposition $0 demo)")
    ap.add_argument("--model", default="openai/gpt-4o-mini", help="judge model when --live")
    args = ap.parse_args(argv)

    cases = json.loads(FIXTURE.read_text())["cases"]
    invoke = _live_invoke(args.model) if args.live else None
    redactors = _redactors()

    for case in cases:
        gold = [Proposition(p["text"], sensitive=p["sensitive"]) for p in case["propositions"]]
        print(f"\n=== {case['id']} ({case['domain']}) ===")
        for name, red in redactors.items():
            redacted = red(case["text"], case["policy"])
            if args.live:
                s = score_redaction(case["text"], redacted, case["policy"], invoke)  # LLM decompose+judge
            else:
                # $0: gold propositions + an IDENTIFYING-token presence check (proper nouns / numbers /
                # ids only — not scaffold words, else a good redaction reads as a leak). A crude stand-in
                # for the real semantic-leak judge (--live); the point is the harness, not the number.
                def _present(system, user, _r=redacted):
                    import re
                    fact = system.split("FACT: ")[-1]
                    ident = re.findall(r"\b[A-Z][a-zA-Z]+\b|\b[\w-]*\d[\w-]*\b", fact)  # Names, IDs, numbers
                    ident = [t for t in ident if t not in ("The", "An", "A", "SSN")]
                    return "YES" if any(t in _r for t in ident) else "NO"
                s = score_redaction(case["text"], redacted, case["policy"], _present, propositions=gold)
            flag = "  <-- LEAK" if s.failed else ""
            print(f"  {name:5} security={s.security} utility={s.utility} "
                  f"(sens={s.n_sensitive}/nonsens={s.n_nonsensitive}) failed={s.failed}{flag}")
    if not args.live:
        print("\n($0 demo: gold props + lexical presence. --live uses a real LLM decomposition + "
              "semantic-leak judge — certify that judge before headlining, RESEARCH_TODO Arm 7.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
