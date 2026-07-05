#!/usr/bin/env python3
"""Crawl real upstream GitHub ``SKILL.md`` files and plant deterministic canaries into
them, to GROW the leakage canary panel past what the bundled fixtures supply.

Why: P4's "alignment, not scale" headline rests on the per-canary paired contrast
(permissive finetune vs instruct, same base). With only 40 bundled canaries the paired
test is underpowered. The bundled real-doc supply (skill_pool 55 + distilled 20) caps a
clean run at ~63; to reach N=100 with REAL docs (not carrier reuse) we source fresh
upstream skills here. Each is a real, third-party-authored ``SKILL.md`` — strictly
stronger construct validity than a synthetic carrier.

Reproducibility: every file is fetched by its **git blob SHA** (content-addressed), so the
record pins the exact bytes regardless of later branch movement. Every canary choice
(type, value, injection site, scrub) is the deterministic ``plant_canaries`` machinery,
namespaced by a fresh per-skill id. Re-running yields byte-identical canary records for the
same candidate set.

Discovery is GitHub code search (``gh api search/code``); we dedup by repo (<=2/repo) and by
content hash, skip the repos the distilled set already used, filter to 300-2000 chars
(comparable to the bundled canary docs), and take the first ``--target`` that pass.

Usage:  uv run python scripts/memory/crawl_realskill_canaries.py --target 60
Output: tests/fixtures/memory/leakage_canaries_realskill.json  (validated canary records)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "memory"))
from plant_canaries import (  # noqa: E402
    _canary_type_for, build_canary, inject_canary, scrub,
)

OUT = ROOT / "tests" / "fixtures" / "memory" / "leakage_canaries_realskill.json"

# Repos the bundled distilled set already drew from — skip for source independence.
_SEEN_REPOS = {"stripe/ai", "vercel-labs/slack-agent-skill", "openai/skills",
               "yuyz0112/public-api-skills"}

# Discovery queries, ordered for diversity (different slices of the SKILL.md ecosystem).
_QUERIES = [
    "filename:SKILL.md path:skills",
    "filename:SKILL.md",
    "filename:skill.md path:.claude",
    "filename:SKILL.md agent",
    "filename:SKILL.md path:.claude/skills",
    "filename:SKILL.md anthropic",
    "filename:SKILL.md description tools",
    "filename:SKILL.md workflow",
]
_PAGES = 3  # pages per query (100/page) -> up to 2400 raw hits before dedup

MIN_LEN, MAX_LEN = 300, 2600


def gh_json(args: list[str]) -> dict | list | None:
    try:
        out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=45)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def search_candidates(per_query: int) -> list[dict]:
    """Return [{owner,repo,path,blob_sha,html_url}] deduped by repo (<=2) + path."""
    seen_repo: dict[str, int] = {}
    seen_key: set[tuple] = set()
    out: list[dict] = []
    for q in _QUERIES:
        items: list[dict] = []
        for page in range(1, _PAGES + 1):
            res = gh_json(["-X", "GET", "search/code", "-f", f"q={q}",
                           "-f", "per_page=100", "-f", f"page={page}"])
            batch = (res or {}).get("items", []) if isinstance(res, dict) else []
            items.extend(batch)
            if len(batch) < 100:
                break
        print(f"  query {q!r}: {len(items)} hits")
        for it in items:
            repo_full = it.get("repository", {}).get("full_name", "")
            owner = it.get("repository", {}).get("owner", {}).get("login", "")
            name = it.get("repository", {}).get("name", "")
            path = it.get("path", "")
            blob = it.get("sha", "")
            key = (repo_full, path)
            if not (repo_full and blob and path) or repo_full in _SEEN_REPOS:
                continue
            if key in seen_key or seen_repo.get(repo_full, 0) >= 2:
                continue
            seen_key.add(key)
            seen_repo[repo_full] = seen_repo.get(repo_full, 0) + 1
            out.append({"owner": owner, "repo": name, "path": path,
                        "blob_sha": blob, "html_url": it.get("html_url", "")})
            if len(out) >= per_query * len(_QUERIES):
                break
    return out


def fetch_blob(owner: str, repo: str, blob_sha: str) -> str | None:
    """Content-addressed fetch by blob sha (pins exact bytes)."""
    res = gh_json([f"repos/{owner}/{repo}/git/blobs/{blob_sha}"])
    if not isinstance(res, dict) or res.get("encoding") != "base64":
        return None
    try:
        return base64.b64decode(res["content"]).decode("utf-8", "replace")
    except Exception:
        return None


def is_usable(body: str) -> bool:
    if not (MIN_LEN <= len(body) <= MAX_LEN):
        return False
    # plausibly English prose (ascii-dominant) and not a placeholder stub
    ascii_frac = sum(c.isascii() for c in body) / len(body)
    if ascii_frac < 0.95:
        return False
    low = body.lower()
    if "lorem ipsum" in low or low.count("todo") > 3:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=60, help="how many real-skill canaries to mint")
    args = ap.parse_args()

    print("discovering SKILL.md candidates via gh code search…")
    cands = search_candidates(per_query=max(40, args.target))
    print(f"  {len(cands)} repo-deduped candidates\n")

    print("fetching bodies (content-addressed by blob sha) + filtering…")
    records: list[dict] = []
    content_hashes: set[str] = set()
    for c in cands:
        if len(records) >= args.target:
            break
        body = fetch_blob(c["owner"], c["repo"], c["blob_sha"])
        if not body or not is_usable(body):
            continue
        chash = hashlib.sha256(body.encode()).hexdigest()
        if chash in content_hashes:
            continue
        content_hashes.add(chash)

        idx = len(records) + 1
        skill_id = f"rsk-{idx:03d}"
        ctype = _canary_type_for(skill_id)
        canary_value, markers = build_canary(skill_id, ctype)
        original = inject_canary(body.rstrip(), ctype, canary_value)
        scrubbed = scrub(original, canary_value, ctype)
        # Integrity: planted, recoverable in original, absent from shared body.
        if canary_value not in original or canary_value in scrubbed or "[REDACTED]" not in scrubbed:
            continue
        if any(m not in original for m in markers):
            continue
        records.append({
            "skill_id": skill_id,
            "canary_type": ctype,
            "canary_value": canary_value,
            "original_md_with_canary": original,
            "scrubbed_md": scrubbed,
            "recovery_markers": markers,
            "provenance": {
                "source_skill_url": c["html_url"],
                "source_repo": f"{c['owner']}/{c['repo']}",
                "source_path": c["path"],
                "source_blob_sha": c["blob_sha"],
                "kind": "real_upstream_skill",
                "pinned": True,
            },
        })
        print(f"  {skill_id}  {ctype:18}  {len(body):>4}B  {c['owner']}/{c['repo']}/{c['path']}")

    if len(records) < args.target:
        print(f"\nWARN: only minted {len(records)}/{args.target} (raise candidate pool or relax filter)")
    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {len(records)} real-skill canary records -> {OUT.relative_to(ROOT)}")
    repos = {r["provenance"]["source_repo"] for r in records}
    print(f"distinct source repos: {len(repos)}")
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
