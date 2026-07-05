#!/usr/bin/env bash
# Hybrid P4 run-data regeneration, unattended + Slack-pinged (caching-only judge, no batch).
#   Phase 1 — Featherless: arms A/B/C/D/E (scale ladders + alignment), one provider for ladder consistency.
#   Phase 2 — OpenRouter: F_reasoning models + cross-provider 70B/72B/8B (serving-stack gap).
# Liveness guard + checkpointing are in the harness; this adds pings + an all-aborted guard so a
# silent stall / fake-success can't hide while you're asleep. Cost ceiling ~$20 (Featherless flat,
# OpenRouter ~$1-3, Anthropic paraphrase judge ~$10-18, prompt-cached).
set -u
cd /Users/soren/Desktop/ROGUE
set -a; . ./.env 2>/dev/null || true; set +a
BOT="${SLACK_BOT_TOKEN:-}"          # the SLACK_WEBHOOK_URL is revoked (302->404); use the bot instead
CHAN="#security"
DATE="$(date +%F)"
FEATH="data/research/skill_leak_census_${DATE}.json"
ORF="data/research/skill_leak_openrouter_${DATE}.json"
LOG="data/research/skill_leak_regen_${DATE}.log"

ping(){ [ -n "$BOT" ] && curl -s https://slack.com/api/chat.postMessage \
        -H "Authorization: Bearer $BOT" -H 'Content-type: application/json' \
        --data "$(python3 -c 'import json,sys;print(json.dumps({"channel":sys.argv[1],"text":sys.argv[2]}))' "$CHAN" "$1")" \
        >/dev/null 2>&1 || true; }
# n results in an --out file (0 if missing/empty/all-aborted)
nres(){ python3 -c "import json,sys;
try:
 d=json.load(open(sys.argv[1])); print(len(d.get('results',[])))
except Exception: print(0)" "$1" 2>/dev/null || echo 0; }

START=$(date +%s)
ping ":satellite_antenna: P4 regen STARTED ($DATE) — Phase1 Featherless arms A-E, Phase2 OpenRouter reasoning+cross-provider. caching-only judge, ceiling ~\$20. I'll ping each phase + done/crash."

# ---------- Phase 1: Featherless ----------
ping ":hourglass_flowing_sand: P4 Phase 1/2 (Featherless arms A-E) running…"
uv run python scripts/memory/run_leakage_redteam.py \
  --grid scripts/memory/leakage_model_grid.json --provider featherless \
  --arms A_scale_qwen,B_scale_llama,C_align_llama8b,D_align_qwen7b,E_align_gemma9b \
  --paraphrase-judge --prefer-mirror --runs 1 \
  --out "$FEATH" >> "$LOG" 2>&1
RC1=$?; N1=$(nres "$FEATH"); D1=$(( ($(date +%s)-START)/60 ))
if [ "$RC1" -eq 0 ] && [ "$N1" -gt 0 ]; then
  ping ":white_check_mark: P4 Phase 1 DONE in ${D1}m — ${N1} Featherless models → $FEATH"
else
  ping ":x: P4 Phase 1 PROBLEM (rc=$RC1, results=$N1) after ${D1}m — see $LOG. Continuing to Phase 2."
fi

# ---------- Phase 2: OpenRouter ----------
ping ":hourglass_flowing_sand: P4 Phase 2/2 (OpenRouter reasoning + cross-provider) running…"
uv run python scripts/memory/run_leakage_redteam.py \
  --grid scripts/memory/leakage_grid_openrouter.json --provider openrouter \
  --paraphrase-judge --runs 1 \
  --out "$ORF" >> "$LOG" 2>&1
RC2=$?; N2=$(nres "$ORF"); D2=$(( ($(date +%s)-START)/60 ))

# ---------- Summary ----------
TOTAL=$(( N1 + N2 ))
if [ "$TOTAL" -gt 0 ] && [ "$N1" -gt 0 ] && [ "$N2" -gt 0 ]; then
  ping ":checkered_flag: P4 regen COMPLETE in ${D2}m — ${N1} Featherless + ${N2} OpenRouter = ${TOTAL} models. Files: $FEATH , $ORF . Next: canary check + update P4 numbers."
elif [ "$TOTAL" -gt 0 ]; then
  ping ":warning: P4 regen finished in ${D2}m but a phase came back empty (Feath=$N1, OR=$N2). Check $LOG before trusting."
else
  ping ":rotating_light: P4 regen produced ZERO results in ${D2}m — likely keys/serving/all-aborted. Check $LOG. Do NOT treat as done."
fi
