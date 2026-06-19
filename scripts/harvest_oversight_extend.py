"""Extension harvest for the oversight answer-key corpus (axes 1-4).

Adds: authoritative court/regulatory primary sources (court-record aggregators
that BD WILL fetch -- .gov is hard-blocked by BD policy on BOTH Unlocker and
Scraping Browser, so primary sources come from courtlistener/justia/casetext +
reputable named-incident coverage), stronger concrete APPROVE incidents
(adjudicated-legitimate disputes / chargebacks the merchant won), and the new
fraud sub-patterns (APP fraud, invoice/mandate fraud, deepfake-CEO/vishing,
friendly-fraud, payroll diversion, double-brokering).

Government .gov domains are blocked by Bright Data -> we use scrape_browser for
the JS/anti-bot court-aggregator domains and web_unlock for the rest. Appends
to tests/fixtures/oversight/_raw/. Costs real BD money -- run once.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import dotenv

dotenv.load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

# BD browser customer-id env already carries the 'brd-customer-' prefix; the
# client re-adds it, so strip it here to avoid a doubled prefix in the WSS auth.
_cid = os.environ.get("BRIGHTDATA_BROWSER_CUSTOMER_ID", "")
if _cid.startswith("brd-customer-"):
    os.environ["BRIGHTDATA_BROWSER_CUSTOMER_ID"] = _cid[len("brd-customer-"):]

from rogue.harvest.bright_data_client import BrightDataClient  # noqa: E402

OUT = Path("tests/fixtures/oversight/_raw")
OUT.mkdir(parents=True, exist_ok=True)

# Queries chosen for: (1) authoritative court/primary records of NAMED incidents,
# (2) concrete legitimate-transaction / merchant-won-chargeback APPROVE cases,
# (3) the new sub-patterns. case_class is one of the 3 allowed values.
QUERIES: list[tuple[str, str]] = [
    # --- authoritative primary / court-record (axis 1) ---
    ("large_wire", "business email compromise wire fraud indictment court record"),
    ("large_wire", "deepfake CEO voice vishing wire transfer fraud case named company"),
    ("vendor_change", "vendor impersonation invoice fraud guilty plea court case"),
    ("large_wire", "authorized push payment scam victim case named bank reimbursed"),
    ("high_value_refund", "refund fraud ring indictment sentenced court record"),
    # --- stronger concrete APPROVE incidents (axis 2) ---
    ("high_value_refund", "chargeback merchant won dispute representment evidence legitimate transaction"),
    ("high_value_refund", "arbitration chargeback merchant prevailed compelling evidence delivered"),
    ("large_wire", "court ruled wire transfer authorized payment valid bank liability"),
    ("vendor_change", "vendor bank change verified callback legitimate confirmed genuine"),
    # --- new sub-patterns (axis 3) ---
    ("large_wire", "payroll diversion direct deposit fraud case example employee"),
    ("vendor_change", "double brokering freight fraud carrier payment case"),
    ("large_wire", "mandate fraud bank details change real case UK loss"),
    ("high_value_refund", "first party fraud friendly fraud chargeback abuse case study"),
    ("large_wire", "invoice redirection fraud council company real case amount lost"),
]

# Domains we deliberately try via the Scraping Browser first (JS / anti-bot /
# court aggregators). web_unlock is the default for ordinary article pages.
BROWSER_DOMAINS = (
    "courtlistener.com", "justia.com", "casetext.com", "law.justia.com",
    "documentcloud.org", "pacermonitor.com", "unicourt.com", "courthousenews.com",
)
# .gov is BD-blocked (both products); never attempt -> saves spend + avoids
# polluting the index with access-denied errors.
GOV_BLOCKED = (".gov", "gov.uk", "europa.eu", "sec.gov", "ic3.gov", "fbi.gov")
SKIP = ("youtube.com", "facebook.com", "twitter.com", "x.com", "linkedin.com",
        "/login", "pinterest.", "instagram.com")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def _is_gov(link: str) -> bool:
    return any(g in link for g in GOV_BLOCKED)


def _use_browser(link: str) -> bool:
    return any(d in link for d in BROWSER_DOMAINS)


async def main() -> None:
    client = BrightDataClient.from_env()
    serp_count = unlock_count = browser_count = 0
    index_path = OUT / "_index_extend.json"
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
            picked = 0
            for r in results:
                if picked >= 4:
                    break
                link = r.get("link") or r.get("url")
                title = r.get("title", "")
                if not link or not link.startswith("http"):
                    continue
                if _is_gov(link):
                    print(f"  -- skip gov (BD-blocked): {link}")
                    continue
                if any(b in link for b in SKIP):
                    continue
                fname = OUT / f"ext__{_slug(case_class)}__{_slug(title or link)}.md"
                if fname.exists():
                    picked += 1
                    continue
                via = "browser" if _use_browser(link) else "unlock"
                print(f"  -> {via}: {link}")
                content = ""
                status = None
                try:
                    if via == "browser":
                        page = await client.scrape_browser(link)
                        content = page.rendered_text or ""
                        status = "browser"
                        browser_count += 1
                    else:
                        page = await client.web_unlock(link, format="markdown")
                        content = page.content or ""
                        status = page.status_code
                        unlock_count += 1
                except Exception as e:  # noqa: BLE001
                    print(f"     fetch FAILED ({via}): {str(e)[:140]}")
                    # If unlock returned junk for a court page, try browser once.
                    if via == "unlock" and _use_browser(link):
                        pass
                    continue
                picked += 1
                if len(content) < 400:
                    print(f"     thin content ({len(content)} chars) — kept but flag")
                fname.write_text(
                    f"<!-- case_class: {case_class} -->\n"
                    f"<!-- source_url: {link} -->\n"
                    f"<!-- title: {title} -->\n"
                    f"<!-- via: {via} -->\n"
                    f"<!-- status: {status} -->\n\n" + content,
                    encoding="utf-8",
                )
                index.append({
                    "case_class": case_class, "query": query, "url": link,
                    "title": title, "file": str(fname), "via": via,
                    "status": status, "content_len": len(content),
                })
    finally:
        await client.aclose()

    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"\n\nDONE. SERP={serp_count} unlock={unlock_count} browser={browser_count}  "
          f"est spend=${serp_count*0.0015 + unlock_count*0.0025 + browser_count*0.01:.4f}")
    print(f"Index: {index_path} ({len(index)} pages)")


if __name__ == "__main__":
    asyncio.run(main())
