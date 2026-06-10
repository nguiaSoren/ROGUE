"""Build-08 skill-pool harvest — fetch pass (Web Unlocker).

Fetches a curated, diverse set of real pages discovered by the SERP pass and
saves each as markdown under tests/fixtures/memory/_raw/ with a provenance
manifest (_index.json). The skill extraction (writing skill_pool.json) is done
by a human-in-the-loop reading these raw files — this script only does the
grounded fetch + archive.

Run: uv run python scripts/harvest_skill_pool_fetch.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re

import dotenv

from rogue.harvest.bright_data_client import BrightDataClient

dotenv.load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"))

RAW = "tests/fixtures/memory/_raw"

# Curated fetch targets. raw.githubusercontent.com READMEs render as clean
# markdown through the Unlocker; docs/blog pages give procedural prose.
TARGETS: list[str] = [
    # --- agent-skill / claude-skill repos + docs ---
    "https://raw.githubusercontent.com/anthropics/skills/main/README.md",
    "https://raw.githubusercontent.com/ComposioHQ/awesome-claude-skills/main/README.md",
    "https://raw.githubusercontent.com/VoltAgent/awesome-agent-skills/main/README.md",
    "https://raw.githubusercontent.com/addyosmani/agent-skills/main/README.md",
    "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview",
    # --- cursor / windsurf rules ---
    "https://raw.githubusercontent.com/PatrickJS/awesome-cursorrules/main/README.md",
    "https://raw.githubusercontent.com/SchneiderSam/awesome-windsurfrules/main/README.md",
    "https://raw.githubusercontent.com/aurelia/aurelia/master/docs/user-docs/developer-guides/developing-with-ai/windsurf-rules-example.md",
    # --- agent tool recipes (langchain / crewai) ---
    "https://docs.crewai.com/en/learn/create-custom-tools",
    "https://www.langchain.com/blog/how-to-build-an-agent",
    # --- prompt-engineering patterns ---
    "https://raw.githubusercontent.com/dair-ai/prompt-engineering-guide/main/README.md",
    "https://raw.githubusercontent.com/promptslab/awesome-prompt-engineering/main/README.md",
    # --- code review / secure coding checklists ---
    "https://raw.githubusercontent.com/mgreiler/code-review-checklist/main/README.md",
    "https://raw.githubusercontent.com/mgreiler/secure-code-review-checklist/main/README.md",
    "https://google.github.io/eng-practices/review/reviewer/standard.html",
    "https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/stable-en/02-checklist/05-checklist",
    # --- web scraping / data cleaning recipes ---
    "https://blog.hartleybrody.com/web-scraping-boilerplate/",
    "https://medium.com/@hadiyolworld007/pandas-data-cleaning-cookbook-8-essential-techniques-for-real-world-messy-data-fa7c4bd88aa8",
    # --- git recovery / sql optimization ---
    "https://dev.to/zainaboyedeji/the-complete-git-commands-cheat-sheet-everything-you-need-to-know-4n9b",
    "https://www.geeksforgeeks.org/sql/best-practices-for-sql-query-optimizations/",
    # --- incident response / sre runbooks ---
    "https://sre.google/resources/practices-and-processes/incident-management-guide/",
    "https://emmer.dev/blog/an-effective-incident-runbook-template/",
    # --- react performance ---
    "https://blog.logrocket.com/a-complete-guide-to-react-performance-optimization/",
    # --- agent memory lessons-learned ---
    "https://towardsdatascience.com/a-practical-guide-to-memory-for-autonomous-llm-agents/",
    "https://ericmjl.github.io/blog/2026/1/18/how-to-build-self-improving-coding-agents-part-2/",
    "https://www.briancoords.com/agent-skills-are-the-markdown-files-ive-been-waiting-for/",
    # --- debugging playbooks ---
    "https://microsoft.github.io/code-with-engineering-playbook/engineering-fundamentals-checklist/",
    "https://raw.githubusercontent.com/wshobson/agents/main/docs/agent-skills.md",
]


def slugify(url: str) -> str:
    s = re.sub(r"^https?://", "", url)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:120]


async def main() -> None:
    client = BrightDataClient.from_env()
    manifest: list[dict] = []
    n_unlock = 0
    try:
        for url in TARGETS:
            slug = slugify(url)
            try:
                page = await client.web_unlock(url, format="markdown")
                n_unlock += 1
                content = page.content or ""
                fname = f"{slug}.md"
                with open(os.path.join(RAW, fname), "w") as f:
                    f.write(content)
                manifest.append(
                    {
                        "url": url,
                        "file": fname,
                        "status_code": page.status_code,
                        "content_len": len(content),
                        "fetched_at": page.fetched_at.isoformat(),
                    }
                )
                print(f"[{page.status_code} {len(content):6d}b] {url}")
            except Exception as e:  # noqa: BLE001
                print(f"[ERR] {url}: {e}")
                manifest.append({"url": url, "error": str(e)})
    finally:
        await client.aclose()

    with open(os.path.join(RAW, "_index.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nUnlocker fetches: {n_unlock}  (~${n_unlock * 0.0025:.4f})")
    print(f"Wrote {RAW}/_index.json")


if __name__ == "__main__":
    asyncio.run(main())
