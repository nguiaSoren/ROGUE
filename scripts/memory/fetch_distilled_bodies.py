#!/usr/bin/env python3
"""Fetch the SHA-pinned ORIGINAL source skill for any body-withheld distilled record.

A few distilled-skill fixtures do not redistribute their evolved body because the
upstream source skill carries no redistribution license (or a non-commercial one). For
those records the fixture keeps the authors' own metadata (the planted canary, the
recovery markers, and the SHA-pinned provenance URL) but drops ``original_md_with_canary``
and ``scrubbed_md``. This script re-fetches each upstream original from its pinned commit
so the record can be inspected and re-distilled locally, without this archive itself
redistributing third-party content under a license that does not permit it.

Note: the exact evolved-and-canary-injected body used in the experiment is not byte
reproducible (the distillation step is LLM-stochastic); the frozen leakage results in
``data/research/skill_leak_distilled_*.json`` are the record of that run. This script
fetches the upstream ORIGINAL for inspection and to support a fresh local re-distillation.

Standard library only. Run from the repo root or an unzipped supplement::

    python scripts/memory/fetch_distilled_bodies.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "memory" / "leakage_canaries_distilled.json"
OUT = ROOT / "data" / "research" / "trace2skill_fixture" / "_fetched"

_BLOB = re.compile(r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)")


def raw_url(blob_url: str) -> str | None:
    """github.com/OWNER/REPO/blob/SHA/path -> raw.githubusercontent.com/OWNER/REPO/SHA/path."""
    m = _BLOB.match(blob_url or "")
    if not m:
        return None
    owner, repo, sha, path = m.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"


def main() -> int:
    recs = json.loads(FIXTURE.read_text())
    withheld = [r for r in recs if r.get("body_withheld")]
    if not withheld:
        print("No body-withheld records; nothing to fetch.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{len(withheld)} body-withheld skill(s) (source license forbids redistributing a derived body):\n")
    rc = 0
    for r in withheld:
        sid = r["skill_id"]
        prov = r.get("provenance", {})
        url = prov.get("source_skill_url", "")
        raw = raw_url(url)
        print(f"== {sid} ==")
        print(f"   source : {url}")
        print(f"   reason : {r.get('body_withheld_reason', '')}")
        print(f"   canary : {r.get('canary_value')}")
        print(f"   markers: {r.get('recovery_markers')}")
        if not raw:
            print("   ERROR: source_skill_url is not a pinned github blob URL; cannot fetch.\n")
            rc = 1
            continue
        dest = OUT / f"{sid}.original.md"
        try:
            with urllib.request.urlopen(raw, timeout=30) as resp:  # noqa: S310 (pinned github raw URL)
                body = resp.read().decode("utf-8", "replace")
            dest.write_text(body)
            print(f"   fetched -> {dest.relative_to(ROOT)}  ({len(body)} bytes)")
            print("   to reconstruct the fixture body, inject the canary above into this")
            print("   original and re-run the distillation; the exact evolved body is")
            print("   LLM-stochastic and not byte-reproducible (see the frozen results).\n")
        except (urllib.error.URLError, OSError) as e:
            print(f"   ERROR fetching {raw}: {e}\n")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
