/**
 * Leaderboard source data — a MIRROR of `src/rogue/data/demo_stats.json` (the all-time redacted
 * matrix export: 11,973 calibrated-judge trials, real verdicts/rates). It is bundled statically here
 * — rather than read from the live `breachMatrix()` API — on purpose: the live matrix currently holds
 * only a thin current-run slice (~50 trials/model, noisy), while this snapshot is the robust, stable
 * standings. Bundling it ALSO guarantees the public `/leaderboard` and the `rogue try` CLI overlay cite
 * IDENTICAL numbers (the CLI reads the same demo_stats.json).
 *
 * KEEP IN SYNC: when `src/rogue/data/demo_stats.json` is regenerated, update this file in the same
 * stride (both derive from tests/fixtures/demo_snapshot.json.gz via scripts/ops/seed_demo_data.py).
 *
 * SNAPSHOT, NOT LIVE: these are a periodic measured snapshot of the all-time matrix, measured as of
 * 2026-06-07 (the v3 re-judge of the stored breach matrix). The numbers are real historical
 * measurements — they refresh only when ROGUE re-reproduces and this file is regenerated, NOT on
 * every page load. The /leaderboard page labels them "measured as of 2026-06-07" accordingly.
 */
export const LEADERBOARD_TOTAL_TRIALS = 11973;
export const LEADERBOARD_JUDGE = "calibrated v3 judge · [withheld — under anonymized review] on JailbreakBench";

export type LeaderboardModel = {
  model_label: string;
  target_model: string;
  /** Mean any-breach rate (partial|full) across attack families — the ranking key. */
  mean_breach_rate: number;
  worst_family: string;
  worst_breach_rate: number;
  n_trials: number;
  n_families: number;
};

/** The 8 target endpoints ROGUE tests (6 production text models + 2 audio targets, sampled lighter
 *  at ~185 trials each). Order is irrelevant (the board re-sorts by resistance). */
export const LEADERBOARD_MODELS: LeaderboardModel[] = [
  { model_label: "claude-opus-4-8", target_model: "anthropic/claude-opus-4-8", mean_breach_rate: 0.0067, worst_family: "indirect_prompt_injection", worst_breach_rate: 0.0606, n_trials: 537, n_families: 10 },
  { model_label: "claude-haiku-4-5", target_model: "anthropic/claude-haiku-4-5", mean_breach_rate: 0.0276, worst_family: "training_data_extraction", worst_breach_rate: 0.2892, n_trials: 2223, n_families: 15 },
  { model_label: "gpt-5.4-nano", target_model: "openai/gpt-5.4-nano", mean_breach_rate: 0.0329, worst_family: "training_data_extraction", worst_breach_rate: 0.1687, n_trials: 2222, n_families: 15 },
  { model_label: "llama-3.1-8b-instruct", target_model: "meta-llama/llama-3.1-8b-instruct", mean_breach_rate: 0.0904, worst_family: "training_data_extraction", worst_breach_rate: 0.3976, n_trials: 2144, n_families: 15 },
  { model_label: "gemini-3.1-flash-lite", target_model: "google/gemini-3.1-flash-lite", mean_breach_rate: 0.1531, worst_family: "training_data_extraction", worst_breach_rate: 0.7745, n_trials: 2288, n_families: 15 },
  { model_label: "gpt-audio-mini", target_model: "openai/gpt-audio-mini", mean_breach_rate: 0.1784, worst_family: "training_data_extraction", worst_breach_rate: 0.7368, n_trials: 185, n_families: 9 },
  { model_label: "mistral-small-2603", target_model: "mistralai/mistral-small-2603", mean_breach_rate: 0.3052, worst_family: "training_data_extraction", worst_breach_rate: 0.939, n_trials: 2189, n_families: 15 },
  { model_label: "voxtral-small-24b-2507", target_model: "mistralai/voxtral-small-24b-2507", mean_breach_rate: 0.4391, worst_family: "dan_persona", worst_breach_rate: 1.0, n_trials: 185, n_families: 9 },
];

/* --- Open-source models — SEPARATE methodology --------------------------------------------------
 * These 16 open-weight models were scanned via Featherless with the curated SINGLE-SHOT aggressive
 * jailbreak pack (~37–45 trials/model, primitive-level any-breach rate). This is DELIBERATELY a
 * different, lighter methodology than the 8 models above (deep escalation + PAIR pipeline, ~2,000
 * trials each) — do NOT merge the two into one ranking; the page renders them as a separate section
 * with its own label. Measured 2026-06-20. Regenerate via scripts/sweep/build_oss_leaderboard.py
 * (reads the fl-* breach_results) and keep src/rogue/data/oss_leaderboard_stats.json in sync. */
export const LEADERBOARD_OSS_MEASURED = "2026-06-20";
export const LEADERBOARD_OSS_METHOD =
  "single-shot aggressive jailbreak pack · primitive-level any-breach";

export const LEADERBOARD_OSS_MODELS: LeaderboardModel[] = [
  { model_label: "DeepSeek-R1-Distill-Llama-70B", target_model: "deepseek-ai/DeepSeek-R1-Distill-Llama-70B", mean_breach_rate: 0.2, worst_family: "multi_turn_gradient", worst_breach_rate: 1.0, n_trials: 42, n_families: 15 },
  { model_label: "DeepSeek-V3.1", target_model: "deepseek-ai/DeepSeek-V3.1", mean_breach_rate: 0.2, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 39, n_families: 15 },
  { model_label: "Qwen2.5-72B-Instruct", target_model: "Qwen/Qwen2.5-72B-Instruct", mean_breach_rate: 0.2, worst_family: "indirect_prompt_injection", worst_breach_rate: 1.0, n_trials: 38, n_families: 15 },
  { model_label: "MiniMax-M2", target_model: "MiniMaxAI/MiniMax-M2", mean_breach_rate: 0.2667, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 38, n_families: 15 },
  { model_label: "Meta-Llama-3.1-8B-Instruct", target_model: "meta-llama/Meta-Llama-3.1-8B-Instruct", mean_breach_rate: 0.3333, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "QwQ-32B", target_model: "Qwen/QwQ-32B", mean_breach_rate: 0.3333, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 40, n_families: 15 },
  { model_label: "GLM-4-9B-0414", target_model: "zai-org/GLM-4-9B-0414", mean_breach_rate: 0.4, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Mistral-Small-24B-Instruct-2501", target_model: "mistralai/Mistral-Small-24B-Instruct-2501", mean_breach_rate: 0.4667, worst_family: "obfuscation_encoding", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Qwen3-235B-A22B", target_model: "Qwen/Qwen3-235B-A22B", mean_breach_rate: 0.4667, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 37, n_families: 15 },
  { model_label: "Qwen3-32B", target_model: "Qwen/Qwen3-32B", mean_breach_rate: 0.4667, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 40, n_families: 15 },
  { model_label: "Mistral-7B-Instruct-v0.2", target_model: "mistralai/Mistral-7B-Instruct-v0.2", mean_breach_rate: 0.4667, worst_family: "multi_turn_gradient", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Meta-Llama-3.1-70B-Instruct", target_model: "meta-llama/Meta-Llama-3.1-70B-Instruct", mean_breach_rate: 0.4667, worst_family: "direct_instruction_override", worst_breach_rate: 1.0, n_trials: 38, n_families: 15 },
  { model_label: "Qwen2.5-7B-Instruct-abliterated", target_model: "huihui-ai/Qwen2.5-7B-Instruct-abliterated", mean_breach_rate: 0.5333, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Qwen2.5-7B-Instruct", target_model: "Qwen/Qwen2.5-7B-Instruct", mean_breach_rate: 0.5333, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Mistral-Nemo-Instruct-2407", target_model: "mistralai/Mistral-Nemo-Instruct-2407", mean_breach_rate: 0.6, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
  { model_label: "Meta-Llama-3.1-8B-Instruct-abliterated", target_model: "huihui-ai/Meta-Llama-3.1-8B-Instruct-abliterated", mean_breach_rate: 0.7333, worst_family: "tool_use_hijack", worst_breach_rate: 1.0, n_trials: 45, n_families: 15 },
];
