#!/usr/bin/env python3
"""Citation forensics via crawl4ai (NOT WebFetch/web-search).

Why crawl4ai and not WebFetch: WebFetch routes the page through a small
summarizer model that hallucinates and even *echoes the prompt's expected
answer back* (proven on the 2026-06-27 P4 pass: it reported a "corrected"
title that did not exist and missed an IEEE Access DOI that was sitting in
the arXiv `Journal-ref` field). crawl4ai returns the raw page markdown, so
the comparison is against ground-truth bytes, not a model's paraphrase.

This script is the deterministic *evidence* half of citation forensics: it
crawls each cite's arXiv abstract page and prints the real Title / Authors /
Comments / Journal-ref / DOI / Subjects next to the .bib values. The
*judgment* half (does the title match? does the source support the claim the
prose makes?) is for the reader/agent that consumes this output.

Usage:
  uv run python scripts/research/verify_citations_crawl4ai.py <bib> [--key KEY ...]
  uv run python scripts/research/verify_citations_crawl4ai.py docs/research/publishing/p4_skill_leak/references.bib
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path


def parse_bib(text: str) -> list[dict]:
    """Minimal BibTeX entry parser (no external dep). Returns list of dicts
    with keys: _key, _type, and the lowercased fields we care about."""
    entries = []
    # split on @type{key, ... } at top level (entries do not nest @)
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),", text):
        etype, key = m.group(1), m.group(2).strip()
        start = m.end()
        # find the matching close brace for this entry
        depth = 1
        i = m.start(0)
        # walk from the opening brace
        brace_open = text.find("{", m.start(0))
        i = brace_open + 1
        depth = 1
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[start:i - 1]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*", body):
            fname = fm.group(1).lower()
            rest = body[fm.end():].lstrip()
            if not rest:
                continue
            if rest[0] == "{":
                d = 1
                j = 1
                while j < len(rest) and d > 0:
                    if rest[j] == "{":
                        d += 1
                    elif rest[j] == "}":
                        d -= 1
                    j += 1
                val = rest[1:j - 1]
            elif rest[0] == '"':
                j = rest.find('"', 1)
                val = rest[1:j]
            else:
                val = re.split(r"[,\n]", rest, 1)[0]
            fields[fname] = " ".join(val.split())
        fields["_key"] = key
        fields["_type"] = etype.lower()
        entries.append(fields)
    return entries


def extract_arxiv_fields(md: str) -> dict:
    """Pull the canonical fields out of an arXiv /abs/ page markdown."""
    out = {"title": None, "authors": None, "comments": None,
           "journal_ref": None, "doi": None, "subjects": None, "abstract": None}
    # abstract: arxiv renders it as a single blockquote line "> Abstract:..."
    mabs = re.search(r"^>\s*Abstract:\s*(.+)$", md, re.MULTILINE)
    if mabs:
        abs = re.sub(r"\s+", " ", mabs.group(1)).strip()
        out["abstract"] = abs[:1600] + ("..." if len(abs) > 1600 else "")
    for line in md.splitlines():
        s = line.strip()
        mt = re.search(r"Title:\s*(.+)$", s)
        if mt and out["title"] is None and s.startswith("#"):
            out["title"] = mt.group(1).strip()
        ma = re.search(r"Authors:\s*(.+)$", s)
        if ma and out["authors"] is None:
            names = re.findall(r"\[([^\]]+)\]\(https://arxiv\.org/search", line)
            out["authors"] = ", ".join(names) if names else ma.group(1).strip()
        for field, label in (("comments", "Comments"), ("journal_ref", "Journal-ref"),
                             ("doi", "DOI"), ("subjects", "Subjects")):
            mc = re.search(rf"\|\s*{label}:\s*\|\s*(.+?)\s*\|", line)
            if mc and out[field] is None:
                out[field] = re.sub(r"\s+", " ", mc.group(1)).strip()
    return out


async def crawl_one(crawler, url: str) -> dict:
    r = await crawler.arun(url=url)
    if not r.success:
        return {"_error": f"crawl failed: {getattr(r, 'error_message', 'unknown')}"}
    return extract_arxiv_fields(r.markdown or "")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bib", type=Path)
    ap.add_argument("--key", action="append", default=None,
                    help="restrict to these cite keys (repeatable)")
    args = ap.parse_args()

    entries = parse_bib(args.bib.read_text())
    if args.key:
        wanted = set(args.key)
        entries = [e for e in entries if e["_key"] in wanted]
    if not entries:
        print("no matching entries", file=sys.stderr)
        return 2

    from crawl4ai import AsyncWebCrawler

    print(f"# Citation forensics (crawl4ai) — {args.bib}")
    print(f"# {len(entries)} entr{'y' if len(entries)==1 else 'ies'}\n")

    async with AsyncWebCrawler(verbose=False) as crawler:
        for e in entries:
            eprint = e.get("eprint")
            print("=" * 72)
            print(f"KEY: {e['_key']}  (@{e['_type']})")
            print(f"  BIB title  : {e.get('title','')}")
            print(f"  BIB author : {e.get('author','')}")
            print(f"  BIB venue  : {e.get('booktitle') or e.get('journal') or e.get('note','')}")
            print(f"  BIB doi    : {e.get('doi','')}")
            print(f"  BIB eprint : {eprint or '(none)'}")
            if not eprint:
                print("  CRAWL      : SKIPPED (no arXiv eprint — verify venue/DOI by hand)")
                continue
            url = f"https://arxiv.org/abs/{eprint}"
            got = await crawl_one(crawler, url)
            if "_error" in got:
                print(f"  CRAWL      : {got['_error']}  ({url})")
                continue
            print(f"  REAL title : {got['title']}")
            print(f"  REAL author: {got['authors']}")
            print(f"  REAL comm. : {got['comments']}")
            print(f"  REAL j-ref : {got['journal_ref']}")
            print(f"  REAL doi   : {got['doi']}")
            print(f"  REAL subj  : {got['subjects']}")
            print(f"  REAL abstr : {got['abstract']}")
        print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
