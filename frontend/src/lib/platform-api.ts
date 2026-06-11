/**
 * Typed client for the authenticated `/v1` platform API (the SaaS product surface).
 *
 * This is the SECOND, parallel client to `lib/api.ts` (the credential-less `/api/*`
 * reader the public marketing/threat-intel pages use). It carries the SAME Render
 * cold-start resilience as `apiGet`, the 502/503/504 retry with 1.5s→3s backoff
 * and the 12s per-attempt abort (mirroring `lib/api.ts:23-28`, `:37-60`), but with
 * three differences driven by tenancy (see docs/platform/dashboard/pages-and-routes.md §3-4):
 *
 *  1. It injects an `Authorization: Bearer <key>` header. The bearer is passed in as
 *     an argument and is NEVER `NEXT_PUBLIC_*`, so the secret never ships to the browser.
 *     The key comes from the httpOnly session cookie (`lib/session.ts:getApiKey()`), read
 *     server-side by the `/api/*` proxy route handlers that wrap these calls; client
 *     components hit those same-origin proxies and never see the bearer. There is no
 *     placeholder fallback, `resolveKey()` throws `ApiV1Error(401, "no_session", …)`
 *     when no key is supplied.
 *  2. Tenant data is per-request, not ISR, every call is `cache: "no-store"`.
 *  3. On a non-OK response it reads the error envelope `{ error: { code, message } }`
 *     (ARCHITECTURE §5) and throws an `ApiV1Error` carrying it, so product pages can
 *     render an explicit error state instead of silently serving stale cross-tenant HTML.
 *
 * Types `ScanRecord` / `ScanStatus` / `ScanSpec` mirror `src/rogue/platform/schemas.py`;
 * `ScanReportJson` / `Finding` mirror `ScanReport.to_dict()` (`src/rogue/report.py:130`)
 * plus the platform `score` the report route adds.
 */

// Server-side base for the hosted platform API. Defaults to the live service; override with
// API_BASE / NEXT_PUBLIC_API_BASE. This client runs server-side only (Server Components + Route
// Handlers) so it reads the real bearer from the session, the key is never shipped to the browser.
const API_BASE =
  process.env.API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "https://rogue-private.onrender.com";

// Same cold-start posture as lib/api.ts: Render's free tier returns transient
// 502/503/504 (or drops the socket) for the first request or two while it boots.
const GATEWAY_STATUSES = new Set([502, 503, 504]);
const MAX_RETRIES = 2;
const ATTEMPT_TIMEOUT_MS = 12_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Resolve the bearer for a call, required (the caller reads it from the server session). */
function resolveKey(key?: string): string {
  if (!key) {
    throw new ApiV1Error(401, "no_session", "no API key in session, sign in first");
  }
  return key;
}

/** The `{ error: { code, message, details? } }` envelope the `/v1` surface returns (ARCHITECTURE §5). */
export type ApiV1ErrorEnvelope = {
  error: { code: string; message: string; details?: unknown };
};

export class ApiV1Error extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiV1Error";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type FetchOpts = {
  method?: string;
  /** JSON body for POSTs. */
  body?: unknown;
  /** Extra headers (e.g. Idempotency-Key for POST /v1/scans). */
  headers?: Record<string, string>;
  /** Override the default `Accept` (e.g. the report route's html/pdf formats). */
  accept?: string;
};

async function apiV1<T>(path: string, key: string | undefined, opts: FetchOpts = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${resolveKey(key)}`,
    Accept: opts.accept ?? "application/json",
    ...opts.headers,
  };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let lastError: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const r = await fetch(url, {
        method: opts.method ?? "GET",
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        // Tenant data is private + per-request, never the public corpus's 300s ISR.
        cache: "no-store",
        signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS),
      });

      if (GATEWAY_STATUSES.has(r.status) && attempt < MAX_RETRIES) {
        await sleep(1500 * (attempt + 1)); // 1.5s, then 3s, ride out the cold boot
        continue;
      }

      if (!r.ok) {
        // Surface the error envelope's code/message instead of a bare status.
        let code = "error";
        let message = `${path} → ${r.status} ${r.statusText}`;
        let details: unknown;
        try {
          const env = (await r.json()) as Partial<ApiV1ErrorEnvelope>;
          if (env?.error) {
            code = env.error.code ?? code;
            message = env.error.message ?? message;
            details = env.error.details;
          }
        } catch {
          /* non-JSON error body, keep the status-line message */
        }
        throw new ApiV1Error(r.status, code, message, details);
      }

      // Non-JSON formats (html/pdf) are fetched as a link by the export buttons, not here;
      // this client only decodes the JSON surface.
      return (await r.json()) as T;
    } catch (e) {
      // An ApiV1Error is a real, decoded API failure, do not retry it as a cold start.
      if (e instanceof ApiV1Error) throw e;
      // Network-level throw (connection reset during cold boot), retry too.
      lastError = e;
      if (attempt < MAX_RETRIES) {
        await sleep(1500 * (attempt + 1));
        continue;
      }
      throw e;
    }
  }
  throw lastError;
}

// --------------------------------------------------------------------------
// Types, mirror src/rogue/platform/schemas.py and src/rogue/report.py.
// --------------------------------------------------------------------------

/** Mirrors `ScanStatus` (src/rogue/platform/schemas.py:16). */
export type ScanStatus = "queued" | "running" | "completed" | "failed" | "canceled";

export const TERMINAL_STATUSES: ReadonlySet<ScanStatus> = new Set<ScanStatus>([
  "completed",
  "failed",
  "canceled",
]);

export function isTerminal(status: ScanStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** Mirrors `TargetSpec.redacted()` (src/rogue/platform/schemas.py:47), the persist-safe snapshot. */
export type RedactedTarget = {
  endpoint?: string | null;
  provider?: string | null;
  model?: string | null;
  system_prompt_len?: number;
  has_api_key?: boolean;
};

/** Mirrors `TargetSpec` (src/rogue/platform/schemas.py:28), what /scans/new posts. */
export type TargetSpec = {
  endpoint?: string | null;
  provider?: string | null;
  model?: string | null;
  /** Raw credential at the API boundary; never persisted/echoed. */
  api_key?: string | null;
  system_prompt?: string;
};

/** Mirrors `ScanSpec` (src/rogue/platform/schemas.py:58), the POST /v1/scans body. */
export type ScanSpec = {
  target: TargetSpec;
  /** "pack" = a small curated JSON pack; "repertoire" = the live harvested corpus (ROGUE's full
   *  arsenal, capped at max_tests); "ladder" = escalate each goal through ROGUE's full multi-tier
   *  arsenal (graduated techniques + chain-of-jailbreak + structured-data + image/audio renderers), 
   *  the deepest and most expensive mode. Default "pack". Mirrors `ScanSpec.mode`. */
  mode?: "pack" | "repertoire" | "ladder";
  pack?: string;
  attacks?: string[] | null;
  max_tests?: number;
  n_trials?: number;
  budget?: number | null;
};

/** Mirrors `ScanRecord` (src/rogue/platform/schemas.py:69), GET /v1/scans/{id}. */
export type ScanRecord = {
  scan_id: string;
  org_id: string;
  project_id?: string | null;
  status: ScanStatus;
  progress: number; // 0–100
  n_tests: number;
  n_completed: number;
  n_breaches: number;
  top_attack?: string | null;
  /** 0–100 headline; null while running, set at completion (ARCHITECTURE §5). */
  score?: number | null;
  cost_usd: number;
  report_id?: string | null;
  error?: string | null;
  target: RedactedTarget;
  pack: string;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

/** Page envelope for the cursor-paginated scan list (GET /v1/scans). */
export type ScanListResponse = {
  scans: ScanRecord[];
  next_cursor?: string | null;
};

/** Mirrors `Finding` (src/rogue/report.py:51), incl. the render-time `remediation` (§report-views.md 2). */
export type Finding = {
  family: string;
  technique: string;
  vector: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  success_rate: number;
  n_trials: number;
  n_breach: number;
  example_attack?: string | null;
  example_response?: string | null;
  /** Plain-language "what this attack is + why it matters" (non-expert framing);
   *  surfaced by the report route, absent on older runs. */
  explanation?: string | null;
  /** Render-time concern surfaced by the report route; absent on older runs. */
  remediation?: string | null;
};

/** Mirrors `ScanReport.to_dict()` (src/rogue/report.py:130) PLUS the platform `score`
 *  and the report-route-added `recommendations[]` (docs/platform/dashboard/report-views.md §2). */
export type ScanReportJson = {
  target: string;
  n_tests: number;
  n_breaches: number;
  breach_rate: number;
  top_attack?: string | null;
  cost_usd: number;
  findings: Finding[];
  /** Markdown "forward-to-your-boss" overview rendered prominently below the
   *  headline; absent on older runs (the exec-summary block degrades out). */
  executive_summary?: string | null;
  /** 0–100 headline added by the report route on top of the SDK dataclass. */
  score?: number | null;
  /** Banded headline level for `score` (critical/high/medium/low); from the report
   *  route's `scoring.risk_level`. Absent on older runs, derive from `score` then. */
  risk_level?: "critical" | "high" | "medium" | "low" | null;
  /** One-line plain-English description of how `score` is computed (report caption). */
  score_methodology?: string | null;
  /** Report-level "what to do next"; absent on older runs (panel degrades). */
  recommendations?: string[] | null;
};

export type ReportFormat = "json" | "html" | "pdf";

// --------------------------------------------------------------------------
// Assurance report, mirrors `render_json()` (src/rogue/governance/assurance.py:412).
// "AI Red-Team Assurance Report" — posture summary + framework crosswalk coverage
// over the corpus reproduced against one deployment. NOT a certification (see
// `non_certification`, always present, surfaced as the page's lead banner).
// --------------------------------------------------------------------------

/** One titled framework ID, mirrors `frameworks_to_dict` (src/rogue/taxonomy/crosswalk.py:300). */
export type FrameworkRef = { id: string; title: string };

/** The `frameworks` object: titled OWASP/ATLAS lists + a coarse NIST prose tag. */
export type FrameworkCoverage = {
  owasp: FrameworkRef[];
  atlas: FrameworkRef[];
  nist: string;
};

/** Verifiable pointer at an already-signed attestation entry (assurance.py:124 `AttestationRef`). */
export type AssuranceAttestation = {
  org_id: string;
  seq: number | null;
  entry_hash: string;
  signature: string;
  corpus_as_of: string;
  framing: string;
};

/** Mirrors `render_json()` (src/rogue/governance/assurance.py:412). */
export type AssuranceReportJson = {
  report_type: "ai_red_team_assurance";
  /** The full non-certification disclaimer string; render PROMINENTLY at top. */
  non_certification: string;
  scope: {
    customer_id: string;
    config_id: string;
    config_name: string;
    target_model: string;
    system_prompt_label: string;
    tools: string[];
    window_start: string | null;
    window_end: string | null;
  };
  posture: {
    corpus_as_of: string;
    n_primitives: number;
    n_trials: number;
    n_breaching_primitives: number;
    by_severity: { critical: number; high: number; medium: number; low: number };
    by_verdict: Record<string, number>;
    by_exfil_method: Record<string, number>;
  };
  families: string[];
  frameworks: FrameworkCoverage;
  /** Ready-made compact one-line framework summary. */
  frameworks_line: string;
  attestation: AssuranceAttestation | null;
  threat_brief_ref: string | null;
};

// --------------------------------------------------------------------------
// API surface, each takes the bearer `key` (server-resolved) as an argument.
// --------------------------------------------------------------------------

export const platformApi = {
  /** POST /v1/scans, create (queue) a scan. Returns the 202 `ScanRecord` (status=queued).
   *  Pass an `idempotencyKey` so a double-submit can't launch two paid scans. */
  createScan: (body: ScanSpec, key?: string, idempotencyKey?: string) =>
    apiV1<ScanRecord>("/v1/scans", key, {
      method: "POST",
      body,
      headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    }),

  /** GET /v1/scans/{id}, the full `ScanRecord` (the poller's route). */
  getScan: (scanId: string, key?: string) =>
    apiV1<ScanRecord>(`/v1/scans/${encodeURIComponent(scanId)}`, key),

  /** POST /v1/scans/{id}/cancel, request cancellation; returns the updated `ScanRecord`. */
  cancelScan: (scanId: string, key?: string) =>
    apiV1<ScanRecord>(`/v1/scans/${encodeURIComponent(scanId)}/cancel`, key, { method: "POST" }),

  /** GET /v1/scans, newest-first, cursor-paginated list. */
  listScans: (
    key?: string,
    params?: { project_id?: string; limit?: number; cursor?: string },
  ) => {
    const q = new URLSearchParams();
    if (params?.project_id) q.set("project_id", params.project_id);
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    if (params?.cursor) q.set("cursor", params.cursor);
    const qs = q.toString();
    return apiV1<ScanListResponse>(`/v1/scans${qs ? `?${qs}` : ""}`, key);
  },

  /** GET /v1/scans/{id}/report?format=…, the completed report. Only `json` is
   *  decoded here; `html`/`pdf` are fetched as links by the export buttons (see
   *  reportUrl). */
  getReport: (scanId: string, key?: string, format: ReportFormat = "json") =>
    apiV1<ScanReportJson>(
      `/v1/scans/${encodeURIComponent(scanId)}/report?format=${format}`,
      key,
    ),

  /** GET /v1/scans/{id}/assurance?format=json, the per-scan AI Red-Team Assurance Report. */
  getAssurance: (scanId: string, key?: string) =>
    apiV1<AssuranceReportJson>(
      `/v1/scans/${encodeURIComponent(scanId)}/assurance?format=json`,
      key,
    ),

  /** POST /v1/validate, dry-run a target (reachability/credentials) before a paid scan. */
  validateTarget: (body: TargetSpec, key?: string) =>
    apiV1<{
      target: string;
      reachable: boolean;
      authenticated: boolean;
      model_responds: boolean;
      supports_image: boolean;
      supports_audio: boolean;
      error: string | null;
      ok: boolean;
    }>(
      "/v1/validate",
      key,
      { method: "POST", body },
    ),
};

/** The bare URL for a report export, for an <a href> / new tab, where the browser
 *  handles the open/download (html/pdf, and json as a raw download). The bearer for
 *  these is supplied by the server-side route handler, not appended here (never put
 *  a secret in a client href). */
export function reportUrl(scanId: string, format: ReportFormat): string {
  return `${API_BASE}/v1/scans/${encodeURIComponent(scanId)}/report?format=${format}`;
}

export { API_BASE };
