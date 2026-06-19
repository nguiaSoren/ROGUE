"""Surface 2 reviewer-page generator — turn the corpus into a clickable HTML gate.

Reads the designed-label corpus, strips each case to **FACTS ONLY** (``case_id``,
``case_class``, ``facts``), and writes a single self-contained ``oversight_review.html``
(inline CSS + JS, zero external deps/CDN) that a human opens by double-click — NO dev
server, NO build step (CLAUDE.md no-dev-server rule). The reviewer clicks APPROVE /
DENY through every case and downloads ``oversight_decisions.json``; that file is then
scored against the on-disk answer key by ``run_gate_measurement.py --mode decisions``
to produce the REAL false-approve rate.

MEASUREMENT-VALIDITY INVARIANT (ADR-0011, build 07 §1/§4):
The page embeds **FACTS ONLY**. The answer-key fields — ``designed_label``,
``designed_rationale``, ``source_refs`` — are NEVER shipped to the page; showing them
biases the decision and destroys the measurement. The label stays in the corpus on
disk and is joined only at SCORING time. This mirrors the cockpit's HARD RULE
(``cockpit.py``): surface structured facts to CHECK, never prose to PERSUADE, never a
verdict. ``_strip_to_facts`` + ``_assert_no_answer_key`` enforce this in the generator
so a leaky page cannot be emitted.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
from pathlib import Path
from typing import Any

# Defensive `src/` insert so the script runs without the editable install on path
# (mirrors run_gate_measurement.py). No DB, no network, no money — pure file I/O.
_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from rogue.oversight.case_corpus import GatedCase, load_corpus  # noqa: E402

# The ONLY fields allowed onto the page. Anything else (designed_label,
# designed_rationale, label_provenance, source_refs) is the answer key and must
# never leave the corpus on disk.
_ALLOWED_PAGE_KEYS: frozenset[str] = frozenset({"case_id", "case_class", "facts"})
_FORBIDDEN_KEYS: tuple[str, ...] = (
    "designed_label",
    "designed_rationale",
    "label_provenance",
    "source_refs",
)


def _strip_to_facts(case: GatedCase) -> dict[str, Any]:
    """Project a ``GatedCase`` to the FACTS-ONLY shape shipped to the page.

    Returns exactly ``{case_id, case_class, facts}`` — never any answer-key field.
    """
    return {
        "case_id": case.case_id,
        "case_class": case.case_class,
        "facts": dict(case.facts),
    }


def _assert_no_answer_key(payload: list[dict[str, Any]]) -> None:
    """Hard guard: the page payload must carry FACTS ONLY (ADR-0011).

    Fails loudly if any record has a key outside ``{case_id, case_class, facts}`` or
    if the JSON serialization contains a known answer-key field name — the page must
    never embed ``designed_label`` / ``designed_rationale`` / ``source_refs``.
    """
    for rec in payload:
        extra = set(rec.keys()) - _ALLOWED_PAGE_KEYS
        if extra:
            raise AssertionError(
                f"case {rec.get('case_id', '?')!r} would ship answer-key field(s) "
                f"{sorted(extra)} to the page; only {sorted(_ALLOWED_PAGE_KEYS)} are "
                f"allowed (ADR-0011 — the label is the answer key, joined at scoring)"
            )
    serialized = json.dumps(payload)
    for forbidden in _FORBIDDEN_KEYS:
        if forbidden in serialized:
            raise AssertionError(
                f"page payload contains forbidden answer-key token {forbidden!r}; "
                f"refusing to emit a measurement-invalidating page (ADR-0011)"
            )


# Preferred display order for the facts strip (keys not listed fall to the end,
# alphabetically — so a new corpus key still renders, just after the known ones).
_FACT_KEY_ORDER: tuple[str, ...] = (
    "amount",
    "dollar_amount",
    "parties",
    "request_type",
    "what_was_flagged",
    "verification_done",
    "verification_steps",
    "channel",
    "domains_involved",
    "date",
    "year",
    "outcome",
)


def _build_payload(cases: list[GatedCase]) -> list[dict[str, Any]]:
    """Strip every case to facts-only and assert no answer-key leakage."""
    payload = [_strip_to_facts(c) for c in cases]
    _assert_no_answer_key(payload)
    return payload


def _render_html(payload: list[dict[str, Any]], *, corpus_label: str) -> str:
    """Render the self-contained reviewer page. ``payload`` is FACTS ONLY."""
    cases_json = json.dumps(payload, ensure_ascii=False, indent=2)
    key_order_json = json.dumps(list(_FACT_KEY_ORDER))
    n = len(payload)
    safe_label = html.escape(corpus_label)

    # CSS and JS are intentionally inline (no CDN, no build) so the file opens
    # offline by double-click. {{ }} escape literal braces inside the f-string.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex,nofollow" />
<title>ROGUE — Human Gate review ({n} cases)</title>
<style>
  :root {{
    --bg: #0c0e12; --panel: #14171d; --panel-2: #1b1f27; --line: #262b35;
    --ink: #e7eaf0; --ink-dim: #9aa3b2; --ink-faint: #6b7384;
    --approve: #2f9e63; --approve-2: #3fb877; --deny: #d9534f; --deny-2: #e36b67;
    --accent: #5b8cff; --chip: #232834;
    --radius: 14px; --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; }}
  body {{
    background: var(--bg); color: var(--ink); font-family: var(--sans);
    font-size: 16px; line-height: 1.5; -webkit-font-smoothing: antialiased;
    display: flex; flex-direction: column; min-height: 100vh;
  }}
  header {{
    border-bottom: 1px solid var(--line); padding: 14px 22px;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    background: linear-gradient(180deg, #11141a, #0c0e12);
  }}
  .brand {{ font-weight: 700; letter-spacing: .06em; font-size: 13px; color: var(--ink-dim); }}
  .brand b {{ color: var(--accent); }}
  .counts {{ font-family: var(--mono); font-size: 13px; color: var(--ink-dim); margin-left: auto; }}
  .counts .left {{ color: var(--ink); font-weight: 600; }}
  .counts .a {{ color: var(--approve-2); }}
  .counts .d {{ color: var(--deny-2); }}
  .progress-wrap {{ height: 3px; background: var(--line); width: 100%; }}
  .progress {{ height: 100%; width: 0%; background: var(--accent); transition: width .18s ease; }}
  main {{ flex: 1; display: flex; align-items: flex-start; justify-content: center; padding: 28px 18px 120px; }}
  .card {{
    width: 100%; max-width: 860px; background: var(--panel);
    border: 1px solid var(--line); border-radius: var(--radius);
    box-shadow: 0 12px 40px rgba(0,0,0,.45); overflow: hidden;
  }}
  .card-head {{ padding: 18px 24px 12px; border-bottom: 1px solid var(--line); }}
  .card-head .row {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
  .case-no {{ font-family: var(--mono); font-size: 13px; color: var(--ink-faint); }}
  .case-id {{ font-family: var(--mono); font-size: 14px; color: var(--ink-dim); }}
  .chip {{
    font-family: var(--mono); font-size: 12px; letter-spacing: .04em;
    background: var(--chip); color: var(--accent); border: 1px solid var(--line);
    padding: 3px 10px; border-radius: 999px; text-transform: lowercase;
  }}
  .facts {{ padding: 8px 0 6px; }}
  .fact {{
    display: grid; grid-template-columns: 200px 1fr; gap: 16px;
    padding: 13px 24px; border-bottom: 1px solid var(--line);
  }}
  .fact:last-child {{ border-bottom: none; }}
  .fact:nth-child(even) {{ background: var(--panel-2); }}
  .fact .k {{
    font-family: var(--mono); font-size: 12px; letter-spacing: .03em;
    color: var(--ink-faint); text-transform: uppercase; padding-top: 1px;
  }}
  .fact .v {{ color: var(--ink); white-space: pre-wrap; word-break: break-word; }}
  .notes-wrap {{ padding: 16px 24px 4px; }}
  .notes-wrap label {{ display: block; font-size: 12px; color: var(--ink-faint); margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: .04em; font-family: var(--mono); }}
  textarea {{
    width: 100%; min-height: 62px; resize: vertical; background: var(--panel-2);
    border: 1px solid var(--line); border-radius: 10px; color: var(--ink);
    padding: 10px 12px; font-family: var(--sans); font-size: 14px;
  }}
  textarea:focus {{ outline: none; border-color: var(--accent); }}
  .actions {{
    position: fixed; left: 0; right: 0; bottom: 0; padding: 14px 18px;
    display: flex; gap: 14px; justify-content: center; align-items: center;
    background: linear-gradient(0deg, var(--bg) 70%, transparent);
  }}
  .actions .inner {{ width: 100%; max-width: 860px; display: flex; gap: 14px; align-items: center; }}
  button {{ font-family: var(--sans); cursor: pointer; border: none; }}
  .btn-decide {{
    flex: 1; padding: 18px 0; border-radius: 12px; font-size: 17px; font-weight: 700;
    letter-spacing: .03em; color: #fff; transition: transform .06s ease, filter .12s ease;
  }}
  .btn-decide:active {{ transform: translateY(1px); }}
  .btn-approve {{ background: var(--approve); }}
  .btn-approve:hover {{ filter: brightness(1.12); }}
  .btn-deny {{ background: var(--deny); }}
  .btn-deny:hover {{ filter: brightness(1.12); }}
  .btn-decide .kbd {{ font-family: var(--mono); font-size: 12px; opacity: .8; margin-left: 8px; }}
  .btn-back {{
    background: var(--panel-2); color: var(--ink-dim); border: 1px solid var(--line);
    padding: 18px 18px; border-radius: 12px; font-size: 14px;
  }}
  .btn-back:hover {{ color: var(--ink); }}
  .btn-back:disabled {{ opacity: .35; cursor: default; }}
  /* End screen */
  .done {{ max-width: 640px; text-align: center; }}
  .done h1 {{ font-size: 24px; margin: 0 0 8px; }}
  .done p {{ color: var(--ink-dim); }}
  .done .stat {{ font-family: var(--mono); font-size: 14px; color: var(--ink); margin: 18px 0; }}
  .btn-download {{
    background: var(--accent); color: #fff; padding: 16px 28px; border-radius: 12px;
    font-size: 16px; font-weight: 700; letter-spacing: .02em;
  }}
  .btn-download:hover {{ filter: brightness(1.1); }}
  .btn-ghost {{
    background: transparent; color: var(--ink-dim); border: 1px solid var(--line);
    padding: 12px 18px; border-radius: 10px; font-size: 14px; margin-top: 14px;
  }}
  .btn-ghost:hover {{ color: var(--ink); }}
  .hint {{ color: var(--ink-faint); font-size: 12px; margin-top: 22px; font-family: var(--mono); }}
</style>
</head>
<body>
<header>
  <span class="brand"><b>ROGUE</b> · Human Gate review</span>
  <span class="case-id" id="corpus-label">{safe_label}</span>
  <span class="counts" id="counts"></span>
</header>
<div class="progress-wrap"><div class="progress" id="progress"></div></div>

<main id="main"></main>

<div class="actions" id="actions" style="display:none">
  <div class="inner">
    <button class="btn-back" id="back" title="Previous case">&larr; Back</button>
    <button class="btn-decide btn-deny" id="deny">DENY<span class="kbd">D</span></button>
    <button class="btn-decide btn-approve" id="approve">APPROVE<span class="kbd">A</span></button>
  </div>
</div>

<script>
"use strict";
const CASES = {cases_json};
const KEY_ORDER = {key_order_json};
const STORAGE_KEY = "rogue_oversight_decisions_v1";
const TOTAL = CASES.length;

// decisions[i] = {{decision, deliberation_notes, decision_latency_s}} | undefined
let decisions = new Array(TOTAL);
let idx = 0;
let shownAt = 0;

function loadProgress() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved && Array.isArray(saved.decisions) && saved.decisions.length === TOTAL) {{
      decisions = saved.decisions;
      idx = typeof saved.idx === "number" ? Math.max(0, Math.min(TOTAL, saved.idx)) : 0;
    }}
  }} catch (e) {{ /* ignore corrupt storage */ }}
}}
function saveProgress() {{
  try {{ localStorage.setItem(STORAGE_KEY, JSON.stringify({{decisions, idx}})); }}
  catch (e) {{ /* storage may be unavailable on file:// in some browsers */ }}
}}

function orderedFactKeys(facts) {{
  const keys = Object.keys(facts);
  const known = KEY_ORDER.filter(k => keys.includes(k));
  const rest = keys.filter(k => !KEY_ORDER.includes(k)).sort();
  return known.concat(rest);
}}
function esc(s) {{
  return String(s).replace(/[&<>"']/g, c => (
    {{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]
  ));
}}
function prettyKey(k) {{ return k.replace(/_/g, " "); }}

function counts() {{
  let a = 0, d = 0;
  for (const r of decisions) {{ if (r && r.decision === "APPROVE") a++; else if (r && r.decision === "DENY") d++; }}
  return {{a, d, done: a + d, left: TOTAL - (a + d)}};
}}
function renderCounts() {{
  const c = counts();
  document.getElementById("counts").innerHTML =
    `<span class="left">${{c.left}} left</span> &nbsp;·&nbsp; ` +
    `<span class="a">${{c.a}} approve</span> / <span class="d">${{c.d}} deny</span> ` +
    `&nbsp;(${{c.done}}/${{TOTAL}})`;
  document.getElementById("progress").style.width = (TOTAL ? (c.done / TOTAL * 100) : 0) + "%";
}}

function render() {{
  renderCounts();
  const main = document.getElementById("main");
  const actions = document.getElementById("actions");
  if (idx >= TOTAL) {{ renderDone(); actions.style.display = "none"; return; }}
  actions.style.display = "flex";

  const c = CASES[idx];
  const prior = decisions[idx];
  const rows = orderedFactKeys(c.facts).map(k =>
    `<div class="fact"><div class="k">${{esc(prettyKey(k))}}</div><div class="v">${{esc(c.facts[k])}}</div></div>`
  ).join("");

  main.innerHTML = `
    <div class="card">
      <div class="card-head">
        <div class="row">
          <span class="case-no">case ${{idx + 1}} of ${{TOTAL}}</span>
          <span class="chip">${{esc(c.case_class)}}</span>
          <span class="case-id">${{esc(c.case_id)}}</span>
        </div>
      </div>
      <div class="facts">${{rows}}</div>
      <div class="notes-wrap">
        <label for="notes">deliberation notes (optional)</label>
        <textarea id="notes" placeholder="What did you check? (not scored — engagement is not a breach)">${{prior && prior.deliberation_notes ? esc(prior.deliberation_notes) : ""}}</textarea>
      </div>
    </div>`;

  document.getElementById("back").disabled = (idx === 0);
  shownAt = performance.now();
  // keep focus on the body so A/D keys work without a stray textarea focus
  window.scrollTo(0, 0);
}}

function decide(decision) {{
  if (idx >= TOTAL) return;
  const notesEl = document.getElementById("notes");
  const notes = notesEl ? notesEl.value.trim() : "";
  const latency = Math.max(0, (performance.now() - shownAt) / 1000);
  decisions[idx] = {{
    case_id: CASES[idx].case_id,
    decision: decision,
    deliberation_notes: notes ? notes : null,
    decision_latency_s: Math.round(latency * 1000) / 1000,
  }};
  idx += 1;
  saveProgress();
  render();
}}

function back() {{
  if (idx > 0) {{ idx -= 1; saveProgress(); render(); }}
}}

function renderDone() {{
  const main = document.getElementById("main");
  const c = counts();
  main.innerHTML = `
    <div class="card done" style="padding:36px 28px">
      <h1>All ${{TOTAL}} cases reviewed</h1>
      <p>Download your decisions and hand the file to the scorer to get the real false-approve rate.</p>
      <div class="stat">${{c.a}} approve · ${{c.d}} deny · ${{TOTAL}} total</div>
      <button class="btn-download" id="download">Download decisions</button>
      <div><button class="btn-ghost" id="review-again">&larr; Review again</button>
      <button class="btn-ghost" id="reset">Reset all</button></div>
      <div class="hint">file: oversight_decisions.json &rarr; run_gate_measurement.py --mode decisions</div>
    </div>`;
  document.getElementById("download").onclick = download;
  document.getElementById("review-again").onclick = () => {{ idx = Math.max(0, TOTAL - 1); saveProgress(); render(); }};
  document.getElementById("reset").onclick = () => {{
    if (confirm("Discard all decisions and start over?")) {{
      decisions = new Array(TOTAL); idx = 0;
      try {{ localStorage.removeItem(STORAGE_KEY); }} catch (e) {{}}
      render();
    }}
  }};
}}

function download() {{
  // Emit FACTS-side decisions only: case_id, decision, notes, latency.
  // No label is known to the page; scoring joins to the on-disk key.
  const out = [];
  for (let i = 0; i < TOTAL; i++) {{
    const r = decisions[i];
    if (!r) continue;
    out.push({{
      case_id: r.case_id,
      decision: r.decision,
      deliberation_notes: r.deliberation_notes,
      decision_latency_s: r.decision_latency_s,
    }});
  }}
  const blob = new Blob([JSON.stringify(out, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "oversight_decisions.json";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}}

document.getElementById("approve").onclick = () => decide("APPROVE");
document.getElementById("deny").onclick = () => decide("DENY");
document.getElementById("back").onclick = back;

document.addEventListener("keydown", (e) => {{
  // Don't hijack typing in the notes box.
  if (e.target && e.target.tagName === "TEXTAREA") return;
  const k = e.key.toLowerCase();
  if (k === "a") {{ e.preventDefault(); decide("APPROVE"); }}
  else if (k === "d") {{ e.preventDefault(); decide("DENY"); }}
  else if (k === "arrowleft") {{ e.preventDefault(); back(); }}
}});

loadProgress();
render();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a self-contained, dependency-free HTML reviewer for the Surface-2 "
            "human gate. The page embeds FACTS ONLY (never the answer key); the reviewer "
            "clicks APPROVE/DENY and downloads oversight_decisions.json for scoring."
        )
    )
    parser.add_argument(
        "--corpus", default=None,
        help="Path to the designed-label corpus JSON (default: the bundled fixture).",
    )
    parser.add_argument(
        "--out", default="oversight_review.html",
        help="Output HTML path (default: oversight_review.html).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Review only the first N cases (default: all).",
    )
    parser.add_argument(
        "--shuffle", action="store_true",
        help="Shuffle case order (seeded, deterministic).",
    )
    parser.add_argument(
        "--shuffle-seed", type=int, default=1729,
        help="Seed for --shuffle (default 1729); makes the order reproducible.",
    )
    args = parser.parse_args(argv)

    cases = load_corpus(args.corpus)
    if args.shuffle:
        random.Random(args.shuffle_seed).shuffle(cases)
    if args.limit is not None:
        if args.limit < 1:
            parser.error(f"--limit must be >= 1, got {args.limit}")
        cases = cases[: args.limit]

    payload = _build_payload(cases)  # strips + asserts no answer-key leakage

    corpus_label = args.corpus or "bundled fixture"
    html_text = _render_html(payload, corpus_label=str(corpus_label))

    out_path = Path(args.out)
    out_path.write_text(html_text, encoding="utf-8")

    size = out_path.stat().st_size
    print(
        f"wrote {out_path} ({size:,} bytes) — {len(payload)} case(s), FACTS ONLY "
        f"(no designed_label/designed_rationale/source_refs embedded)."
    )
    print(
        "open it by double-click (no server), click through, then Download decisions "
        "→ oversight_decisions.json → run_gate_measurement.py --mode decisions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
