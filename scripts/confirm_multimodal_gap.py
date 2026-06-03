#!/usr/bin/env python
"""One-off (#1b confirm): how many multimodal-attack arXiv papers does ROGUE's
text-biased discovery miss? Runs a few multimodal-targeted SERP queries via the
real Bright Data SERP client, collects unique arXiv IDs, and diffs them against
the IDs ROGUE has actually SEEN (source_provenances) — turning the internal-bias
diagnosis into an external number. ~5 SERP queries ≈ $0.008. Read-only on the DB.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402

QUERIES = [
    'site:arxiv.org "vision-language" jailbreak',
    'site:arxiv.org multimodal jailbreak LLM',
    'site:arxiv.org "cross-modal" jailbreak attack',
    'site:arxiv.org typographic attack VLM',
    'site:arxiv.org audio jailbreak language model',
]
_ARXIV_ID = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)


def seen_arxiv_ids() -> set[str]:
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(os.environ["DATABASE_URL"])
    ids: set[str] = set()
    with e.connect() as c:
        for (u,) in c.execute(text("SELECT url FROM source_provenances WHERE url LIKE '%arxiv%'")):
            m = _ARXIV_ID.search(u or "")
            if m:
                ids.add(m.group(1))
        for (u,) in c.execute(text("SELECT source_url FROM attack_strategies WHERE source_url LIKE '%arxiv%'")):
            m = _ARXIV_ID.search(u or "")
            if m:
                ids.add(m.group(1))
    return ids


async def main() -> int:
    seen = seen_arxiv_ids()
    print(f"ROGUE has SEEN {len(seen)} unique arXiv IDs (provenance + strategies)\n")

    client = BrightDataClient.from_env()
    found: dict[str, tuple[str, str]] = {}  # id -> (title, query)
    try:
        for q in QUERIES:
            resp = await client.serp_search(q, count=20)
            hits = []
            for r in resp.organic_results:
                link = (r.get("link") or r.get("url") or "") if isinstance(r, dict) else ""
                title = (r.get("title") or "") if isinstance(r, dict) else ""
                m = _ARXIV_ID.search(link)
                if m:
                    aid = m.group(1)
                    hits.append(aid)
                    found.setdefault(aid, (title[:70], q))
            print(f"  {q}")
            print(f"    -> {len(resp.organic_results)} organic, {len(set(hits))} unique arXiv ids")
    finally:
        await client.aclose() if hasattr(client, "aclose") else None

    missed = {aid: v for aid, v in found.items() if aid not in seen}
    have = {aid: v for aid, v in found.items() if aid in seen}
    print("\n" + "=" * 72)
    print(f"unique multimodal-attack arXiv papers surfaced : {len(found)}")
    print(f"  already SEEN by ROGUE                        : {len(have)}")
    print(f"  MISSED (in SERP, never seen by ROGUE)        : {len(missed)}")
    print("\nMISSED papers (the gap):")
    for aid, (title, q) in sorted(missed.items()):
        print(f"  {aid}  {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
