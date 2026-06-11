"""Grow the C2 claimed-success-rate sample for the reproducibility-gap study.

Re-fetches each arxiv/blog/huggingface source and re-extracts the success rate
the SOURCE claims for THAT technique, with Sonnet 4.6 via the Anthropic Batch
API (flat -50%) + a prompt-cached extraction instruction. Uniform model across
the whole claimed-candidate set so the C2 correlation is single-judgment.

THREE GATED PHASES (money/writes are opt-in):
  (default)   dry-run     — list candidates + cost preview. No fetch, no LLM, no DB write.
  --run       fetch+extract — Bright Data re-fetch + Sonnet batch extract -> data/research/reextracted_claims.json. PAID. No DB write.
  --apply     write        — read the JSON, back up old values, UPDATE attack_primitives.claimed_success_rate. Writes LIVE Neon.

Companion to docs/research/reproducibility_gap_study.md. Reuses
BrightDataClient.web_unlock + the judge_batch.py Batch-API pattern.

Run:
  uv run python scripts/research/grow_claimed_rates.py                 # dry-run (free)
  uv run python scripts/research/grow_claimed_rates.py --run           # paid fetch+extract
  uv run python scripts/research/grow_claimed_rates.py --apply         # write reviewed results to Neon
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "data" / "research" / "reextracted_claims.json"
BACKUP = ROOT / "data" / "research" / "reextracted_claims_backup.json"
MODEL = "claude-sonnet-4-6"
SOURCE_TYPES = ("arxiv", "blog", "huggingface")
DOC_CHAR_CAP = 40_000          # ~10k tokens of markdown per source
MAX_OUTPUT_TOKENS = 600
CACHE_MIN_TOKENS = 2048        # Sonnet 4.6 prompt-cache floor

os.environ.update({k: v for k, v in dotenv_values(ROOT / ".env").items() if v})
ENGINE = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

# Prompt-cached extraction instruction (identical across all batch requests, so
# it is written to cache once and read by every subsequent request).
SYSTEM_PROMPT = """You extract the *claimed attack-success rate* that a source document reports for a specific jailbreak / prompt-injection technique.

You are given (a) a ROGUE attack primitive — its title, family, and short description identifying ONE technique — and (b) the markdown of the source that the primitive was harvested from. Find the single success rate the SOURCE explicitly claims for THIS technique, and call `record_claimed_rate`.

Rules — read carefully, this number feeds a published correlation:
- Return `claimed_success_rate` as a fraction in [0,1] ONLY if the source states an explicit numeric success / attack-success / jailbreak / bypass rate for THIS technique. Convert percentages (e.g. "78.2%") to 0.782.
- If the source quotes a RANGE across models/conditions (e.g. "60.0%-78.2% across GPT-4o-mini, Claude…"), report the rate the source presents as the headline/representative figure for the technique; if there is no clear headline, report the MAXIMUM and say so in `stated_as`. Never average.
- Do NOT report: baseline/no-attack rates, defended/mitigated rates, correlation coefficients (r=…), BLEU/METEOR/accuracy metrics, refusal rates, or a different technique's rate.
- If the source states no explicit success rate for this technique, set `claimed_success_rate` to null. A confident null is correct and useful — do not guess or infer a number that is not stated.
- `stated_as` must quote the exact phrase from the source the number came from (or describe why it is null). `target_models_claimed` lists the models the rate was measured against, if stated.
- `confidence`: "high" if a single unambiguous rate for this technique; "medium" if you had to choose among several; "low" if uncertain whether the number really refers to this technique.

Worked examples:
1. Primitive: "Multi-turn translation into low-resource African language". Source says: "Afrikaans achieves 60.0%-78.2% harmful response rate across five models; English baseline 52.7%-83.6%." → claimed_success_rate=0.782, stated_as="Afrikaans 60.0%-78.2% (max across models)", target_models_claimed=["gpt-4o-mini","claude-3.5-haiku","deepseek-v3","gemini-2.0-flash","grok-3-mini"], confidence="medium".
2. Primitive: "DAN persona override". Source is a Reddit post sharing a prompt with no measured rate. → claimed_success_rate=null, stated_as="no explicit success rate stated; prompt shared without measurement", confidence="high".
3. Primitive: "GCG suffix". Source abstract: "attains 88% ASR on Vicuna and transfers at 43% to GPT-4." → claimed_success_rate=0.88, stated_as="88% ASR on Vicuna (headline)", target_models_claimed=["vicuna","gpt-4"], confidence="high".
Treat the figure for the *named primitive* as authoritative; when a paper covers several attacks, extract only the one matching the primitive's title/family/description."""

EXTRACT_TOOL = {
    "name": "record_claimed_rate",
    "description": "Record the success rate the source claims for this technique.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claimed_success_rate": {
                "anyOf": [{"type": "number"}, {"type": "null"}],
                "description": "Fraction in [0,1], or null if no explicit rate is stated.",
            },
            "stated_as": {"type": "string", "description": "Exact source phrase, or why null."},
            "target_models_claimed": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["claimed_success_rate", "stated_as", "target_models_claimed", "confidence"],
        "additionalProperties": False,
    },
}


def load_candidates() -> list[dict]:
    """One row per primitive: pick the best source (arxiv > blog > hf)."""
    sql = """
    SELECT p.primitive_id, p.claimed_success_rate, p.title, p.family::text AS family,
           p.short_description, sp.source_type, sp.url
    FROM attack_primitives p JOIN source_provenances sp ON sp.primitive_id = p.primitive_id
    WHERE p.synthesized = false AND sp.source_type IN ('arxiv','blog','huggingface')
    """
    rank = {"arxiv": 0, "blog": 1, "huggingface": 2}
    best: dict[str, dict] = {}
    with ENGINE.connect() as c:
        for r in c.execute(text(sql)):
            d = dict(r._mapping)
            pid = d["primitive_id"]
            if pid not in best or rank[d["source_type"]] < rank[best[pid]["source_type"]]:
                best[pid] = d
    return list(best.values())


def estimate_cost(n: int) -> dict:
    in_tok = n * 10_000          # ~DOC_CHAR_CAP/4 markdown tokens per doc
    out_tok = n * 400
    # Sonnet 4.6 $3/$15 per 1M, Batch API = 50% off
    sonnet = (in_tok / 1e6 * 3 + out_tok / 1e6 * 15) * 0.5
    bd = n * 0.0015              # Web Unlocker ~ $1.5 / 1k requests
    return {"sonnet_batch_usd": round(sonnet, 2), "bright_data_usd": round(bd, 2),
            "total_usd": round(sonnet + bd, 2)}


def dry_run() -> None:
    cands = load_candidates()
    by_src = Counter(d["source_type"] for d in cands)
    have = sum(1 for d in cands if d["claimed_success_rate"] is not None)
    print(f"candidates (1 best-source per primitive): {len(cands)}")
    print(f"  by source_type: {dict(by_src)}")
    print(f"  already carry a claimed rate (will be RE-extracted for uniformity): {have}")
    print(f"  currently null (potential NEW claimed rates): {len(cands) - have}")
    print(f"\nplan: Bright Data web_unlock(markdown) each -> Sonnet 4.6 Batch API"
          f" (-50%) + prompt-cached instruction -> {RESULTS.name}")
    print(f"cost estimate: {estimate_cost(len(cands))}")
    print(f"\nrun the paid fetch+extract with:  --run   (writes {RESULTS}, NO DB write)")
    print(f"then review that JSON and apply with:  --apply")


async def _fetch_all(cands: list[dict]) -> dict[str, str]:
    """web_unlock each source URL -> {primitive_id: markdown}. Failures dropped."""
    from rogue.harvest.bright_data_client import BrightDataClient
    client = BrightDataClient.from_env()
    out: dict[str, str] = {}
    sem = asyncio.Semaphore(8)

    async def one(d: dict) -> None:
        async with sem:
            try:
                page = await client.web_unlock(d["url"], format="markdown")
                if page.status_code == 200 and page.content and len(page.content) > 200:
                    out[d["primitive_id"]] = page.content[:DOC_CHAR_CAP]
                else:
                    print(f"  fetch weak ({page.status_code}, {len(page.content or '')}b): {d['url'][:70]}")
            except Exception as e:  # noqa: BLE001
                print(f"  fetch FAIL {type(e).__name__}: {d['url'][:70]}")

    await asyncio.gather(*(one(d) for d in cands))
    aclose = getattr(client, "aclose", None)
    if aclose:
        await aclose()
    return out


def _request(d: dict, doc: str) -> dict:
    user = (
        f"PRIMITIVE\ntitle: {d['title']}\nfamily: {d['family']}\n"
        f"description: {d['short_description']}\n\nSOURCE MARKDOWN ({d['source_type']}, {d['url']}):\n{doc}"
    )
    return {
        "custom_id": d["primitive_id"],
        "params": {
            "model": MODEL,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            "tools": [EXTRACT_TOOL],
            "tool_choice": {"type": "tool", "name": "record_claimed_rate"},
            "messages": [{"role": "user", "content": user}],
        },
    }


async def run_extract() -> None:
    from anthropic import AsyncAnthropic
    cands = load_candidates()
    by_id = {d["primitive_id"]: d for d in cands}
    print(f"fetching {len(cands)} sources via Bright Data web_unlock …")
    docs = await _fetch_all(cands)
    print(f"fetched {len(docs)}/{len(cands)} OK")
    if not docs:
        print("nothing fetched; aborting before any LLM spend.")
        return

    client = AsyncAnthropic()
    requests = [_request(by_id[pid], doc) for pid, doc in docs.items()]
    batch = await client.messages.batches.create(requests=requests)
    print(f"submitted batch {batch.id} ({len(requests)} reqs); polling …")
    while True:
        b = await client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            print(f"batch ended: {b.request_counts}")
            break
        await asyncio.sleep(15)

    rows: list[dict] = []
    async for entry in await client.messages.batches.results(batch.id):
        d = by_id.get(entry.custom_id, {})
        rec = {"primitive_id": entry.custom_id, "source_type": d.get("source_type"),
               "url": d.get("url"), "title": d.get("title"),
               "old_claimed_rate": d.get("claimed_success_rate"),
               "new_claimed_rate": None, "stated_as": None, "target_models": [],
               "confidence": None, "ok": False}
        if getattr(entry.result, "type", None) == "succeeded":
            for block in entry.result.message.content or []:
                if getattr(block, "type", None) == "tool_use":
                    inp = dict(block.input)
                    v = inp.get("claimed_success_rate")
                    if isinstance(v, (int, float)) and not (0.0 <= v <= 1.0):
                        v = None  # out-of-range guard
                    rec.update(new_claimed_rate=v, stated_as=inp.get("stated_as"),
                               target_models=inp.get("target_models_claimed", []),
                               confidence=inp.get("confidence"), ok=True)
        rows.append(rec)

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(rows, indent=2))
    got = sum(1 for r in rows if r["new_claimed_rate"] is not None)
    newly = sum(1 for r in rows if r["new_claimed_rate"] is not None and r["old_claimed_rate"] is None)
    print(f"\nwrote {RESULTS}")
    print(f"  extracted a rate for {got}/{len(rows)} fetched primitives ({newly} NEWLY-claimed)")
    print(f"  review the JSON, then write to Neon with:  --apply")


def apply_to_db() -> None:
    if not RESULTS.exists():
        raise SystemExit(f"{RESULTS} not found — run --run first.")
    rows = json.loads(RESULTS.read_text())
    to_write = [r for r in rows if r["ok"] and r["new_claimed_rate"] is not None]
    print(f"{len(to_write)} primitives have a non-null extracted rate.")
    # back up current live values for exactly these primitives (reversible)
    ids = [r["primitive_id"] for r in to_write]
    with ENGINE.connect() as c:
        cur = {row[0]: row[1] for row in c.execute(
            text("SELECT primitive_id, claimed_success_rate FROM attack_primitives WHERE primitive_id = ANY(:ids)"),
            {"ids": ids})}
    BACKUP.write_text(json.dumps(cur, indent=2, default=str))
    print(f"backed up {len(cur)} current values -> {BACKUP}")
    changed = 0
    with ENGINE.begin() as c:
        for r in to_write:
            c.execute(text("UPDATE attack_primitives SET claimed_success_rate = :v WHERE primitive_id = :p"),
                      {"v": r["new_claimed_rate"], "p": r["primitive_id"]})
            changed += 1
    print(f"UPDATED claimed_success_rate on {changed} primitives in Neon.")
    print("re-run scripts/research/reproducibility_gap.py to refresh C2 with the larger n.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="PAID: fetch + Sonnet batch extract -> JSON")
    ap.add_argument("--apply", action="store_true", help="write reviewed JSON to live Neon")
    args = ap.parse_args()
    if args.apply:
        apply_to_db()
    elif args.run:
        asyncio.run(run_extract())
    else:
        dry_run()
