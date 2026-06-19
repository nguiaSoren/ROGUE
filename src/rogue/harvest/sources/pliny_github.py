"""Pliny / elder-plinius GitHub umbrella harvest plugin (source #7 in §5.1, new 2026-05-24 PM).

The highest-yield single author on jailbreak corpora. Two repos dominate:

  * **L1B3RT4S** (18.9k stars) — flat ``<ORG>.mkd`` files at the repo root, one
    per AI org (ANTHROPIC.mkd, OPENAI.mkd, GOOGLE.mkd, ...), plus aggregated
    ``%23MOTHERLOAD.txt``, ``%21SHORTCUTS.json``, ``%2ASPECIAL_TOKENS.json``,
    and ``-MISCELLANEOUS-.mkd``.
  * **CL4R1T4S** (26.3k stars) — leaked system prompts. Folder layout differs
    from L1B3RT4S so we discover its top-level via Scraping Browser, then
    Web Unlocker each ``.mkd`` we find.

Two harvest paths run on every daily invocation:

  1. **Direct-fetch (no SERP)** — the locked L1B3RT4S file list defined below.
     Every URL is built via :func:`urllib.parse.quote(filename, safe="")` —
     **never string concatenation**. The bare ``#`` in ``#MOTHERLOAD.txt``
     silently fails when treated as a URL fragment anchor; ``%23`` works.
     All four special-character files verified 2026-05-25 via direct browser
     test (§5.2 Source #7).
  2. **SERP-discovery** — ``site:github.com/elder-plinius updated:>{date}``
     catches every Pliny repo regardless of obfuscated name, then Web
     Unlocker fetches each repo's README + top-level markdowns.

  * **Primary product:** ``serp`` (discovery) + ``web_unlocker`` (per-file
    fetches). The class attribute records ``"serp"`` because that's the
    discovery-phase cost band; per-document fetches are stamped on the
    produced :class:`RawDocument`.
  * **Fallback:** none — if both paths fail, the source goes stale per §9.3.

Spec: ROGUE_PLAN.md §5.1 Source #7, §5.2 Source #7, §9.3 (Day-1 source plugin
checklist).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["PlinyGithubPlugin"]


# L1B3RT4S `<ORG>.mkd` files at repo root — verified 2026-05-24 via direct
# GitHub view (§5.2 Source #7). 34 files; refresh the list whenever Pliny
# commits a new ORG. Plain ASCII filenames; quote() is a no-op for these
# but we apply it uniformly so the URL builder has one code path.
L1B3RT4S_ORG_FILES: tuple[str, ...] = (
    "OPENAI.mkd",
    "ANTHROPIC.mkd",
    "GOOGLE.mkd",
    "META.mkd",
    "MISTRAL.mkd",
    "DEEPSEEK.mkd",
    "XAI.mkd",
    "MIDJOURNEY.mkd",
    "PERPLEXITY.mkd",
    "COHERE.mkd",
    "AMAZON.mkd",
    "MICROSOFT.mkd",
    "APPLE.mkd",
    "NVIDIA.mkd",
    "ALIBABA.mkd",
    "MOONSHOT.mkd",
    "INFLECTION.mkd",
    "LIQUIDAI.mkd",
    "NOUS.mkd",
    "REFLECTION.mkd",
    "REKA.mkd",
    "ZYPHRA.mkd",
    "ZAI.mkd",
    "BRAVE.mkd",
    "CHATGPT.mkd",
    "CURSOR.mkd",
    "FETCHAI.mkd",
    "GRAYSWAN.mkd",
    "GROK-MEGA.mkd",
    "HUME.mkd",
    "INCEPTION.mkd",
    "MULTION.mkd",
    "WINDSURF.mkd",
    "SYSTEMPROMPTS.mkd",
)

# Special-character files. Bare `#` in a URL is a fragment anchor — silently
# returns empty; `%23` works. Verified 2026-05-25 via direct browser test
# (§5.2 Source #7). NEVER replace these with string concatenation; always
# round-trip the *unencoded* name through quote(safe="") so the URL builder
# has exactly one code path.
L1B3RT4S_SPECIAL_FILES: tuple[str, ...] = (
    "#MOTHERLOAD.txt",
    "!SHORTCUTS.json",
    "*SPECIAL_TOKENS.json",
    "-MISCELLANEOUS-.mkd",
)

L1B3RT4S_RAW_PREFIX = "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/"
CL4R1T4S_BROWSE_URL = "https://github.com/elder-plinius/CL4R1T4S"
CL4R1T4S_RAW_PREFIX = "https://raw.githubusercontent.com/elder-plinius/CL4R1T4S/main/"
# GitHub Git Tree API — returns every path in the repo as a JSON list. No auth
# required for public repos (60 req/hr rate limit per IP, plenty for one
# daily harvest call). Originally added 2026-05-26 to fix CL4R1T4S discovery
# after GitHub's React tree-view redesign broke the regex scrape; extended
# to L1B3RT4S 2026-05-26 PM so newly-added Pliny files (e.g. TOKEN80M8.mkd,
# 1337.mkd) are picked up automatically without us updating the hardcoded
# list. Verified 2026-05-26: CL4R1T4S returns 67 files (filtered to 63);
# L1B3RT4S returns 44 files (filtered to 43, vs 38 hardcoded — +5 newer).
L1B3RT4S_TREE_API_URL = (
    "https://api.github.com/repos/elder-plinius/L1B3RT4S/git/trees/main"
    "?recursive=true"
)
CL4R1T4S_TREE_API_URL = (
    "https://api.github.com/repos/elder-plinius/CL4R1T4S/git/trees/main"
    "?recursive=true"
)
# Which extensions are "content files" worth Web-Unlocker fetching. Skip
# LICENSE, .gitignore, .gitattributes, etc. — those have no jailbreak value.
# Different per-repo because L1B3RT4S intentionally ships `.json` files that
# are jailbreak payloads (`!SHORTCUTS.json`, `*SPECIAL_TOKENS.json`),
# whereas CL4R1T4S has no jailbreak-content `.json` files.
L1B3RT4S_CONTENT_EXTENSIONS = frozenset({".mkd", ".md", ".txt", ".json"})
CL4R1T4S_CONTENT_EXTENSIONS = frozenset({".mkd", ".md", ".txt"})

# Filter the SERP "site:github.com/elder-plinius" results down to repo URLs
# (drop blob/issue/wiki paths).
PLINIUS_REPO_RE = re.compile(
    r"https?://github\.com/elder-plinius/([A-Za-z0-9_.-]+)/?$"
)


def _l1b3rt4s_raw_url(filename: str) -> str:
    """Build a raw.githubusercontent URL for one L1B3RT4S file.

    Uses :func:`urllib.parse.quote(filename, safe="")` so leading ``#`` / ``!``
    / ``*`` characters are %-encoded — bare ``#`` is a URL fragment anchor and
    causes Web Unlocker to silently return empty content (§5.2 Source #7,
    verified 2026-05-25 via direct browser test).
    """
    return L1B3RT4S_RAW_PREFIX + quote(filename, safe="")


def _cl4r1t4s_raw_url(path: str) -> str:
    """Build a raw.githubusercontent URL for one CL4R1T4S path.

    ``path`` may contain ``/`` (subdirectories) — preserve those by listing
    ``/`` in ``safe``; everything else goes through ``quote()`` to handle
    any leading-special-character files Pliny may add.
    """
    return CL4R1T4S_RAW_PREFIX + quote(path, safe="/")


class PlinyGithubPlugin(SourcePlugin):
    """Pliny / elder-plinius umbrella harvester (L1B3RT4S + CL4R1T4S + SERP)."""

    name = "pliny_github"
    source_type = "github"
    bright_data_product = "serp"  # discovery-phase cost band; per-doc → web_unlocker
    required_capabilities: frozenset[Capability] = frozenset({Capability.SERP, Capability.UNLOCK})

    def __init__(
        self,
        l1b3rt4s_files: tuple[str, ...] | None = None,
        l1b3rt4s_special_files: tuple[str, ...] | None = None,
        include_cl4r1t4s: bool = True,
        include_serp_discovery: bool = True,
    ) -> None:
        self.l1b3rt4s_files = (
            l1b3rt4s_files if l1b3rt4s_files is not None else L1B3RT4S_ORG_FILES
        )
        self.l1b3rt4s_special_files = (
            l1b3rt4s_special_files
            if l1b3rt4s_special_files is not None
            else L1B3RT4S_SPECIAL_FILES
        )
        self.include_cl4r1t4s = include_cl4r1t4s
        self.include_serp_discovery = include_serp_discovery

    def serp_queries(self, since: datetime) -> list[str]:
        """Pliny umbrella SERP query (docs/sources.md §7-new)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [f"site:github.com/elder-plinius updated:>{date_str}"]

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Three-phase fetch: L1B3RT4S direct, CL4R1T4S discovery, SERP umbrella."""
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        # --- 1. L1B3RT4S direct fetches (GitHub tree API + hardcoded fallback) ---
        # Tree-API path is primary: auto-picks up new files Pliny adds (e.g. as
        # of 2026-05-26 the API returns 5 files we hadn't hardcoded —
        # 1337.mkd, AAA.mkd, TOKEN80M8.mkd, TOKENADE.mkd, README.md). The
        # hardcoded ORG_FILES + SPECIAL_FILES tuples remain as a safety net
        # if the API rate-limits us (60 req/hr unauthed) or returns nothing.
        l1b_entries = await self._discover_l1b3rt4s_paths()
        if not l1b_entries:
            l1b_entries = [
                (f, "")
                for f in (list(self.l1b3rt4s_files) + list(self.l1b3rt4s_special_files))
            ]
            fetch_path_label = "l1b3rt4s_direct_fallback"
        else:
            fetch_path_label = "l1b3rt4s_tree_api"

        for filename, blob_sha in l1b_entries:
            url = _l1b3rt4s_raw_url(filename)
            # §11.7 Tier B — Pliny rewrites files in place, so the git blob SHA
            # (not a timestamp) is the right freshness token: unchanged SHA ⇒
            # skip the Web Unlocker fetch; an in-place rewrite changes the SHA.
            if self.should_skip_fetch(url, blob_sha or None):
                continue
            page = await self._safe_unlock(fetcher, url, fmt="markdown")
            if page is None or not page.content or len(page.content) < 10:
                # Empty body usually means the URL was treated as a fragment
                # anchor — confirm the call path went through quote() above
                # if this fires for a `%`-prefixed file. Silent failure mode.
                continue
            doc = self._build_doc(
                url=url,
                content=page.content,
                content_format="markdown",
                http_status=page.status_code,
                fetched_at=fetched_at,
                metadata={
                    "repo": "elder-plinius/L1B3RT4S",
                    "filename": filename,
                    "fetch_path": fetch_path_label,
                    "version_token": blob_sha or None,
                },
                discovered_via=None,
            )
            if doc is not None:
                docs.append(doc)

        # --- 2. CL4R1T4S discovery via GitHub Git Tree API (no auth needed) ---
        # Replaces the 2024-05-25 Scraping-Browser-on-tree-page approach which
        # broke silently when GitHub shipped the React tree-view redesign:
        # `/blob/main/*.mkd` href patterns no longer exist in static HTML,
        # so the regex matched 0 hits regardless of how many files were in
        # the repo. Verified 2026-05-26: tree API returns all 67 files;
        # filtering to {.mkd, .md, .txt} keeps 63 of them (drops LICENSE etc).
        if self.include_cl4r1t4s:
            for raw_path, blob_sha in await self._discover_cl4r1t4s_paths():
                url = _cl4r1t4s_raw_url(raw_path)
                # §11.7 Tier B — skip the fetch when the blob SHA is unchanged.
                if self.should_skip_fetch(url, blob_sha or None):
                    continue
                # `.md` and `.txt` formats render best as `markdown` through
                # Web Unlocker (raw text passthrough); `.mkd` does too — it's
                # GitHub-flavored markdown despite the unusual extension.
                page = await self._safe_unlock(fetcher, url, fmt="markdown")
                if page is None or not page.content or len(page.content) < 10:
                    continue
                doc = self._build_doc(
                    url=url,
                    content=page.content,
                    content_format="markdown",
                    http_status=page.status_code,
                    fetched_at=fetched_at,
                    metadata={
                        "repo": "elder-plinius/CL4R1T4S",
                        "path": raw_path,
                        "fetch_path": "cl4r1t4s_tree_api",
                        "version_token": blob_sha or None,
                    },
                    discovered_via="github_tree_api:CL4R1T4S",
                )
                if doc is not None:
                    docs.append(doc)

        # --- 3. SERP-umbrella discovery for any-Pliny-repo-updated ---
        if self.include_serp_discovery:
            seen_repos: set[str] = set()
            for query in self.serp_queries(since):
                try:
                    serp = await fetcher.serp(query)
                except NotImplementedError:
                    raise
                except Exception:
                    continue
                for result in serp.organic_results:
                    link = (
                        result.get("link")
                        or result.get("url")
                        or result.get("href")
                        or ""
                    )
                    m = PLINIUS_REPO_RE.search(link)
                    if not m:
                        continue
                    repo = m.group(1)
                    # Skip the two repos we already cover via direct paths
                    # above; SERP is for surfacing *new* obfuscated repos.
                    if repo in {"L1B3RT4S", "CL4R1T4S"}:
                        continue
                    if repo in seen_repos:
                        continue
                    seen_repos.add(repo)
                    readme_url = (
                        f"https://raw.githubusercontent.com/elder-plinius/{repo}"
                        "/main/README.md"
                    )
                    page = await self._safe_unlock(fetcher, readme_url, fmt="markdown")
                    if page is None or not page.content or len(page.content) < 10:
                        continue
                    doc = self._build_doc(
                        url=readme_url,
                        content=page.content,
                        content_format="markdown",
                        http_status=page.status_code,
                        fetched_at=fetched_at,
                        metadata={
                            "repo": f"elder-plinius/{repo}",
                            "fetch_path": "serp_discovered",
                        },
                        discovered_via=f"serp_query: {query}",
                    )
                    if doc is not None:
                        docs.append(doc)

        # ``since`` filtering relies on SERP's ``updated:>{date}`` predicate
        # for the discovery path; direct fetches are unconditional (Pliny
        # rewrites files in place, so timestamp-based filtering on raw URLs
        # would drop active content). Dedup happens at the dedup layer via
        # archive_hash.
        _ = since
        return docs

    @staticmethod
    async def _safe_unlock(
        fetcher: Fetcher,
        url: str,
        *,
        fmt: str,
    ):
        """Web Unlock that swallows transient errors but re-raises the
        NotImplementedError used by Day-0 stubs (so test scaffolds still
        surface unimplemented paths loudly)."""
        try:
            return await fetcher.unlock(url, format=fmt)
        except NotImplementedError:
            raise
        except Exception:
            return None

    @staticmethod
    async def _discover_l1b3rt4s_paths() -> list[tuple[str, str]]:
        """Same as ``_discover_cl4r1t4s_paths`` but for L1B3RT4S, filtering on
        ``L1B3RT4S_CONTENT_EXTENSIONS`` (includes ``.json`` because L1B3RT4S
        ships jailbreak payloads like ``!SHORTCUTS.json`` /
        ``*SPECIAL_TOKENS.json`` — CL4R1T4S doesn't). Returns ``(path, blob_sha)``
        pairs — the SHA is the §11.7 pre-fetch freshness token. [] on any error
        so the caller can fall back to the hardcoded list."""
        import httpx as _httpx

        try:
            async with _httpx.AsyncClient(
                timeout=_httpx.Timeout(30.0),
                headers={"Accept": "application/vnd.github+json"},
            ) as h:
                r = await h.get(L1B3RT4S_TREE_API_URL)
            if r.status_code != 200:
                return []
            tree = r.json().get("tree", [])
        except Exception:
            return []

        out: list[tuple[str, str]] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = str(entry.get("path", ""))
            if "." not in path:
                continue
            ext = "." + path.rsplit(".", 1)[-1].lower()
            if ext in L1B3RT4S_CONTENT_EXTENSIONS:
                out.append((path, str(entry.get("sha", ""))))
        return out

    @staticmethod
    async def _discover_cl4r1t4s_paths() -> list[tuple[str, str]]:
        """Return every content-file ``(path, blob_sha)`` in elder-plinius/CL4R1T4S
        via the GitHub Git Tree API. Public-repo endpoint, no auth needed;
        rate-limited to 60 req/hr per IP (one harvest call/day = far below the
        limit). The blob SHA is the §11.7 pre-fetch freshness token.

        Returns paths like ``"OPENAI/ChatGPT5-08-07-2025.mkd"``,
        ``"ANTHROPIC/Claude-3.5-Sonnet.txt"``, filtered to extensions in
        ``CL4R1T4S_CONTENT_EXTENSIONS``. Network failure → return [] (caller
        proceeds without CL4R1T4S content for this run; L1B3RT4S direct path
        and SERP discovery are unaffected).
        """
        import httpx as _httpx  # local import keeps the module import-safe

        try:
            async with _httpx.AsyncClient(
                timeout=_httpx.Timeout(30.0), headers={"Accept": "application/vnd.github+json"}
            ) as h:
                r = await h.get(CL4R1T4S_TREE_API_URL)
            if r.status_code != 200:
                return []
            tree = r.json().get("tree", [])
        except Exception:
            return []

        out: list[tuple[str, str]] = []
        for entry in tree:
            if entry.get("type") != "blob":
                continue
            path = str(entry.get("path", ""))
            if "." not in path:
                continue
            ext = "." + path.rsplit(".", 1)[-1].lower()
            if ext in CL4R1T4S_CONTENT_EXTENSIONS:
                out.append((path, str(entry.get("sha", ""))))
        return out

    @staticmethod
    def _build_doc(
        *,
        url: str,
        content: str,
        content_format: str,
        http_status: int,
        fetched_at: datetime,
        metadata: dict,
        discovered_via: str | None,
    ) -> RawDocument | None:
        """Construct one RawDocument; swallow validation errors (bad URL etc.)."""
        archive_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        try:
            return RawDocument(
                url=url,
                source_type="github",
                bright_data_product="web_unlocker",
                fetched_at=fetched_at,
                raw_content=content,
                content_format=content_format,  # type: ignore[arg-type]
                archive_hash=archive_hash,
                http_status=http_status,
                metadata=metadata,
                discovered_via=discovered_via,
            )
        except Exception:
            return None
