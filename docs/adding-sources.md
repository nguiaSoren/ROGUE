# Add your own source

ROGUE's 19 open-web sources (see [`sources.md`](sources.md)) are not a fixed list — each one is a small plugin, and you can add your own to harvest from a forum, blog, repo, or feed ROGUE doesn't cover yet. A source is one subclass of `SourcePlugin`; it declares **what kind of fetch it needs**, and the harvest pipeline hands it a fetcher that performs the fetch, extracts the result into `AttackPrimitive`s, deduplicates, and routes it through the rest of the pipeline like any built-in source.

## The contract

Every source subclasses [`SourcePlugin`](../src/rogue/harvest/sources/base.py) and sets four class attributes + one method:

| field | what it is |
|---|---|
| `name` | short stable id (`"my_forum"`) — used by the cost log + dashboard freshness panel |
| `source_type` | a `rogue.schemas.SourceType` literal stamped on every doc (`"blog"`, `"reddit"`, `"github"`, …) |
| `bright_data_product` | the telemetry/cost-log bucket the fetch falls under (no longer a dispatch key — purely for accounting) |
| `required_capabilities` | the `Capability` members this source needs to fetch. The orchestrator resolves a fetcher per capability and **skips the source with a warning** if any are unavailable, so a misconfigured source degrades instead of crashing the run |
| `async fetch_since(fetcher, since)` | the one method you implement — return `0..N` `RawDocument`s published after `since` |

The fetcher is **injected** — your source never constructs its own HTTP client. It declares the capability it needs (e.g. `Capability.UNLOCK` to pull a page, `Capability.SERP` to run a search), and receives a fetcher that satisfies it. That's the line the abstraction draws: your plugin owns **what the content means** (parse it, decide which part is the attack); the fetcher owns **how the bytes arrive**.

## A minimal source

Harvest a static page (a blog or forum index that lists jailbreaks):

```python
import hashlib
from datetime import datetime, timezone

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.harvest.sources.base import SourcePlugin
from rogue.schemas.raw_document import RawDocument


class MyForumPlugin(SourcePlugin):
    name = "my_forum"
    source_type = "blog"                         # a rogue.schemas.SourceType literal
    bright_data_product = "web_unlocker"         # telemetry/cost-log tag only
    required_capabilities = frozenset({Capability.UNLOCK})

    PAGES = ["https://my-forum.example/jailbreaks"]

    async def fetch_since(self, fetcher: Fetcher, since: datetime) -> list[RawDocument]:
        docs: list[RawDocument] = []
        for url in self.PAGES:
            try:
                body = await fetcher.unlock(url, format="markdown")
            except Exception:
                continue   # NEVER raise — one bad page must not kill the harvest run
            docs.append(
                RawDocument(
                    url=url,
                    source_type=self.source_type,
                    bright_data_product=self.bright_data_product,
                    fetched_at=datetime.now(timezone.utc),
                    raw_content=body,
                    content_format="markdown",
                    archive_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    http_status=200,
                )
            )
        return docs
```

That's the whole source. The extraction agent downstream turns each `RawDocument` into structured `AttackPrimitive`s — you don't parse attacks yourself, you just deliver the raw page.

## Register it

Add an instance to `default_plugins()` in [`src/rogue/harvest/discovery_agent.py`](../src/rogue/harvest/discovery_agent.py):

```python
def default_plugins() -> list[SourcePlugin]:
    return [
        ArxivListingPlugin(),
        BlogStaticPlugin(),
        MyForumPlugin(),          # ← your source
        # …
    ]
```

The next `uv run python scripts/harvest/harvest_once.py --since 1d` will fetch, extract, dedupe, and persist from it alongside the built-ins.

## Two things that matter

- **Respect `since`.** For a source with per-item timestamps (a feed, a subreddit, a commit list), compare each item's `posted_at` / `published_at` to `since` and drop anything older — `since` is a timezone-aware UTC datetime. A static page with no timestamps (like the example) can ignore it and rely on the content-hash dedup gate to skip unchanged pulls.
- **Never raise from `fetch_since`.** Swallow and log any per-document failure. The harvest run sweeps many sources; one bad URL or parse error must not take the others down. The list you return is "what I could fetch this run," not "all or nothing."

## Capabilities, briefly

`required_capabilities` is how a source says *what kind of fetch it needs* without caring how it's performed: `UNLOCK` (fetch one page), `SERP` (run a search query), and the platform-specific ones (`REDDIT`, `X`, `HF`) for sources that pull from those. Declare only what you use; the orchestrator wires a fetcher for each and skips your source with a warning if a capability isn't available in the current run, so a source that needs something the deployment can't provide fails soft instead of crashing.

## Multimodal note

If your source carries images (a screenshot of a jailbreak, a typographic-attack image), the same content-semantics decision applies as for any image source: **is the image itself the attack, or does it carry attack text you need to read out of it?** That's your plugin's call (and the extraction layer's) — declare you need image bytes, fetch them, and represent them accordingly. The fetch mechanism is orthogonal to that interpretation; the "what does this image mean" decision lives in the source, above the fetch.
