"""GitHub search harvest plugin (source #5 in docs/sources.md).

Three-stage harvest:

  1. **SERP API** discovers repos matching curated queries — driven by the
     templates in ``docs/sources.md`` §5 (``site:github.com prompt-injection
     updated:>{date}`` etc.).
  2. **Web Unlocker** fetches each repo's README as markdown for the
     extraction layer.
  3. **NEW 2026-05-26 — conditional tree traversal**: if the README mentions
     any keyword in ``DEEP_TRAVERSAL_KEYWORDS`` (jailbreak / system-prompt
     leak terminology), additionally hit the GitHub Git Tree API to discover
     every content file in the repo and Web-Unlock each one (capped at
     ``DEEP_TRAVERSAL_MAX_FILES_PER_REPO`` to bound cost). Catches new
     CL4R1T4S-style leak collections that SERP discovers but the README-only
     path would only sample superficially.

  * **Primary product:** ``serp`` (for discovery) + ``web_unlocker`` (for the
    READMEs + deep-traversal content files). The :attr:`bright_data_product`
    class attribute records ``"serp"`` because that's what defines this
    plugin's discovery-phase cost band; per-document fetches via Web Unlocker
    are recorded on the produced :class:`RawDocument`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["GithubSearchPlugin", "DEEP_TRAVERSAL_KEYWORDS"]


logger = logging.getLogger(__name__)


# Match `https://github.com/<owner>/<repo>` (with optional trailing slash, path,
# or query). Anchored on the github.com host to avoid false positives on
# `gist.github.com` / raw.githubusercontent / api.github.com.
GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
)


# Trigger the deep tree traversal only if the README mentions one of these
# phrases (case-insensitive substring match). Tuned to be specific enough to
# avoid triggering on every random AI repo while catching the obvious
# leak/jailbreak repos. Add new entries here if a known leak collection
# slips through with a README that uses different vocabulary.
DEEP_TRAVERSAL_KEYWORDS: tuple[str, ...] = (
    "system prompt",
    "leaked prompt",
    "leaked system",
    "extracted prompt",
    "system message",
    "prompt injection",
    "indirect prompt injection",
    "jailbreak",
    "DAN prompt",
    "DAN jailbreak",
    "uncensored",
    "abliterated",
    "ablation",
    "weight modification",
    "guardrail bypass",
    "refusal bypass",
    "red team",
    "redteam",
    "adversarial prompt",
    "L1B3RT4S",   # name-recognition — Pliny-style clones
    "CL4R1T4S",
)
_DEEP_TRAVERSAL_RE = re.compile(
    "|".join(re.escape(k) for k in DEEP_TRAVERSAL_KEYWORDS),
    re.IGNORECASE,
)

# Cap content-file fetches per repo to bound cost — a discovered repo with
# 500 files would otherwise blow through Web Unlocker spend on a single
# SERP run. 30 is generous enough for CL4R1T4S-scale collections (which
# top out around 70 files) without runaway behavior on outliers.
DEEP_TRAVERSAL_MAX_FILES_PER_REPO = 30

# Which extensions are worth fetching during deep traversal — same as Pliny
# L1B3RT4S: markdown + text + json (json captures shortcut-table / token
# files like L1B3RT4S's !SHORTCUTS.json). Excludes README.md because we
# already fetched it in phase 2.
DEEP_TRAVERSAL_EXTENSIONS = frozenset({".md", ".mkd", ".txt", ".json"})


class GithubSearchPlugin(SourcePlugin):
    """SERP-driven GitHub repo READMEs harvester."""

    name = "github_search"
    source_type = "github"
    bright_data_product = "serp"

    def __init__(
        self,
        readme_branch_order: tuple[str, ...] = ("main",),
        enable_deep_traversal: bool = True,
        deep_traversal_max_files: int = DEEP_TRAVERSAL_MAX_FILES_PER_REPO,
    ) -> None:
        # REVIEW Day 1: Day-0 only tries `main`. About 15-20% of older repos
        # still have `master` as default branch — on Day 1, try `master` as a
        # second pass when the `main` fetch returns 404. Easiest tweak: change
        # the default tuple to ``("main", "master")`` and loop.
        self.readme_branch_order = readme_branch_order
        self.enable_deep_traversal = enable_deep_traversal
        self.deep_traversal_max_files = deep_traversal_max_files
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """GitHub SERP queries (docs/sources.md §5)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            f"site:github.com prompt-injection updated:>{date_str}",
            f"site:github.com jailbreak GPT OR Claude updated:>{date_str}",
            f'site:github.com "llm-attacks" OR "llm-security" updated:>{date_str}',
        ]

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        """SERP-discover repos → README → conditional deep tree traversal.

        Phase 1: SERP query → list of (owner, repo) tuples.
        Phase 2: Web-Unlock each repo's README as markdown.
        Phase 3 (NEW 2026-05-26): if README mentions any keyword in
            ``DEEP_TRAVERSAL_KEYWORDS``, hit GitHub Git Tree API + Web-Unlock
            every content file (up to ``deep_traversal_max_files``).
        """
        self.call_errors = []
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)
        seen_repos: set[tuple[str, str]] = set()

        for query in self.serp_queries(since):
            try:
                serp = await client.serp_search(query)
            except NotImplementedError:
                raise
            except Exception as exc:
                msg = f"serp_query={query!r}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("github_search SERP failed: %s", msg)
                continue

            for result in serp.organic_results:
                # SERP organic_results entries have at minimum a `link` field
                # (parsed_light shape from §6.1).
                # REVIEW Day 1: confirm the exact field name on the real
                # SerpResponse — could be `url`, `link`, or `href` depending on
                # parsed_light vs parsed_full. Fallback to all three here.
                link = (
                    result.get("link")
                    or result.get("url")
                    or result.get("href")
                    or ""
                )
                m = GITHUB_REPO_RE.search(link)
                if not m:
                    continue
                owner, repo = m.group(1), m.group(2)
                # Filter out obvious non-repo paths captured by the regex.
                if owner in {"orgs", "settings", "login", "topics"}:
                    continue
                if (owner, repo) in seen_repos:
                    continue
                seen_repos.add((owner, repo))

                for branch in self.readme_branch_order:
                    readme_url = (
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
                    )
                    try:
                        readme = await client.web_unlock(readme_url, format="markdown")
                    except NotImplementedError:
                        raise
                    except Exception:
                        continue

                    # Skip empty / 404 stubs that some Web Unlocker calls still
                    # return with 200 + a tiny error body.
                    if not readme.content or len(readme.content) < 10:
                        continue

                    raw_content = readme.content
                    archive_hash = hashlib.sha256(
                        raw_content.encode("utf-8")
                    ).hexdigest()
                    try:
                        docs.append(
                            RawDocument(
                                url=readme_url,
                                source_type=self.source_type,
                                bright_data_product="web_unlocker",
                                fetched_at=fetched_at,
                                raw_content=raw_content,
                                content_format="markdown",
                                archive_hash=archive_hash,
                                http_status=readme.status_code,
                                metadata={
                                    "repo": f"{owner}/{repo}",
                                    "owner": owner,
                                    "branch": branch,
                                    "repo_url": f"https://github.com/{owner}/{repo}",
                                    "fetch_path": "serp_readme",
                                },
                                discovered_via=f"serp_query: {query}",
                            )
                        )
                    except Exception:
                        continue
                    # Got README on this branch — don't try the next branch.

                    # --- Phase 3: conditional deep tree traversal ---
                    if self.enable_deep_traversal and _DEEP_TRAVERSAL_RE.search(raw_content):
                        deep_docs = await self._deep_traverse_repo(
                            client=client,
                            owner=owner,
                            repo=repo,
                            branch=branch,
                            fetched_at=fetched_at,
                            discovered_via=f"serp_query: {query}",
                        )
                        docs.extend(deep_docs)

                    break

        _ = since
        return docs

    async def _deep_traverse_repo(
        self,
        *,
        client: BrightDataClient,
        owner: str,
        repo: str,
        branch: str,
        fetched_at: datetime,
        discovered_via: str,
    ) -> list[RawDocument]:
        """Hit GitHub tree API + Web-Unlock every content file (capped).

        Skipped silently if the tree API rate-limits us (60 req/hr unauth) or
        the repo is private — the README we already emitted in phase 2 stays
        in the harvest output regardless.
        """
        paths = await self._fetch_repo_tree(owner, repo, branch)
        if not paths:
            return []

        # Filter to content extensions + cap. Skip README files (already fetched).
        kept: list[str] = []
        for p in paths:
            if "." not in p:
                continue
            ext = "." + p.rsplit(".", 1)[-1].lower()
            if ext not in DEEP_TRAVERSAL_EXTENSIONS:
                continue
            if p.lower() == "readme.md" or p.lower().endswith("/readme.md"):
                continue
            kept.append(p)
            if len(kept) >= self.deep_traversal_max_files:
                break

        out: list[RawDocument] = []
        from urllib.parse import quote

        for path in kept:
            raw_url = (
                f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
                + quote(path, safe="/")
            )
            try:
                page = await client.web_unlock(raw_url, format="markdown")
            except NotImplementedError:
                raise
            except Exception as exc:
                self.call_errors.append(
                    f"deep_traverse {owner}/{repo}/{path}: {type(exc).__name__}: {exc}"
                )
                continue
            if not page.content or len(page.content) < 10:
                continue
            archive_hash = hashlib.sha256(page.content.encode("utf-8")).hexdigest()
            try:
                out.append(
                    RawDocument(
                        url=raw_url,
                        source_type=self.source_type,
                        bright_data_product="web_unlocker",
                        fetched_at=fetched_at,
                        raw_content=page.content,
                        content_format="markdown",
                        archive_hash=archive_hash,
                        http_status=page.status_code,
                        metadata={
                            "repo": f"{owner}/{repo}",
                            "owner": owner,
                            "branch": branch,
                            "path": path,
                            "repo_url": f"https://github.com/{owner}/{repo}",
                            "fetch_path": "serp_deep_traversal",
                        },
                        discovered_via=discovered_via,
                    )
                )
            except Exception as exc:
                self.call_errors.append(
                    f"build_doc {owner}/{repo}/{path}: {type(exc).__name__}: {exc}"
                )
                continue
        return out

    @staticmethod
    async def _fetch_repo_tree(owner: str, repo: str, branch: str) -> list[str]:
        """GitHub Git Tree API → list of blob paths. [] on any error.

        Same pattern as the Pliny plugin's helpers. Public-repo endpoint, no
        auth needed. Rate-limited to 60 req/hr per IP — at most one call
        per SERP-discovered repo, well below the limit even on a backfill run.
        """
        import httpx as _httpx

        url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}"
            "?recursive=true"
        )
        try:
            async with _httpx.AsyncClient(
                timeout=_httpx.Timeout(30.0),
                headers={"Accept": "application/vnd.github+json"},
            ) as h:
                r = await h.get(url)
            if r.status_code != 200:
                return []
            tree = r.json().get("tree", [])
        except Exception:
            return []
        return [str(e.get("path", "")) for e in tree if e.get("type") == "blob"]
