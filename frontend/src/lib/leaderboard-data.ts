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
 */
export const LEADERBOARD_TOTAL_TRIALS = 11973;
export const LEADERBOARD_JUDGE = "calibrated v3 judge · 89.3% human agreement on JailbreakBench";

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

/** The 8 models ROGUE tests, all-time. Order is irrelevant (the board re-sorts by resistance). */
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
