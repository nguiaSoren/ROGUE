#!/usr/bin/env python3
"""Pin each distilled-skill source URL to the commit SHA it was fetched at (P4 reproducibility).

The Wave-A team recorded GitHub `blob/<branch>/...` source URLs, but a branch ref is mutable
(`main` moves). For a camera-ready reproducibility claim every seed URL must resolve to the
exact bytes we distilled. This rewrites each shard's `provenance.source_skill_url` from
`blob/<branch>/<path>` to `blob/<sha>/<path>`, where <sha> is the LAST commit that touched
that file (so the link is immutable and points at the version that existed when fetched),
and records `source_url_branch` + `source_commit_sha` + `pinned` alongside.

Uses the authenticated `gh api` (5000/hr). Non-blob URLs (e.g. GitHub Pages github.io) are
left unpinned with `pinned: false` and a note; we try a github.io -> github.com fallback.

Re-run scripts/memory/assemble_distilled_fixture.py afterwards to regenerate the fixture
with the pinned provenance.

Usage:  uv run python scripts/memory/pin_distilled_sources.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARD_DIR = ROOT / "data" / "research" / "trace2skill_fixture"

BLOB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+?)/?$")


def last_commit_sha(owner: str, repo: str, path: str, branch: str) -> str | None:
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/commits?path={path}&sha={branch}&per_page=1",
             "--jq", ".[0].sha"],
            capture_output=True, text=True, timeout=30,
        )
        sha = out.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except Exception:
        return None


def pin_url(url: str) -> tuple[str, dict]:
    """Return (possibly-rewritten url, provenance-delta)."""
    m = BLOB.match(url)
    if m:
        owner, repo, branch, path = m.groups()
        sha = last_commit_sha(owner, repo, path, branch)
        if sha:
            pinned = f"https://github.com/{owner}/{repo}/blob/{sha}/{path}"
            return pinned, {"source_url_branch": url, "source_commit_sha": sha, "pinned": True}
        return url, {"pinned": False, "pin_note": "gh api could not resolve a commit sha"}
    # github.io (GitHub Pages) fallback: owner.github.io/repo/... -> github.com/owner/repo
    gh_io = re.match(r"^https://([^.]+)\.github\.io/([^/]+)/(.+?)/?$", url)
    if gh_io:
        owner, repo, rest = gh_io.groups()
        # Pages often drops a leading "skills/"; try the most likely SKILL.md path.
        cand_paths = [f"{rest}/SKILL.md", f"{rest}SKILL.md", f"{rest}"]
        for branch in ("main", "master"):
            for path in cand_paths:
                sha = last_commit_sha(owner, repo, path.strip("/"), branch)
                if sha:
                    pinned = f"https://github.com/{owner}/{repo}/blob/{sha}/{path.strip('/')}"
                    return pinned, {"source_url_pages": url, "source_commit_sha": sha,
                                    "pinned": True, "pin_note": "resolved from GitHub Pages URL"}
        return url, {"pinned": False, "pin_note": "GitHub Pages URL; underlying blob not resolved"}
    return url, {"pinned": False, "pin_note": "not a github blob/pages url"}


def main() -> int:
    shards = sorted(SHARD_DIR.glob("shard_*.json"))
    pinned_n, unpinned = 0, []
    for shard in shards:
        recs = json.loads(shard.read_text())
        for rec in recs:
            prov = rec.setdefault("provenance", {})
            url = prov.get("source_skill_url", "")
            new_url, delta = pin_url(url)
            prov["source_skill_url"] = new_url
            prov.update(delta)
            if delta.get("pinned"):
                pinned_n += 1
                print(f"  pinned  {rec['skill_id']:14} -> …/blob/{delta['source_commit_sha'][:10]}/…")
            else:
                unpinned.append((rec["skill_id"], url, delta.get("pin_note", "")))
                print(f"  UNPINNED {rec['skill_id']:14} {url}  ({delta.get('pin_note')})")
        shard.write_text(json.dumps(recs, indent=2, ensure_ascii=False))

    print(f"\npinned {pinned_n}/{pinned_n + len(unpinned)} source URLs")
    if unpinned:
        print("unpinned (left as-is, pinned=false):")
        for sid, url, note in unpinned:
            print(f"  - {sid}: {url}  [{note}]")
    print("\nNow re-run: uv run python scripts/memory/assemble_distilled_fixture.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
