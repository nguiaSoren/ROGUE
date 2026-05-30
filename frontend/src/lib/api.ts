/**
 * API client for the ROGUE dashboard.
 *
 * Wraps the 7 endpoints exposed by `src/rogue/api/main.py` with TypeScript
 * types. All fetches go through `apiGet` so the API base URL + cache policy
 * are centralized. Pages are cached + revalidated every 5 minutes (ISR) so
 * visitors get instant loads instead of paying the full Vercel→Render→Neon
 * round-trip on every view; new data in Neon surfaces within the revalidate
 * window. The live SSE ticker is a separate client connection, stays real-time.
 *
 * Spec: ROGUE_PLAN.md §11.1 backend endpoints.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const REVALIDATE_SECONDS = 300;

async function apiGet<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`;
  const r = await fetch(url, { next: { revalidate: REVALIDATE_SECONDS } });
  if (!r.ok) {
    throw new Error(`${path} → ${r.status} ${r.statusText}`);
  }
  return (await r.json()) as T;
}

// --------------------------------------------------------------------------
// Types — mirror the JSON shapes produced by `src/rogue/api/main.py`.
// --------------------------------------------------------------------------

export type SourceProvenance = {
  url: string;
  source_type: string | null;
  bright_data_product: string | null;
  author: string | null;
  fetched_at: string | null;
};

export type AttackPrimitive = {
  primitive_id: string;
  title: string;
  family: string;
  vector: string;
  base_severity: string;
  short_description: string;
  payload_template: string | null;
  reproducibility_score: number | null;
  canonical: boolean;
  cluster_id: string | null;
  discovered_at: string | null;
  secondary_families: string[];
  requires_multi_turn: boolean;
  requires_system_prompt_access: boolean;
  requires_tools: string[];
  sources: SourceProvenance[];
};

export type HealthResponse = {
  status: string;
  db: string;
  n_primitives?: number;
  n_breaches?: number;
  n_configs?: number;
  now: string;
};

export type AttacksResponse = {
  since_days: number;
  family: string | null;
  vector: string | null;
  limit: number;
  // true when nothing was discovered inside the since_days window and the API
  // fell back to the newest rows regardless of recency (so the UI can relabel).
  stale?: boolean;
  count: number;
  attacks: AttackPrimitive[];
};

export type BreachCell = {
  primitive_id: string;
  title: string;
  family: string;
  vector: string;
  deployment_config_id: string;
  config_name: string;
  target_model: string;
  n_trials: number;
  any_breach_rate: number;
  any_breach_ci_lo: number;
  any_breach_ci_hi: number;
  full_breach_rate: number;
  avg_confidence: number | null;
  /** A trial in this cell was graded by the secondary judge because the
   *  primary (Sonnet) judge refused (the [JUDGE_REFUSED→…] flag). */
  refused?: boolean;
};

export type BreachMatrixResponse = {
  target_date: string;
  n_cells: number;
  n_primitives: number;
  families: string[];
  configs: { config_id: string; config_name: string }[];
  cells: BreachCell[];
};

export type BreachedConfigBrief = {
  config_id: string;
  config_name: string;
  target_model: string;
  any_breach_rate: number;
  any_breach_ci_lo: number;
  any_breach_ci_hi: number;
  full_breach_rate: number;
  n_trials: number;
};

export type BreachedPrimitiveBrief = {
  primitive_id: string;
  title: string;
  family: string;
  vector: string;
  severity_score: number;
  severity_tier: string;
  max_any_breach_rate: number;
  breached_configs: BreachedConfigBrief[];
};

export type BriefJson = {
  target_date: string;
  customer_id: string;
  breach_rate_threshold: number;
  summary: {
    new_critical: number;
    new_high: number;
    new_medium: number;
    new_low: number;
    newly_defended: number;
    total_today: number;
    total_yesterday: number;
    net_delta: number;
  };
  new_critical: BreachedPrimitiveBrief[];
  new_high: BreachedPrimitiveBrief[];
  new_medium: BreachedPrimitiveBrief[];
  new_low: BreachedPrimitiveBrief[];
  newly_defended: BreachedPrimitiveBrief[];
};

export type BriefResponse = {
  target_date: string;
  format: "markdown" | "json";
  markdown?: string;
  json?: BriefJson;
  from_disk: boolean;
};

export type BanditArm = {
  arm_id: string;
  pulls: number;
  total_novel: number;
  total_cost_usd: number;
  mean_yield: number;
};

export type BanditStatsResponse = {
  updated_at: string | null;
  seeded_from_corpus_at?: string | null;
  last_live_pulled_at?: string | null;
  epsilon?: number;
  n_arms: number;
  n_warm_arms?: number;
  top_arms: BanditArm[];
  bottom_arms: BanditArm[];
  note?: string;
};

// §10.7 persona augmentation A/B — wrapped-vs-unwrapped breach rate per
// (deployment_config × PAP persuasion technique). See src/rogue/api/main.py
// `persona_stats()` for the source query.
export type PersonaConfigRollup = {
  config_id: string;
  config_name: string;
  target_model: string;
  baseline_n_trials: number;
  baseline_breach_rate: number;
  max_delta: number | null;
  n_techniques_tried: number;
};

export type PersonaCell = {
  config_id: string;
  config_name: string;
  target_model: string;
  persona_used: string;
  is_refusal_fallback: boolean;
  n_wrapped_trials: number;
  n_wrapped_breach: number;
  n_wrapped_full_breach: number;
  wrapped_breach_rate: number;
  baseline_breach_rate: number;
  delta: number;
};

export type PersonaStatsResponse = {
  min_trials: number;
  n_configs_with_baseline: number;
  n_cells: number;
  per_config: PersonaConfigRollup[];
  cells: PersonaCell[];
};

// §10.7 multi-turn escalation A/B — synthesized child breach rate vs the
// harvested single-turn parent baseline, per deployment_config. See
// src/rogue/api/main.py `escalation_stats()`.
export type EscalationConfigRow = {
  config_id: string;
  config_name: string;
  target_model: string;
  parent_n_trials: number;
  child_n_trials: number;
  baseline_breach_rate: number;
  escalated_breach_rate: number;
  delta: number;
};

export type EscalationStatsResponse = {
  min_trials: number;
  n_synthesized_primitives: number;
  n_parents_escalated: number;
  n_configs_with_pairs: number;
  per_config: EscalationConfigRow[];
};

// §10.7 AutoDAN-reframed mutation A/B — fraction of mutation children that
// breached configs that DEFENDED the original wording. Higher score =
// the config was pattern-matching, not understanding. See main.py
// `mutation_stats()`.
export type MutationConfigRow = {
  config_id: string;
  config_name: string;
  target_model: string;
  n_pairs: number;
  n_parent_defended: number;
  n_parent_defended_child_breached: number;
  pattern_matching_score: number | null;
};

export type MutationStatsResponse = {
  min_trials: number;
  evade_threshold: number;
  n_mutation_primitives: number;
  n_parents_mutated: number;
  n_configs_with_pairs: number;
  per_config: MutationConfigRow[];
};

// §10.7 full PAIR — per-config stubbornness (avg iters-to-breach) +
// refinement-type distribution. See main.py `stubbornness_stats()`.
export type StubbornnessConfigRow = {
  config_id: string;
  config_name: string;
  target_model: string;
  n_pair_cells: number;
  n_breached: number;
  avg_iters_to_breach: number | null;
  never_breach_rate: number | null;
  total_attacker_cost_usd: number;
};

export type RefinementTypeCount = {
  refinement_type: string;
  n_steps: number;
};

export type StubbornnessStatsResponse = {
  n_pair_cells: number;
  n_breached: number;
  n_refinement_steps: number;
  per_config: StubbornnessConfigRow[];
  refinement_type_distribution: RefinementTypeCount[];
};

// --------------------------------------------------------------------------
// API surface
// --------------------------------------------------------------------------

export const api = {
  health: () => apiGet<HealthResponse>("/api/health"),
  attacks: (params?: { since_days?: number; family?: string; vector?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.since_days) q.set("since_days", String(params.since_days));
    if (params?.family) q.set("family", params.family);
    if (params?.vector) q.set("vector", params.vector);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiGet<AttacksResponse>(`/api/attacks${qs ? `?${qs}` : ""}`);
  },
  attackDetail: (primitiveId: string) =>
    apiGet<{ primitive: AttackPrimitive; breaches: unknown[] }>(`/api/attacks/${primitiveId}`),
  breachMatrix: (date?: string, include?: "baseline" | "augmented") => {
    const q = new URLSearchParams();
    if (date) q.set("date", date);
    if (include) q.set("include", include);
    const qs = q.toString();
    return apiGet<BreachMatrixResponse>(
      `/api/breaches/matrix${qs ? `?${qs}` : ""}`,
    );
  },
  brief: (date?: string, format: "markdown" | "json" = "markdown") => {
    const q = new URLSearchParams();
    if (date) q.set("date", date);
    q.set("format", format);
    return apiGet<BriefResponse>(`/api/brief?${q.toString()}`);
  },
  banditStats: () => apiGet<BanditStatsResponse>("/api/bandit/stats"),
  personaStats: (minTrials?: number) => {
    const q = new URLSearchParams();
    if (minTrials !== undefined) q.set("min_trials", String(minTrials));
    const qs = q.toString();
    return apiGet<PersonaStatsResponse>(
      `/api/persona/stats${qs ? `?${qs}` : ""}`,
    );
  },
  escalationStats: (minTrials?: number) => {
    const q = new URLSearchParams();
    if (minTrials !== undefined) q.set("min_trials", String(minTrials));
    const qs = q.toString();
    return apiGet<EscalationStatsResponse>(
      `/api/escalation/stats${qs ? `?${qs}` : ""}`,
    );
  },
  mutationStats: (minTrials?: number, evadeThreshold?: number) => {
    const q = new URLSearchParams();
    if (minTrials !== undefined) q.set("min_trials", String(minTrials));
    if (evadeThreshold !== undefined)
      q.set("evade_threshold", String(evadeThreshold));
    const qs = q.toString();
    return apiGet<MutationStatsResponse>(
      `/api/mutation/stats${qs ? `?${qs}` : ""}`,
    );
  },
  stubbornnessStats: () =>
    apiGet<StubbornnessStatsResponse>("/api/stubbornness/stats"),
};
