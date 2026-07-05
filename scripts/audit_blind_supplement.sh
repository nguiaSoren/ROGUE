#!/usr/bin/env bash
# Mechanical blind-submission audit for one paper's shipped supplement zip + compiled PDF.
# Catches the recurring leak / dangling-cite / broken-ref classes WITHOUT the 8-agent fan-out.
#
# WHAT IT CANNOT DO: identity rendered inside figure PIXELS (axis labels, legends, titles, a
# wordmark in a PNG) is invisible to pdftotext/grep — it must be checked by eye. This script
# greps the figure GENERATORS as a proxy and reminds you to do the visual pass. See
# docs/research/publishing/BLIND_SUBMISSION_AUDIT.md for the full checklist (incl. the
# claim-evidence / rounding / cross-submission lenses that need human judgement).
#
# Usage:  scripts/audit_blind_supplement.sh [p1|p2|p3|p4|all]   (default: all)
# Run AFTER scripts/make_supplements.sh so the zips + PDFs are current. (bash 3.2 compatible.)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PUB="docs/research/publishing"

tag_to_dir() { case "$1" in
  p1) echo p1_scheduler;; p2) echo p2_judge_calibration;;
  p3) echo p3_reproducibility_gap;; p4) echo p4_skill_leak;; *) echo "";; esac; }

# identity / codename / cross-submission tokens (case-insensitive). \bredteam\b is intentionally
# NOT here: it is legitimate red-team domain vocabulary (esp. P4). The codename's canonical form
# is rogue/ROGUE, which IS caught.
# NOTE: REDTEAM is checked case-SENSITIVELY below (uppercase = old codename artifact); it is left
# out of this -i list so legitimate lowercase red-team domain vocabulary (P4) does not false-trip.
ID_RE='soren|nguia|obounou|lekogo|incheon|\brogue\b|github\.com/nguiaSoren|nguiasoren|CLAUDE\.md|companion (work|stud|paper)|under submission|§ *[A-Za-z]*[0-9]'

audit() {
  local tag="$1"; local dir; dir="$(tag_to_dir "$tag")"; local fail=0
  [ -n "$dir" ] || { echo "unknown tag: $tag"; return 2; }
  local pdf="$PUB/$dir/main.pdf" zip="$PUB/supplement_$tag.zip"
  echo "===================== $tag  ($dir) ====================="
  [ -f "$zip" ] || { echo "  FAIL: no supplement zip ($zip) — run make_supplements.sh"; return 1; }
  local d; d="$(mktemp -d)"; unzip -qo "$zip" -d "$d"

  # 1. identity / codename in shipped CONTENTS
  local h; h="$(grep -rilE "$ID_RE" "$d" 2>/dev/null || true)"
  local cs; cs="$(grep -rlE 'ROGUE|REDTEAM' "$d" 2>/dev/null || true)"   # case-sensitive codename artifact
  h="$(printf '%s\n%s' "$h" "$cs" | sort -u | sed '/^$/d')"
  if [ -n "$h" ]; then echo "  X identity/codename in zip CONTENTS:"; echo "$h" | sed "s#$d/#       #"; fail=1
  else echo "  ok zip contents: clean of identity/codename"; fi

  # 1b. set-position labels P1..P4 (case-sensitive; lowercase p2/p3 loop-vars are OK — eyeball)
  local p; p="$(grep -rlE '\bP[1-4]\b' "$d" 2>/dev/null || true)"
  [ -n "$p" ] && { echo "  ? uppercase P[1-4] present (verify it is not a set-position label):"; echo "$p" | sed "s#$d/#       #"; }
  # 1b'. literal 'Paper N' ordinal — unambiguous set-position tell (no benign reading like P1=priority); HARD fail
  local pp; pp="$(grep -rilE 'Paper *[0-9]' "$d" 2>/dev/null || true)"
  [ -n "$pp" ] && { echo "  X set-position 'Paper N' ordinal present:"; echo "$pp" | sed "s#$d/#       #"; fail=1; }

  # 1c. identity / set-position in FILENAMES (sanitizer only edits contents, never names)
  # (the pN_ prefix on a paper's OWN data files is the legit released-naming scheme — not flagged;
  #  the real risk is another paper's set-position smuggled into a filename, e.g. p2_kappa)
  local fn; fn="$(find "$d" \( -iname '*soren*' -o -iname '*nguia*' -o -iname '*rogue*' -o -iname '*p[1-4]_kappa*' \) 2>/dev/null || true)"
  [ -n "$fn" ] && { echo "  X identity/set-position in FILENAMES:"; echo "$fn" | sed "s#$d/#       #"; fail=1; }

  # 2. compiled PDF (TEXT LAYER ONLY — figure pixels are invisible here)
  if [ -f "$pdf" ]; then
    local pt; pt="$(pdftotext "$pdf" - 2>/dev/null || true)"
    if printf '%s' "$pt" | grep -qiE 'soren|nguia|obounou|incheon|\brogue\b|github\.com/nguiaSoren|companion (work|stud|paper)|under submission'; then
      echo "  X identity/cross-submission tell in PDF TEXT"; fail=1
    else echo "  ok PDF text layer clean  (NOTE: figure PIXELS still need a manual visual pass)"; fi
    printf '%s' "$pt" | grep -q '??' && { echo "  X broken refs (??) in PDF"; fail=1; } || echo "  ok no broken cross-references"
    # 3. every code/data file the PDF cites must ship (or be a regex fragment / repo-only / withheld)
    local miss=""
    while read -r f; do
      [ -z "$f" ] && continue
      local b; b="$(basename "$f")"
      find "$d" -name "$b" 2>/dev/null | grep -q . || miss="$miss $b"
    done < <(printf '%s' "$pt" | grep -oE '[A-Za-z0-9_./-]+\.(py|json|jsonl|csv)' | sort -u)
    [ -n "$miss" ] && echo "  ? PDF cites files NOT in zip (check each: regex fragment of a hyphenated name? repo-only/needs-DB? withheld? or a real dangling cite):$miss" || echo "  ok all cited code/data files resolve in the zip"
  else
    echo "  ? no compiled PDF ($pdf) — skipping PDF checks"
  fi
  rm -rf "$d"
  if [ $fail -eq 0 ]; then echo "  RESULT: PASS (mechanical checks)"; else echo "  RESULT: FAIL — fix the X items"; fi
  return $fail
}

# figure-GENERATOR codename proxy (the real check is opening each rendered PNG by eye).
# Scoped to the actual paper-figure generators, excluding caches and this script.
echo "### figure GENERATORS emitting the codename into a label/title (open the rendered PNG to confirm):"
fg="$(ls scripts/paper_figs.py scripts/research/*fig*.py 2>/dev/null | grep -v __pycache__ | xargs grep -lE 'ROGUE|\brogue\b' 2>/dev/null || true)"
[ -n "$fg" ] && echo "$fg" | sed 's/^/   /' || echo "   (none)"
echo ""

rc=0
case "${1:-all}" in
  all) for t in p1 p2 p3 p4; do audit "$t" || rc=1; done;;
  p1|p2|p3|p4) audit "$1" || rc=1;;
  *) echo "usage: $0 [p1|p2|p3|p4|all]"; exit 2;;
esac
echo ""
echo "Mechanical audit done. NOT covered (do by hand — see BLIND_SUBMISSION_AUDIT.md):"
echo "  - identity rendered in figure PIXELS (open every figure)        - claim<->evidence calibration vs the venue rubric"
echo "  - numeric rounding coherence across prose/captions/figures      - cross-submission CONSTRUCT resolvers (shared vocabulary)"
echo "  - whether a recompute script actually runs in a clean/offline env"
exit $rc
