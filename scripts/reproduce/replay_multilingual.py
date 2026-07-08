"""$0 census/replay for Q20 — measure, from data already paid for, (a) the camouflaged-intent tag
distribution over the harvested corpus and (b) how English-centric the corpus currently is (the gap the
multilingual harvest + translate-then-reproduce close). Read-only: it never fires a model, never writes.

Run against Neon (the un-redacted corpus; the local docker snapshot has payload_slots="[redacted]"):

    DATABASE_URL=$NEON_URL uv run python scripts/reproduce/replay_multilingual.py

HONESTY: these are $0 census numbers — the camouflage figure is a WEAK LEXICAL PRIOR (Zheng shows
keyword detection can't reliably catch camouflage; the strong signal is the LLM judge), and the
English-centrism figure is a coverage gap, not a breach delta. The headline English-vs-non-English
breach delta needs the paid `--multilingual` reproduce arm. See docs/research/multilingual_coverage.md.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from rogue.extract.camouflage import camouflage_score  # noqa: E402
from rogue.grammar.stats import wilson_ci  # noqa: E402


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001 — dotenv is optional; env may already be set
        pass
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("set DATABASE_URL (Neon for the real corpus)")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT primitive_id, family, payload_template, payload_slots FROM attack_primitives"
        )).fetchall()
    engine.dispose()

    n = len(rows)
    if not n:
        raise SystemExit("no primitives found")

    # (a) camouflaged-intent tag distribution
    labels = {"camouflaged": 0, "overt": 0, "ambiguous": 0}
    for _pid, _fam, payload, _slots in rows:
        labels[camouflage_score(payload or "").label] += 1
    k = labels["camouflaged"]
    lo, hi = wilson_ci(k, n)

    print(f"=== Q20 $0 census over {n} harvested primitives ===\n")
    print("(a) Camouflaged-intent tag (weak lexical prior; frame × dual-use co-occurrence):")
    for lab in ("camouflaged", "overt", "ambiguous"):
        print(f"      {lab:11s}: {labels[lab]:5d} ({labels[lab] / n:6.1%})")
    print(f"      camouflaged fraction: {k}/{n} = {k / n:.1%}  [95% Wilson CI {lo:.1%}, {hi:.1%}]")

    # (b) English-centrism of the corpus (the gap Q20 closes)
    lang_switch = sum(1 for _pid, fam, _p, _s in rows if fam == "language_switching")
    has_lang_slot = 0
    for _pid, _fam, payload, slots in rows:
        s = slots if isinstance(slots, dict) else {}
        if "{language}" in (payload or "") or any(str(k2).endswith("_l1") or k2 == "language" for k2 in s):
            has_lang_slot += 1
    print("\n(b) Current multilingual coverage (English-centrism the harvest+reproduce paths close):")
    print(f"      language_switching family : {lang_switch}/{n} = {lang_switch / n:.1%}")
    print(f"      carry a language/_l1 slot : {has_lang_slot}/{n} = {has_lang_slot / n:.1%}")
    print(f"      → {(n - max(lang_switch, has_lang_slot)) / n:.0%} of the corpus is English-only text with no language axis at all.")
    print("\nNOTE: the English-vs-non-English breach DELTA is the paid --multilingual reproduce arm; this census is coverage + tag distribution only.")


if __name__ == "__main__":
    main()
