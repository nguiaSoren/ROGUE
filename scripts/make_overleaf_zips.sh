#!/usr/bin/env bash
# make_overleaf_zips.sh — rebuild the BLIND TMLR/Overleaf source bundles
# (docs/research/publishing/pN_tmlr_overleaf.zip) from current source, and REFUSE to
# emit any bundle that does not compile blind AND pass an identity scan.
#
# WHY THIS EXISTS
#   pN_tmlr_overleaf.zip is hand-built and gitignored, so it goes stale the instant
#   main.tex or a figure changes — and `git status` never flags it. A stale blind
#   bundle means the PDF you reviewed and the one a reviewer compiles are DIFFERENT
#   documents; the catastrophic case is an identity string surviving in the bundle
#   after you fixed it in source (a desk-reject-class leak at a blind venue). This
#   script converts that silent, easy-to-forget, late-small-edit failure into a gate
#   you cannot pass with a dirty bundle.
#
# DESIGN (order matters)
#   1. rm the old zip      — a stale file cannot survive into the new bundle.
#   2. build from a MANIFEST declared by the document (\includegraphics in main.tex),
#      not from whatever happens to be in the directory.
#   3. verify-AS-GATE      — extract the shipped zip, compile it blind standalone, and
#      scan the compiled PDF + source. On ANY failure: remove the zip and exit nonzero.
#      A rebuild that doesn't block on failure just relocates the manual check.
#
# SCOPE (deliberately narrow so the tool is not its own liability)
#   Rebuild-and-verify ONLY. It NEVER pushes, submits, or moves a bundle anywhere.
#   Shipping stays a manual step. It builds the BLIND bundles only.
#
# NOT CHECKED (be honest — do these by hand):
#   - identity rendered in figure PIXELS (e.g. a codename baked into an axis label) is
#     invisible to a text scan; it still needs a manual visual pass.
#   (Source identity IS now gated: the blind main.tex resolves to anonymous in-file —
#   real identity is \input from authormeta.tex, never staged here — and GATE 3 scans
#   the raw main.tex bytes, so this is no longer a hand-check.)
#
# Usage:  scripts/make_overleaf_zips.sh [p1|p2|p3|p4|all]   (default: all)
# Exit:   0 = every requested bundle rebuilt AND passed every gate
#         1 = at least one bundle failed a gate (its zip was REMOVED, not left bad)

set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUB="$ROOT/docs/research/publishing"

# ── versioned identity blocklist (AUDIT IT HERE; keep in sync with audit_blind_supplement.sh) ──
# Any of these appearing in a BLIND bundle's compiled PDF or non-tex source is a leak.
NAME_RE='\b(Benaja|Soren|Obounou|Lekogo|Nguia|Incheon)\b'   # word-bounded: won't false-hit "Sorensen"
EMAIL='nguiasoren@gmail.com'                                 # fixed, case-insensitive
HANDLE='nguiaSoren'                                          # GitHub handle (also covers the repo URL)
CODENAME_RE='ROGUE|REDTEAM'                                  # case-SENSITIVE product codename

dirfor(){ case "$1" in
  p1) echo p1_scheduler;;  p2) echo p2_judge_calibration;;
  p3) echo p3_reproducibility_gap;;  p4) echo p4_skill_leak;;
  *) echo "";; esac; }

build_one(){
  local tag="$1" sub; sub="$(dirfor "$tag")"
  [ -n "$sub" ] || { echo "═══ $tag ═══"; echo "  FAIL: unknown paper tag"; return 1; }
  local dir="$PUB/$sub" tex="$PUB/$sub/main.tex" zip="$PUB/${tag}_tmlr_overleaf.zip"
  echo "═══ $tag  ($sub) ═══"
  rm -f "$zip"   # remove up front: ANY failure below must leave NO shippable bundle on disk
  [ -f "$tex" ] || { echo "  FAIL: no main.tex at $tex"; return 1; }

  # GATE 0 (build-switch state): a BLIND bundle must have \namedtrue COMMENTED. An
  # uncommented \namedtrue is a NAMED/de-anonymized build that would ship AS the blind
  # submission — the subtle version of the identity leak.
  if grep -qE '^[[:space:]]*\\namedtrue' "$tex"; then
    echo "  FAIL: \\namedtrue is UNCOMMENTED — would ship a NAMED build as the blind bundle."; return 1
  fi

  # MANIFEST from the document: every \includegraphics target, resolved to a real file.
  local figs=() missing=() b
  while IFS= read -r b; do
    [ -z "$b" ] && continue
    if   [ -f "$dir/$b" ];     then figs+=("$b")
    elif [ -f "$dir/$b.pdf" ]; then figs+=("$b.pdf")
    elif [ -f "$dir/$b.png" ]; then figs+=("$b.png")
    else missing+=("$b"); fi
  done < <(grep -oE '\\includegraphics(\[[^]]*\])?\{[^}]+\}' "$tex" | sed -E 's/.*\{([^}]+)\}/\1/')
  if [ ${#missing[@]} -gt 0 ]; then
    echo "  FAIL: \\includegraphics references missing files: ${missing[*]}"; return 1
  fi

  # stage exactly: main.tex + references.bib (if any) + declared figures + tmlr.sty/bst
  local ST; ST="$(mktemp -d)"
  cp "$tex" "$ST/main.tex"
  local zlist=(main.tex tmlr.sty tmlr.bst)
  cp "$PUB/tmlr.sty" "$PUB/tmlr.bst" "$ST/"
  [ -f "$dir/references.bib" ] && { cp "$dir/references.bib" "$ST/"; zlist+=(references.bib); }
  for b in "${figs[@]}"; do cp "$dir/$b" "$ST/"; zlist+=("$b"); done

  # build fresh (zip was already removed at entry, so there is no "Nothing to do!" no-op)
  ( cd "$ST" && zip -Xq "$zip" "${zlist[@]}" )

  # ── VERIFY-AS-GATE on the SHIPPED bytes (extract the zip, don't trust the staging) ──
  local RX; RX="$(mktemp -d)"; unzip -qo "$zip" -d "$RX"
  local fail=0

  # GATE 1: the bundle must compile blind, standalone.
  if ( cd "$RX" && TEXINPUTS=".:" BSTINPUTS=".:" BIBINPUTS=".:" tectonic main.tex >"$RX/_compile.log" 2>&1 ); then
    echo "  ok   compiles blind standalone"
  else
    echo "  FAIL: bundle does not compile"; fail=1
  fi

  # GATE 1b: citations/refs must RESOLVE. tectonic compiles fine with an undefined \citep
  # (it renders a "?" and only warns), so the compile gate alone misses a broken bib key.
  # Catch it via the log warnings AND a "?" cite/ref marker scan of the rendered PDF.
  if grep -qiE "undefined (citation|reference)|citation .* undefined" "$RX/_compile.log" 2>/dev/null; then
    echo "  FAIL: undefined citation/reference (broken bib key or \\ref)"; fail=1
  elif [ -f "$RX/main.pdf" ] && pdftotext "$RX/main.pdf" - 2>/dev/null | grep -qE '\(\?+\)|\[\?+\]|\?\?'; then
    echo "  FAIL: '?' citation/reference marker in compiled PDF"; fail=1
  else
    echo "  ok   citations/references resolve"
  fi

  # GATE 2: the compiled blind PDF must contain no identity/codename term.
  if [ -f "$RX/main.pdf" ]; then
    local pt hit=""; pt="$(pdftotext "$RX/main.pdf" - 2>/dev/null || true)"
    printf '%s' "$pt" | grep -qiE "$NAME_RE"    && hit="$hit name"
    printf '%s' "$pt" | grep -qiF "$EMAIL"      && hit="$hit email"
    printf '%s' "$pt" | grep -qF  "$HANDLE"     && hit="$hit handle/url"
    printf '%s' "$pt" | grep -qE  "$CODENAME_RE" && hit="$hit codename"
    if [ -n "$hit" ]; then echo "  FAIL: identity/codename in compiled PDF text:$hit"; fail=1
    else echo "  ok   compiled PDF clean of identity/codename"; fi
  fi

  # GATE 3: shippable SOURCE (main.tex AND references.bib) carries no identity in its
  # BYTES. The blind main.tex now resolves to anonymous IN-FILE — real identity is
  # \input from authormeta.tex, which is never staged into this bundle — so a raw-source
  # scan must pass, and it catches any regression that re-inlines the name/codename.
  # hidden-at-compile (tmlr auto-hide / inactive \ifnamed branch) is NOT absent-from-file:
  # GATE 2 checks the render; this checks the bytes a reviewer opening the .tex would see.
  local sx
  for sx in "$RX/main.tex" "$RX/references.bib"; do
    [ -f "$sx" ] || continue
    grep -qiE "$NAME_RE"     "$sx" && { echo "  FAIL: name in $(basename "$sx") source"; fail=1; }
    grep -qiF "$EMAIL"       "$sx" && { echo "  FAIL: email in $(basename "$sx") source"; fail=1; }
    grep -qF  "$HANDLE"      "$sx" && { echo "  FAIL: handle/url in $(basename "$sx") source"; fail=1; }
    grep -qE  "$CODENAME_RE" "$sx" && { echo "  FAIL: codename in $(basename "$sx") source"; fail=1; }
  done
  [ "$fail" -eq 0 ] && echo "  ok   shipped source (.tex/.bib) clean of identity"

  # GATE 4: figure files must carry no identity in their BYTES — EXIF/XMP/PNG text chunks,
  # embedded file paths, or the build machine's username. A PDF-render/text scan never sees
  # these (e.g. a regenerated figure could embed "/Users/soren/..." in metadata).
  local META_RE='\b(Benaja|Soren|Obounou|Lekogo|Nguia|Incheon)\b|nguiaSoren|/Users/|nguiasoren@'
  local fig figfail=0
  for fig in "$RX"/*.pdf "$RX"/*.png; do
    [ -e "$fig" ] || continue
    [ "$(basename "$fig")" = main.pdf ] && continue
    if LC_ALL=C strings -n 4 "$fig" | grep -qiE "$META_RE"; then
      echo "  FAIL: identity in figure metadata/bytes: $(basename "$fig")"; fail=1; figfail=1
    fi
  done
  [ "$figfail" -eq 0 ] && echo "  ok   figures clean of identity in metadata/bytes"

  if [ "$fail" -ne 0 ]; then
    rm -f "$zip"                       # refuse to leave a bad bundle on disk
    echo "  ✗ $tag: GATE FAILED — zip REMOVED (no shippable bundle produced)"
    rm -rf "$ST" "$RX"; return 1
  fi
  local n; n="$(cd "$RX" && find . -type f ! -name main.pdf ! -name _compile.log | wc -l | tr -d ' ')"
  echo "  ✓ $tag: rebuilt + verified  ($n files)"
  rm -rf "$ST" "$RX"; return 0
}

main(){
  command -v tectonic >/dev/null 2>&1 || { echo "FATAL: tectonic not on PATH (needed for the compile gate)"; exit 2; }
  command -v pdftotext >/dev/null 2>&1 || { echo "FATAL: pdftotext not on PATH (needed for the identity gate)"; exit 2; }
  local targets=("$@"); [ ${#targets[@]} -eq 0 ] && targets=(all)
  [ "${targets[0]}" = all ] && targets=(p1 p2 p3 p4)
  local rc=0 t
  for t in "${targets[@]}"; do build_one "$t" || rc=1; done
  echo
  if [ "$rc" -eq 0 ]; then echo "ALL REQUESTED BUNDLES OK (rebuilt + verified)."
  else echo "SOME BUNDLES FAILED — failed zips were REMOVED. Fix source and re-run."; fi
  echo "Reminder: figure PIXELS are NOT scanned — do a manual visual pass. This script never pushes/submits."
  exit $rc
}
main "$@"
