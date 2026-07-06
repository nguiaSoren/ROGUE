#!/usr/bin/env python3
"""Lint LaTeX for the control-word space-gobbling bug (chktex Warning 1 class).

The bug: a user-defined parameterless TEXT macro (e.g. \\sysname -> "ROGUE")
used as `\\sysname is` renders "ROGUEis", because TeX discards whitespace after
a control word. Canonical fix: load `xspace` and define the macro with a
trailing \\xspace (adds a space before a word, not before punctuation), OR write
`\\sysname{} is` / `\\sysname\\ is` at the call site.
Ref (crawl4ai, 2026-06-27): texfaq.org/FAQ-xspace, "Commands gobble following space".

This linter flags ONLY user-defined parameterless macros whose definition lacks
\\xspace and that are USED followed by whitespace+letter (the gobbling pattern).
It deliberately ignores built-ins (\\emph{...}, \\noindent, ...) to keep the
false-positive rate near zero. It also parses any \\input'd file (e.g.
authormeta.tex) so a macro defined there is still resolved.

Usage:
  uv run python scripts/research/lint_latex_spacing.py <file.tex> [<file.tex> ...]
  # exit code 1 if any gobbling use is found, 0 if clean.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEF_RE = re.compile(
    r"\\(?:new|renew|provide)command\*?\s*\{?\\(\w+)\}?\s*(\[\d+\])?\s*\{(.*?)\}",
    re.DOTALL,
)
DEF_RE_DEF = re.compile(r"\\def\\(\w+)\s*\{(.*?)\}", re.DOTALL)


def collect_macros(text: str) -> dict[str, dict]:
    """name -> {nargs, has_xspace}. Only parameterless text macros are risky."""
    macros: dict[str, dict] = {}
    for m in DEF_RE.finditer(text):
        name, nargs, body = m.group(1), m.group(2), m.group(3)
        n = int(nargs[1:-1]) if nargs else 0
        macros[name] = {"nargs": n, "has_xspace": "\\xspace" in body, "body": body}
    for m in DEF_RE_DEF.finditer(text):
        name, body = m.group(1), m.group(2)
        macros.setdefault(name, {"nargs": 0, "has_xspace": "\\xspace" in body, "body": body})
    return macros


def resolve_inputs(path: Path, text: str) -> str:
    """Append the text of any \\input'd / \\include'd sibling .tex so macros
    defined there (authormeta.tex) are visible to the macro collector."""
    extra = ""
    for m in re.finditer(r"\\(?:input|include)\s*\{([^}]+)\}", text):
        name = m.group(1).strip()
        cand = (path.parent / name)
        for p in (cand, cand.with_suffix(".tex")):
            if p.exists():
                extra += "\n" + p.read_text(errors="ignore")
                break
    return extra


def lint(path: Path) -> list[str]:
    text = path.read_text(errors="ignore")
    full = text + resolve_inputs(path, text)
    macros = collect_macros(full)
    # risky = parameterless, text-producing (body has a letter), no xspace
    risky = {
        name for name, d in macros.items()
        if d["nargs"] == 0 and not d["has_xspace"] and re.search(r"[A-Za-z]", d["body"])
    }
    findings = []
    lines = text.splitlines()
    for name in sorted(risky):
        # \name  followed by whitespace (incl newline) then a letter == gobble
        use_re = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z@])[ \t]*(?:\n[ \t]*)?[ \t]([A-Za-z])")
        # simpler: \name + >=1 space/newline + letter
        use_re = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z@])\s+[A-Za-z]")
        for i, line in enumerate(lines, 1):
            for um in use_re.finditer(line):
                ctx = line[max(0, um.start() - 20): um.start() + 30].strip()
                findings.append(f"{path}:{i}: \\{name} gobbles trailing space -> '...{ctx}...'  (add \\xspace to def, or \\{name}{{}} at use)")
    return findings


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]]
    if not files:
        print(__doc__)
        return 2
    total = 0
    for f in files:
        if not f.exists():
            print(f"MISSING {f}")
            continue
        found = lint(f)
        if found:
            total += len(found)
            print("\n".join(found))
        else:
            print(f"OK  {f}  (no space-gobbling macro uses)")
    print(f"\n== {total} gobbling use(s) across {len(files)} file(s) ==")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
