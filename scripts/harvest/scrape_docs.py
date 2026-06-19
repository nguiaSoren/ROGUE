"""
┌────────────────────────────────────────────────────────────────────┐
│  INPUT: a starting URL (e.g. .../serp-api/introduction)            │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │ STEP 1 — Probe: does {url}.md exist?        │
        │   curl -sI {url}.md → 200 + markdown?       │
        └─────────────────────────────────────────────┘
                  │                              │
              YES │                              │ NO
                  ▼                              ▼
  ┌─────────────────────────────────────┐  ┌──────────────────────────────┐
  │ STEP 2a — Find URL list             │  │ STEP 3 — Fallback: HTML      │
  │                                     │  │   Playwright + html→md       │
  │ Try in order:                       │  │   (clicks tabs, converts)    │
  │  1. Known AI-docs index files:      │  └──────────────────────────────┘
  │       /llms.txt                     │
  │       /llms-full.txt                │
  │       /.well-known/llms.txt         │
  │       /llm.txt, /ai-docs.txt        │
  │  2. Known sitemap paths:            │
  │       /sitemap.xml                  │
  │       /sitemap_index.xml            │
  │       /docs/sitemap.xml             │
  │  3. /robots.txt → follow            │
  │       Sitemap: lines                │
  │  4. Crawl from start URL (BFS)      │
  └─────────────────────────────────────┘
                  │
                  ▼
  ┌─────────────────────────────────────┐
  │ STEP 2b — Filter URLs               │
  │   keep only ones under              │
  │   the same section path             │
  │   as the input URL                  │
  └─────────────────────────────────────┘
                  │
                  ▼
  ┌─────────────────────────────────────┐
  │ STEP 2c — Download each             │
  │   as {url}.md, save into            │
  │   ROOT/SECTION_NAME/                │
  └─────────────────────────────────────┘


Reusable docs scraper.

Usage:
    python scrape_docs.py <start_url> [output_root]

Example:
    python scrape_docs.py https://docs.brightdata.com/scraping-automation/serp-api/introduction
    python scrape_docs.py https://docs.example.com/api/foo /Users/me/Desktop/docs

Strategy (fastest → slowest):
  1. Probe {url}.md — if Mintlify-style raw markdown is exposed, use it.
     a. Look for /llms.txt to discover all .md URLs
     b. Fall back to /sitemap.xml
     c. Fall back to crawling links from the start page
  2. If no .md endpoint, use Playwright to render HTML and convert to markdown.
"""

import sys
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse, urljoin


# ───────────────────────── helpers ─────────────────────────

def fetch(url, timeout=15):
    """GET a URL as text. Returns None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "docs-scraper/1.0"})
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="replace")
    except Exception:
        return None


def looks_like_markdown(text):
    """Heuristic: does this text look like real markdown, not an HTML page?"""
    if not text or len(text) < 100:
        return False
    if text.lstrip().startswith("<"):  # HTML
        return False
    # Look for typical markdown signals
    signals = 0
    if re.search(r"^#{1,6} ", text, re.MULTILINE): signals += 1
    if "```" in text: signals += 1
    if re.search(r"^\* |^- |^\d+\. ", text, re.MULTILINE): signals += 1
    return signals >= 1

def derive_section(start_url):
    """
    Figure out the section folder from any of these input forms:
      .../scraping-automation/serp-api                  → section = 'serp-api'
      .../scraping-automation/serp-api/                 → section = 'serp-api'
      .../scraping-automation/serp-api/introduction     → section = 'serp-api'
      .../scraping-automation/serp-api/introduction/    → section = 'serp-api'

    Heuristic: probe for common child pages under {url}. If any exist,
    the input is a section root → use the last segment as the section.
    Otherwise it's a leaf page → use the parent segment.
    """
    url = start_url.rstrip("/")
    path = urlparse(url).path
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "docs", "/"

    # Probe for common child page names. If any return markdown, this is a section root.
    common_children = ["introduction", "quickstart", "overview", "getting-started", "intro"]
    is_section_root = False
    for child in common_children:
        probe = fetch(f"{url}/{child}.md")
        if probe and looks_like_markdown(probe):
            is_section_root = True
            break

    if is_section_root:
        # URL points to a section → folder = last segment
        section = parts[-1]
        prefix = "/" + "/".join(parts) + "/"
    elif len(parts) >= 2:
        # URL is a leaf page → folder = parent segment
        section = parts[-2]
        prefix = "/" + "/".join(parts[:-1]) + "/"
    else:
        section = parts[-1]
        prefix = "/" + section + "/"

    return section, prefix


def slug_from_url(url, section):
    """Turn a URL into a flat filename, keyed off the section name."""
    path = urlparse(url).path.rstrip("/")
    tail = path.split(f"/{section}/", 1)
    if len(tail) == 2:
        flat = tail[1]
    else:
        flat = path.split("/")[-1] or "index"
    return flat.replace("/", "_").replace(".md", "")


# ───────────────────────── URL discovery ─────────────────────────
# ───────────────────────── URL discovery ─────────────────────────

# Known AI-docs index conventions, in order of preference
INDEX_CANDIDATES = [
    "/llms.txt",
    "/llms-full.txt",
    "/.well-known/llms.txt",
    "/ai-docs.txt",          # seen occasionally
    "/llm.txt",              # singular variant some sites use
]

# Known sitemap locations, in order of preference
SITEMAP_CANDIDATES = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/docs/sitemap.xml",
]


def find_index_file(base):
    """Try known AI-docs index conventions. Return (url, content) or (None, None)."""
    for path in INDEX_CANDIDATES:
        url = urljoin(base, path)
        content = fetch(url)
        if content and (".md" in content or "http" in content):
            print(f"  ✓ found index at {path}")
            return url, content
    return None, None


def find_sitemap(base):
    """
    Try known sitemap paths, then fall back to robots.txt which is
    REQUIRED by spec to advertise sitemaps via `Sitemap: <url>` lines.
    """
    # First: try common paths directly
    for path in SITEMAP_CANDIDATES:
        url = urljoin(base, path)
        xml = fetch(url)
        if xml and "<urlset" in xml or (xml and "<sitemapindex" in xml):
            print(f"  ✓ found sitemap at {path}")
            return xml

    # Second: ask robots.txt where the sitemap lives
    robots = fetch(urljoin(base, "/robots.txt"))
    if robots:
        matches = re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
        for sitemap_url in matches:
            xml = fetch(sitemap_url)
            if xml and ("<urlset" in xml or "<sitemapindex" in xml):
                print(f"  ✓ found sitemap via robots.txt: {sitemap_url}")
                return xml

    return None


def expand_sitemap_index(xml, base):
    """If this is a sitemap *index* (points to other sitemaps), fetch them all."""
    if "<sitemapindex" not in xml:
        return xml
    sub_urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    combined = []
    for sub_url in sub_urls:
        sub_xml = fetch(sub_url)
        if sub_xml:
            combined.append(sub_xml)
    return "\n".join(combined)


def urls_from_index(base, section):
    """Pull URLs from whatever index file the site exposes."""
    _, txt = find_index_file(base)
    if not txt:
        return []
    # Grab anything URL-ish that ends in .md (or any URL if no .md found)
    md_urls = re.findall(r"https?://[^\s)<>\"']+\.md", txt)
    if md_urls:
        return [u for u in md_urls if f"/{section}/" in u and "/cn/" not in u]
    # Some index files list bare URLs without .md — return those and let
    # the caller append .md when fetching
    all_urls = re.findall(r"https?://[^\s)<>\"']+", txt)
    return [u for u in all_urls if f"/{section}/" in u and "/cn/" not in u]


def urls_from_sitemap(base, section_prefix):
    """Parse any discovered sitemap for URLs under our section path."""
    xml = find_sitemap(base)
    if not xml:
        return []
    xml = expand_sitemap_index(xml, base)
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    return [u for u in urls if section_prefix in urlparse(u).path and "/cn/" not in u]

def urls_from_crawl(start_url, section_prefix, max_pages=200):
    """Last-resort: BFS-crawl links staying under the section prefix."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  (skipping crawl fallback — install beautifulsoup4 to enable)")
        return []
    seen, queue, found = {start_url}, [start_url], set()
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        html = fetch(url)
        if not html:
            continue
        found.add(url)
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            if section_prefix in urlparse(link).path and link not in seen:
                seen.add(link)
                queue.append(link)
    return sorted(found)


# ───────────────────────── fast path: .md endpoints ─────────────────────────

def run_md_path(start_url, out_dir, section, section_prefix):
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"

    print("→ Discovering URLs...")
    urls = urls_from_index(base, section)
    source = "llms.txt"
    if not urls:
        urls = [u + ".md" for u in urls_from_sitemap(base, section_prefix)]
        source = "sitemap.xml"
    if not urls:
        urls = [u + ".md" for u in urls_from_crawl(start_url, section_prefix)]
        source = "crawl"

    urls = sorted(set(urls))
    if not urls:
        print("  ✗ no URLs found via any method")
        return False

    print(f"  ✓ {len(urls)} URLs from {source}\n")

    with open(f"{out_dir}/urls.txt", "w") as f:
        f.write("\n".join(urls))

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        content = fetch(url)
        if not content or not looks_like_markdown(content):
            print(f"  ✗ not markdown, skipping")
            continue
        # Preserve URL hierarchy as nested folders
        relative = url.split(f"/{section}/", 1)[-1]         # e.g. 'query-parameters/google.md'
        if not relative.endswith(".md"):
            relative += ".md"
        file_path = os.path.join(out_dir, relative)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)
        print(f"  ✓ saved {relative} ({len(content):,} chars)")
    return True


# ───────────────────────── slow path: HTML + Playwright ─────────────────────────

def run_html_path(start_url, out_dir, section, section_prefix):
    try:
        from playwright.sync_api import sync_playwright
        from markdownify import markdownify as md
    except ImportError:
        print("  ✗ HTML fallback needs: pip install playwright markdownify && playwright install chromium")
        return False

    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
    urls = urls_from_sitemap(base, section_prefix) or urls_from_crawl(start_url, section_prefix)
    urls = sorted(set(urls))
    if not urls:
        print("  ✗ no URLs found")
        return False

    print(f"  ✓ {len(urls)} URLs to render via Playwright\n")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15000)

        for i, url in enumerate(urls, 1):
            print(f"[{i}/{len(urls)}] {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1500)

                # Expand every tab so all code variants render into the DOM
                for group in page.query_selector_all('[role="tablist"]'):
                    for tab in group.query_selector_all('[role="tab"]'):
                        try:
                            tab.click(timeout=2000)
                            page.wait_for_timeout(150)
                        except Exception:
                            pass

                main = page.query_selector("main") or page.query_selector("article")
                html = main.inner_html() if main else page.content()

                markdown = md(
                    html, heading_style="ATX", code_language="",
                    strip=["script", "style", "svg", "button"],
                )
                markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()

                name = slug_from_url(url, section) + ".md"
                with open(f"{out_dir}/{name}", "w") as f:
                    f.write(markdown)
                print(f"  ✓ saved {name} ({len(markdown):,} chars)")
            except Exception as e:
                print(f"  ✗ failed: {e}")
        browser.close()
    return True


# ───────────────────────── orchestrator ─────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape_docs.py <start_url> [output_root]")
        sys.exit(1)

    start_url = sys.argv[1].rstrip("/")
    out_root = sys.argv[2] if len(sys.argv) > 2 else "/Users/soren/Desktop/ROGUE/website"

    section, section_prefix = derive_section(start_url)
    out_dir = os.path.join(out_root, section.upper())
    os.makedirs(out_dir, exist_ok=True)
    print(f"Section: {section}   →   {out_dir}")
    print(f"Filter prefix: {section_prefix}\n")

    # Step 1: confirm raw .md is supported by probing a known-good child
    print("→ Step 1: probing for raw .md endpoint...")
    base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"

    # Try the input itself, then common children if it's a section root
    probe_urls = [start_url + ".md"] + [
        f"{start_url}/{c}.md" for c in ["introduction", "quickstart", "overview"]
    ]
    md_supported = any(
        (p := fetch(u)) and looks_like_markdown(p)
        for u in probe_urls
    )

    if md_supported:
        print("  ✓ raw markdown available — taking fast path\n")
        ok = run_md_path(start_url, out_dir, section, section_prefix)
    else:
        print("  ✗ no raw markdown — falling back to HTML rendering\n")
        ok = run_html_path(start_url, out_dir, section, section_prefix)

    print("\nDone." if ok else "\nFinished with errors.")


if __name__ == "__main__":
    # python scrape_docs.py https://docs.brightdata.com/scraping-automation/serp-api/introduction
    # python scrape_docs.py https://docs.brightdata.com/scraping-automation/serp-api
    # python scrape_docs.py https://docs.brightdata.com/ai/mcp-server
    # python scrape_docs.py https://docs.brightdata.com/scraping-automation/web-unlocker/
    main()