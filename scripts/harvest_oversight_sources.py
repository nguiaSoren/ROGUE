"""One-off harvest for build-area 07 (Surface 2 human-gate answer key).

Runs a small set of SERP queries against the 3 financial-ops oversight
case-classes, then Web-Unlocks the most promising organic results so the
operator can extract REAL, source-cited GatedCase facts from the fetched
page text. Writes raw fetched pages to tests/fixtures/oversight/_raw/ for
offline extraction. Costs real BD money — run once, deliberately.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import dotenv

dotenv.load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402

OUT = Path("tests/fixtures/oversight/_raw")
OUT.mkdir(parents=True, exist_ok=True)

# (case_class, query) — adapt as results suggest. Kept to ~15 SERP queries.
QUERIES: list[tuple[str, str]] = [
    ("large_wire", "business email compromise real case example wire transfer"),
    ("large_wire", "authorized push payment fraud case example bank"),
    ("large_wire", "FBI IC3 BEC wire fraud case example amount recovered"),
    ("large_wire", "legitimate large wire transfer verified callback procedure example"),
    ("large_wire", "CEO fraud wire transfer red flags case study"),
    ("high_value_refund", "refund fraud scheme case example retailer"),
    ("high_value_refund", "friendly fraud chargeback case example legitimate refund"),
    ("high_value_refund", "refund abuse fraud ring arrested case example amount"),
    ("high_value_refund", "legitimate refund within policy matching order verification example"),
    ("vendor_change", "vendor bank account change fraud case example"),
    ("vendor_change", "supplier impersonation fake bank change request fraud case"),
    ("vendor_change", "how to verify legitimate vendor bank change request out of band callback"),
    ("vendor_change", "accounts payable vendor banking detail change fraud case study"),
    ("vendor_change", "legitimate supplier bank detail update verified example"),
]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


async def main() -> None:
    client = BrightDataClient.from_env()
    serp_count = 0
    fetch_count = 0
    index: list[dict] = []
    try:
        for case_class, query in QUERIES:
            print(f"\n=== SERP [{case_class}] {query!r} ===")
            try:
                resp = await client.serp_search(query, count=10, engine="google")
            except Exception as e:  # noqa: BLE001
                print(f"  SERP FAILED: {e}")
                continue
            serp_count += 1
            results = resp.organic_results or []
            print(f"  {len(results)} organic results")
            # Take up to 4 links per query (budget ~ 14 queries x ~4 = up to 56 fetches)
            picked = 0
            for r in results:
                if picked >= 4:
                    break
                link = r.get("link") or r.get("url")
                title = r.get("title", "")
                if not link or not link.startswith("http"):
                    continue
                # Skip obvious junk / aggregators / login-walled
                if any(b in link for b in ("youtube.com", "facebook.com", "twitter.com",
                                           "linkedin.com", "/login", "pinterest.")):
                    continue
                fname = OUT / f"{_slug(case_class)}__{_slug(title or link)}.md"
                if fname.exists():
                    picked += 1
                    continue
                print(f"  -> unlock: {link}")
                try:
                    page = await client.web_unlock(link, format="markdown")
                except Exception as e:  # noqa: BLE001
                    print(f"     fetch FAILED: {e}")
                    continue
                fetch_count += 1
                picked += 1
                content = page.content or ""
                fname.write_text(
                    f"<!-- case_class: {case_class} -->\n"
                    f"<!-- source_url: {link} -->\n"
                    f"<!-- title: {title} -->\n"
                    f"<!-- status_code: {page.status_code} -->\n\n"
                    + content,
                    encoding="utf-8",
                )
                index.append({
                    "case_class": case_class,
                    "query": query,
                    "url": link,
                    "title": title,
                    "file": str(fname),
                    "status_code": page.status_code,
                    "content_len": len(content),
                })
    finally:
        await client.aclose()

    (OUT / "_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\n\nDONE. SERP queries={serp_count}  fetches={fetch_count}  "
          f"est spend=${serp_count*0.0015 + fetch_count*0.0025:.4f}")
    print(f"Index: {OUT / '_index.json'} ({len(index)} pages)")


if __name__ == "__main__":
    asyncio.run(main())
