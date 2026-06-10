"""Build-08 skill-pool harvest — SERP discovery pass.

Runs a spread of agent-skill / rules / recipe / playbook queries through the
Bright Data SERP API and dumps the organic results (title + link) to a JSON
file so the (separate) fetch pass can pick real pages to Web-Unlock.

Run: uv run python scripts/harvest_skill_pool_serp.py
"""

from __future__ import annotations

import asyncio
import json
import os

import dotenv

from rogue.harvest.bright_data_client import BrightDataClient

dotenv.load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

QUERIES = [
    "awesome claude skills github",
    "claude agent skills examples markdown repository",
    "agent skill library markdown github",
    "cursor rules examples repository github",
    "windsurf rules examples github",
    "LLM agent tool recipe example langchain",
    "crewai custom tool example python",
    "agent memory lessons learned example writeup",
    "AI agent playbook skill markdown github",
    "prompt engineering patterns library github",
    "claude code skills SKILL.md examples",
    "debugging playbook checklist engineering",
    "web scraping best practices python recipe",
    "code review checklist best practices github",
    "data cleaning pandas recipe cookbook",
    "git recovery commands cheatsheet recipe",
    "sql query optimization tips recipe",
    "incident response runbook sre playbook",
    "react performance optimization patterns",
    "secure coding owasp checklist recipe",
]


async def main() -> None:
    client = BrightDataClient.from_env()
    out: list[dict] = []
    try:
        for q in QUERIES:
            try:
                resp = await client.serp_search(q, count=10)
                org = [
                    {"title": r.get("title"), "link": r.get("link")}
                    for r in resp.organic_results
                    if r.get("link")
                ]
                out.append({"query": q, "results": org})
                print(f"[{len(org):2d}] {q}")
            except Exception as e:  # noqa: BLE001
                print(f"[ERR] {q}: {e}")
                out.append({"query": q, "results": [], "error": str(e)})
    finally:
        await client.aclose()

    path = "tests/fixtures/memory/_raw/_serp_discovery.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote {path} ({len(QUERIES)} queries)")


if __name__ == "__main__":
    asyncio.run(main())
