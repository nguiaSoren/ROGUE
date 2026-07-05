#!/usr/bin/env bash
# Build the 4 TMLR supplementary zips, one per paper. Each zip = ONLY that paper's
# released data/code slices + its blind PAPERS.md (HTML-comment stripped), with the
# repo-relative paths preserved so the reproduce scripts run on unzip.
#
# Re-run any time the underlying files change — no manual zip tracking. FAIL-CLOSED:
# if any author/identity token appears in a paper's staged tree, that zip is NOT
# written (forces a fix). Output: docs/research/publishing/supplement_p{1..4}.zip
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
OUT="$ROOT/docs/research/publishing"
TMP="$(mktemp -d)"
ID_RE='soren|nguia|obounou|lekogo|/Users/soren|github\.com/nguiaSoren|incheon|rogue|neon|§ *[A-Za-z]*[0-9]|oversight-meaningfulness|Surface[ -][0-9]|Paper *[0-9]|CLAUDE\.md|companion (work|stud|paper)|under submission|in this codebase'

stage() {  # $1=stage dir, $2..=repo-relative paths (files / dirs / globs)
  local dir="$1"; shift; local missing=()
  for p in "$@"; do
    local matched=0
    for f in $p; do
      if [ -e "$f" ]; then mkdir -p "$dir/$(dirname "$f")"; cp -R "$f" "$dir/$f"; matched=1; fi
    done
    [ $matched -eq 0 ] && missing+=("$p")
  done
  [ ${#missing[@]} -gt 0 ] && printf '   missing (skipped): %s\n' "${missing[*]}"
}

sanitize() {  # scrub known identity strings in the STAGED COPIES only (repo originals untouched)
  while IFS= read -r f; do
    LC_ALL=C sed -i '' \
      -e 's#https://github.com/nguiaSoren/ROGUE#https://anonymous.example/anon-repo#g' \
      -e 's#github.com/nguiaSoren/ROGUE#anonymous.example/anon-repo#g' \
      -e 's#ROGUE_OPENROUTER_#JUDGE_OPENROUTER_#g' \
      -e 's#rogue_judge#our_judge#g' \
      -e 's#rogue_breach#judge_breach#g' \
      -e 's#rogue_verdict#judge_verdict#g' \
      -e 's#rogue_kappa_check#judge_kappa_check#g' \
      -e 's#rogue_label_#judge_label_#g' \
      -e 's#rogue_dev_password#anon_password#g' \
      -e 's#rogue_\*#run_*#g' \
      -e 's#ROGUE_PLAN#DESIGN_NOTES#g' \
      -e 's#ROGUE#the harness#g' \
      -e 's#Rogue#The harness#g' \
      -e 's#rogue#harness#g' \
      -e 's#live Neon DB#live database#g' \
      -e 's#live Neon#live database#g' \
      -e 's#collected in Neon#collected in the database#g' \
      -e 's#Neon endpoints#database endpoints#g' \
      -e 's#Neon#a managed Postgres database#g' \
      -e 's#build-0[0-9]#an internal build note#g' \
      -e 's#Surface[ -][0-9][0-9]*#an internal component#g' \
      -e 's#ADR-[0-9][0-9][0-9][0-9]#an internal decision record#g' \
      -e 's#§ *[A-Za-z]*[0-9][0-9.]*#an internal section#g' \
      -e 's#scripts/calibration/kappa_check\.py#an internal kappa helper#g' \
      -e 's#the sibling ``kappa_check\.py``#an internal ``kappa helper``#g' \
      -e 's#oversight-meaningfulness note#separate internal note#g' \
      -e 's#TMLR upgrade of p4#an archival version#g' \
      -e 's#nguiaSoren#anon#g' \
      -e 's#Benaja Soren Obounou Lekogo Nguia#Anonymous#g' \
      -e 's#nguiasoren@gmail.com#anon@example.org#g' \
      -e 's#/Users/soren#/home/anon#g' \
      -e 's#P[1-4] — ##g' \
      -e 's#"""P[1-4] #"""#g' \
      -e "s#P[1-4]'s #the #g" \
      -e 's#The P[1-4] #The #g' \
      -e 's/# P[1-4] /# /g' \
      -e 's# (P[1-4])##g' \
      -e 's#(P[1-4] #(#g' \
      -e 's#[[:<:]]P\([0-4]\)[[:>:]]#Sev-\1#g' \
      -e 's#p2_kappa#kappa#g' \
      -e 's#CLAUDE\.md costly-scripts rule#an internal cost-control policy#g' \
      -e 's#CLAUDE\.md#an internal policy doc#g' \
      -e 's#os.environ.get("USER", "operator")#"operator"#g' \
      "$f" 2>/dev/null || true
  done < <(grep -rIl '' "$1" 2>/dev/null)
}

build() {  # $1=tag  $2=blind-PAPERS.md  $3=schema tables (space-sep, "" to skip)  $4..=paths
  local tag="$1" papersmd="$2" schema="$3"; shift 3
  local dir="$TMP/$tag"; rm -rf "$dir"; mkdir -p "$dir"
  echo ">>> $tag"
  stage "$dir" "$@"
  find "$dir" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null  # never ship compiled bytecode
  find "$dir" -name '*.pyc' -delete 2>/dev/null
  sed '1,/-->/d' "$OUT/$papersmd" | sed '/./,$!d' > "$dir/PAPERS.md"   # strip leading HTML comment
  # focused CREATE TABLE schema (structure only) for the paper's own tables — NOT
  # the full models.py (which would reveal product scope + cross-link papers).
  [ -n "$schema" ] && uv run python "$ROOT/scripts/dump_schema.py" $schema > "$dir/SCHEMA.sql" 2>/dev/null
  sanitize "$dir"
  # de-position staged filenames (p2_kappa_* -> kappa_*) to match the content scrub
  find "$dir" -depth -name '*p2_kappa*' 2>/dev/null | while IFS= read -r p; do
    mv "$p" "$(dirname "$p")/$(basename "$p" | sed 's#p2_kappa#kappa#g')"
  done
  local hits idp
  hits="$(grep -rilE "$ID_RE" "$dir" 2>/dev/null || true)"
  # case-SENSITIVE set-position paper labels. EXCEPTION: the two verbatim-public-skill data files
  # (leakage_canaries_distilled.json, trace2skill_fixture/shard_*.json) carry real distilled-skill
  # bodies whose P1/P2/P3 are support-ticket PRIORITY levels, not set-position labels — manually
  # verified 2026-06-22 and traced to their SHA-pinned GitHub source (e.g. composio-community/
  # support-skills ticket-triage has P0/P1/P2/P3 priorities). The identity/codename check above
  # ($ID_RE, line 94) still applies to these files in full; only the P[1-4] check is narrowed.
  idp="$(grep -rlE '\bP[1-4]\b' "$dir" \
          --exclude='leakage_canaries_distilled.json' --exclude='shard_*.json' 2>/dev/null || true)"
  hits="$(printf '%s\n%s' "$hits" "$idp" | sort -u | sed '/^$/d')"
  if [ -n "$hits" ]; then
    echo "   IDENTITY/SET-POSITION FOUND — zip NOT written:"; echo "$hits" | sed 's/^/     /'; return 1
  fi
  ( cd "$dir" && zip -Xqr "$OUT/supplement_$tag.zip" . )
  echo "   wrote docs/research/publishing/supplement_$tag.zip  ($(cd "$dir" && find . -type f | wc -l | tr -d ' ') files)"
}

rm -f "$OUT"/supplement_p*.zip

build p1 anon_supplement_PAPERS.md \
  "deployment_configs attack_primitives attack_strategies breach_results ladder_attempts ladder_rotation_membership" \
  data/research/scheduler_results.json \
  data/research/p1_judge_panel.json \
  data/research/ladder_attempts_snapshot.csv \
  scripts/reproduce/candidate_quota_ab.py \
  scripts/paper_figs.py \
  scripts/research/p1_cost_fig.py \
  scripts/export_paper_data.py \
  scripts/reproduce/grammar_demo

build p2 anon_supplement_PAPERS_p2.md \
  "deployment_configs attack_primitives breach_results pair_refinement_steps" \
  "data/calibration/jbb_judge_report_v3.json" \
  "data/calibration/wildguard_report.json" \
  "data/calibration/strongreject_report.json" \
  "data/calibration/information_disclosure_report.json" \
  "data/calibration/unauthorized_action_report.json" \
  "data/calibration/fabricated_sensitive_value_report.json" \
  "data/calibration/information_disclosure_judge_items.jsonl" \
  "data/calibration/unauthorized_action_judge_items.jsonl" \
  "data/calibration/fabricated_sensitive_value_judge_items.jsonl" \
  "data/calibration/unauthorized_action_agentdojo_report.json" \
  "data/calibration/agentdojo_unauth_corpus.jsonl" \
  "data/calibration/agentdojo_unauth_judge_items.jsonl" \
  "data/calibration/agentdojo_unauth_divergences.json" \
  "data/calibration/agentdojo_unauth_corpus_travel.jsonl" \
  "data/calibration/agentdojo_unauth_judge_items_travel.jsonl" \
  "data/calibration/agentdojo_unauth_divergences_travel.json" \
  "data/calibration/agentdojo_unauth_corpus_workspace.jsonl" \
  "data/calibration/agentdojo_unauth_judge_items_workspace.jsonl" \
  "data/calibration/agentdojo_unauth_divergences_workspace.json" \
  "data/calibration/injecagent_unauth_corpus.jsonl" \
  "data/calibration/injecagent_unauth_judge_items_exec.jsonl" \
  "data/calibration/injecagent_unauth_judge_items.jsonl" \
  "data/calibration/injecagent_unauth_divergences.json" \
  "data/calibration/unauthorized_action_injecagent_report.json" \
  "data/calibration/jbb_judge_report_v3_qwen3-32b.json" \
  "data/calibration/jbb_judge_report_v3_gpt-oss-120b.json" \
  "data/calibration/jbb_judge_report_v3_kimi-k2.json" \
  "data/calibration/jbb_judge_report_v3_gemma-3-27b-it.json" \
  "data/calibration/jbb_judge_report_v3_deepseek-chat-v3-1.json" \
  "data/calibration/jbb_judge_report_v3_llama-3-3-70b-instruct.json" \
  "data/calibration/jbb_judge_report_v3_llama-3-1-8b-instruct.json" \
  "data/calibration/jbb_judge_report_v3_hermes-3-llama-3-1-70b.json" \
  "data/calibration/jbb_judge_report_v3_mistral-small-3-2-24b-instruct.json" \
  "data/calibration/jbb_judge_report_v3_gpt-5-4.json" \
  "data/calibration/frozen_cited/jbb_judge_report_v3_qwen-2-5-72b-instruct.json" \
  "data/calibration/frozen_cited/jbb_judge_report_v3_qwen-2-5-72b-instruct.anchor-deepinfra-fp8-t0.json" \
  "data/calibration/frozen_cited/jbb_judge_report_v3_qwen-2-5-72b-instruct.repro.json" \
  "data/calibration/frozen_cited/jbb_judge_report_v3_qwen-2-5-72b-instruct_strict.json" \
  "data/calibration/frozen_cited/jbb_judge_items.jsonl" \
  "data/calibration/frozen_cited/jbb_judge_items_qwen-2-5-72b-instruct.anchor.jsonl" \
  "data/calibration/frozen_cited/jbb_judge_items_qwen-2-5-72b-instruct.repro.jsonl" \
  "data/calibration/frozen_cited/jbb_judge_items_qwen-2-5-72b-instruct_strict.anchor.jsonl" \
  "data/calibration/frozen_cited/jbb_judge_items_qwen-2-5-72b-instruct_strict.repro.jsonl" \
  "data/calibration/p2_kappa_audit_table.md" \
  data/calibration/p2_kappa_relabels \
  scripts/calibration/run_calibration.py \
  scripts/calibration/eval_jbb_judge.py \
  scripts/calibration/eval_wildguard.py \
  scripts/calibration/second_grader_pass.py \
  scripts/calibration/calibrate_breach_type.py \
  scripts/calibration/recompute_p2_calibration.py \
  scripts/calibration/mint_agentdojo_corpus.py \
  scripts/calibration/mint_injecagent_corpus.py \
  scripts/calibration/injecagent_wedge.py \
  scripts/calibration/freeze_designed_per_case.py \
  scripts/calibration/eval_jbb_judge_2nd.py \
  scripts/calibration/build_kappa_relabel_html.py \
  scripts/calibration/score_kappa_relabel.py \
  scripts/calibration/analyze_kappa_replication.py \
  scripts/calibration/kappa_check.py \
  docs/judge-calibration.md

build p3 anon_supplement_PAPERS_p3.md \
  "deployment_configs attack_primitives source_provenances breach_results" \
  data/research/p3_v3_rejudge_trials.jsonl \
  data/research/p3_v3_rejudge_pairs.csv \
  data/research/p3_v3_rejudge_stats.json \
  data/research/reproducibility_gap_pairs.csv \
  data/research/p3_claim_distribution.csv \
  data/research/p3_corpus_source_types.csv \
  data/research/reextracted_claims.json \
  data/research/coverage_validity_results.json \
  data/research/p3_objective_classification.jsonl \
  data/research/p3_objective_decomposition.json \
  data/research/p3_unfilled_primitives.json \
  data/research/p3_consummation_qwen-qwen-2-5-72b-instruct.json \
  data/research/p3_consummation_deepseek-deepseek-chat-v3-1.json \
  data/research/p3_consummation_qwen-qwen-2-5-72b-instruct_trials.jsonl \
  data/research/p3_consummation_deepseek-deepseek-chat-v3-1_trials.jsonl \
  data/research/p3_strongreject_trials.jsonl \
  data/research/p3_strongreject_swap.json \
  data/research/p3_objective_classification2_qwen-qwen-2-5-72b-instruct.jsonl \
  scripts/research/p3_judge_independence.py \
  data/research/p3_labels.json \
  data/research/p3_fidelity.json \
  scripts/research/p3_objective_label_sheet.py \
  scripts/research/p3_objective_classify.py \
  scripts/research/p3_objective_decompose.py \
  scripts/research/p3_reviewer_recomputes.py \
  data/research/p3_contested_readjudication_evaded.json \
  data/research/p3_contested_readjudication_partial.json \
  data/research/p3_contested_index_evaded.json \
  data/research/p3_contested_index_partial.json \
  data/research/p3_contested_evaded_sonnet.json \
  data/research/p3_contested_evaded_qwen.json \
  data/research/p3_contested_evaded_deepseek.json \
  data/research/p3_contested_partial_sonnet.json \
  data/research/p3_contested_partial_qwen.json \
  data/research/p3_contested_partial_deepseek.json \
  scripts/research/p3_contested_readjudication.py \
  scripts/research/p3_unfilled_sensitivity.py \
  scripts/research/p3_corpus_table.py \
  scripts/research/p3_v3_from_pairs.py \
  scripts/research/p3_v3_figs.py \
  scripts/research/reproduce_p3_from_pairs.py \
  scripts/research/reproducibility_gap.py \
  data/research/promptrend_c2_results.json \
  data/research/promptrend_clean_results.json \
  data/research/promptrend_clean_trials.jsonl \
  scripts/research/p3_promptrend_recompute.py
# P3's headline = the calibrated-judge_v3 re-grade: p3_v3_rejudge_trials.jsonl (per-cell
# original + v3 verdict), p3_v3_rejudge_pairs.csv (per-primitive), p3_v3_rejudge_stats.json
# (aggregates); p3_v3_from_pairs.py recomputes the funnel + C2 from the CSV, pure stdlib,
# no DB. The cross-objective panel was CUT in the reframe — its artifacts (panel_*) and
# the _openai_chat helper they needed are no longer shipped (a dangling file for a cut
# section is the inverse of the staging bug). reproducibility_gap_pairs.csv stays as the
# original-grade companion (the two grades agree, which is the robustness point).
# The two PrompTrend re-judges (§C2): promptrend_c2_results.json = neutral-objective
# re-judge (per-vuln, recomputes rho=-0.05); promptrend_clean_results.json +
# promptrend_clean_trials.jsonl = judge-ISOLATED re-judge of their stored responses
# (verdicts only, no response text; recomputes our +0.10 vs their -0.07). These are
# P3's own results (P3 ran them); the judge is consumed as a fixed instrument.
# NOTE: P3 deliberately ships NONE of P2's judge-calibration artifacts
# (jbb_judge_report_v3 / wildguard / strongreject / information_disclosure reports,
# scripts/calibration/*, docs/judge-calibration.md). Those are P2's contributed
# results; under the cross-submission overlap rule P3 consumes the judge as a fixed
# instrument and refers to that separate work rather than re-shipping its results.

build p4 anon_supplement_PAPERS_p4.md \
  "" \
  tests/fixtures/memory/leakage_canaries.json \
  scripts/memory/run_leakage_redteam.py \
  scripts/memory/_openai_chat.py \
  scripts/memory/leakage_model_grid.json \
  scripts/memory/select_judge_subset.py \
  scripts/memory/build_label_html.py \
  scripts/memory/calibrate_memory_judge.py \
  "data/research/skill_leak_grid_*.json" \
  "data/research/skill_leak_census_2026-06-16.json" \
  "data/research/skill_leak_tint_2026-06-16.json" \
  "data/research/skill_leak_70b_openrouter.json" \
  "data/research/skill_leak_llama8b_or.json" \
  "data/research/skill_leak_ladder_2026-06-16.json" \
  "data/research/skill_leak_packB_llama_3run.json" \
  "data/research/skill_leak_judgepass_2026-06-16.json" \
  scripts/memory/verify_p4_numbers.py \
  scripts/memory/paired_alignment_test.py \
  scripts/memory/power_sim_canary.py \
  scripts/memory/leakage_grid_mistral_or.json \
  "data/research/skill_leak_mistral_or.json" \
  scripts/memory/leakage_grid_alignment_or.json \
  "data/research/skill_leak_alignment_or.json" \
  scripts/memory/leakage_grid_hermes4_or.json \
  "data/research/skill_leak_hermes4_or.json" \
  scripts/memory/leakage_grid_alignment_or3.json \
  "data/research/skill_leak_alignment_n100_2026-06-28.json" \
  tests/fixtures/memory/leakage_canaries_n100.json \
  scripts/memory/crawl_realskill_canaries.py \
  tests/fixtures/memory/leakage_canaries_realskill.json \
  scripts/memory/leakage_grid_isolator_8b_n100.json \
  "data/research/skill_leak_isolator_8b_n100_2026-06-28.json" \
  scripts/memory/reconstruction_control.py \
  scripts/research/skill_leak_alignment_fig.py \
  scripts/memory/trace2skill_pilot.py \
  scripts/memory/assemble_distilled_fixture.py \
  scripts/memory/pin_distilled_sources.py \
  scripts/memory/fetch_distilled_bodies.py \
  scripts/memory/leakage_grid_distilled_subset.json \
  tests/fixtures/memory/leakage_canaries_distilled.json \
  "data/research/trace2skill_fixture/shard_*.json" \
  "data/research/skill_leak_distilled_llama_instruct.json" \
  "data/research/skill_leak_distilled_gemma.json" \
  "data/research/trace2skill_pilot_*.json"
# The internal lab note docs/research/skill_pool_leakage.md is deliberately NOT
# shipped: it is a working narration carrying superseded n=4 workshop numbers (the
# "Llama scale helps 85->65" framing the paper dissolves), a Groq provenance the
# paper reframes onto Featherless, dead file pointers, and workshop/venue process
# detail (a double-blind hazard). The judge-decidability result it narrated is read
# directly from the marker_only_rate / judge_increment_rate fields in the shipped
# grid/census JSON; skill_leak_judgepass_2026-06-16.json is the judge-ON capture
# behind the "15 of 20 via marker, 0 via judge" sentence.
# P4 ships ALL data behind the 22-model census: the 19 Featherless-live models
# (census/grid/tint) PLUS the 3 large 70B-72B models + the cross-provider Llama-8B
# (70b_openrouter + llama8b_or, the 15-pt serving-stack gap), the varying Qwen scale
# rungs (ladder, the 0.5B/1.5B three-run means), and the disjoint-pack robustness
# check (packB_llama_3run, instruct 82% vs abliterated 98%). Without these a reviewer
# fetching the named files would find a 19-model census, not 22, and could not
# reproduce the +97 CoT surface, the provider gap, or the second-pack ordering.

rm -rf "$TMP"
echo "done — attach each supplement_p*.zip to its paper's OpenReview submission."
