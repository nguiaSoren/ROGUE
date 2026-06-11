import Link from "next/link";
import { redirect } from "next/navigation";
import {
  platformApi,
  type AssuranceReportJson,
  type FrameworkRef,
} from "@/lib/platform-api";
import { getApiKey } from "@/lib/session";

/** Same-origin export proxy, the bearer is attached server-side by the route
 *  handler, never placed in a client href (see app/api/scans/[scanId]/assurance). */
function exportHref(scanId: string): string {
  return `/api/scans/${encodeURIComponent(scanId)}/assurance?format=json`;
}

/**
 * /scans/{scanId}/assurance, a completed scan's AI Red-Team Assurance Report (server component).
 *
 * The "credibility document" for one deployment: a prominent NON-CERTIFICATION
 * disclaimer banner, the scope + posture summary (deployment under test, window,
 * corpus-as-of, attacks reproduced, breaching primitives), breach breakdowns
 * (by severity / verdict / exfiltration channel), framework coverage
 * (OWASP / MITRE ATLAS / NIST — the credibility centerpiece), and evidence &
 * attestation. Reads `GET /v1/scans/{id}/assurance?format=json`, the persisted
 * `render_json()` (src/rogue/governance/assurance.py:412). The page never recomputes
 * a number; everything arrives pre-derived from the crosswalk + posture builder.
 *
 * Auth mirrors the report page: `(app)/layout.tsx` gates the session; we re-read
 * the key here (server-only) for the fetch. A `not_ready`/404 means the scan isn't
 * completed yet; we surface "not ready" rather than a hard error. Honesty rule:
 * empty/null sections (no attestation, no exfil channels, no families) render an
 * explicit "none / unattested" note — never copy that could imply safety.
 */
export const dynamic = "force-dynamic"; // tenant data, never statically cached

const SEVERITY_CLASS: Record<"critical" | "high" | "medium" | "low", string> = {
  critical: "border-rogue-red/40 bg-rogue-red/10 text-rogue-red",
  high: "border-orange-500/40 bg-orange-500/10 text-orange-300",
  medium: "border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
  low: "border-blue-500/40 bg-blue-500/10 text-blue-300",
};

export default async function AssurancePage({
  params,
}: {
  params: Promise<{ scanId: string }>;
}) {
  const { scanId } = await params;

  const key = await getApiKey();
  if (!key) redirect("/sign-in");

  let report: AssuranceReportJson | null = null;
  let loadError: string | null = null;
  let notReady = false;
  try {
    report = await platformApi.getAssurance(scanId, key);
  } catch (e) {
    // 404 / not-ready while the scan is still queued/running — treat as "not yet".
    const msg = e instanceof Error ? e.message : "Failed to load assurance report.";
    if (/not[_ ]?ready|404/i.test(msg)) notReady = true;
    else loadError = msg;
  }

  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-10 space-y-8">
        <header className="flex items-start justify-between gap-4 sm:gap-6 flex-wrap animate-rogue-fade-up">
          <div className="space-y-2 min-w-0">
            <Link
              href={`/scans/${encodeURIComponent(scanId)}/report`}
              className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green hover:underline"
            >
              ← scan report
            </Link>
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight break-words">
              AI Red-Team Assurance Report
            </h1>
            {report && (
              <p className="text-sm text-muted-foreground font-mono break-words">
                {report.scope.config_name || report.scope.target_model || "deployment"} ·{" "}
                {report.posture.n_primitives} attacks reproduced
              </p>
            )}
          </div>

          {report && (
            <div className="flex items-center gap-2 font-mono text-xs">
              <a
                href={exportHref(scanId)}
                className="uppercase tracking-[0.15em] border border-border rounded-md px-3 py-1.5 hover:bg-card/40 transition-colors"
              >
                JSON
              </a>
            </div>
          )}
        </header>

        {loadError ? (
          <div className="rounded-lg border border-rogue-red/40 bg-rogue-red/10 p-6 font-mono text-sm text-rogue-red">
            <p className="font-bold">Couldn&apos;t load assurance report</p>
            <p className="mt-1 text-xs opacity-80">{loadError}</p>
          </div>
        ) : notReady ? (
          <div className="rounded-lg border border-border p-6 font-mono text-sm text-muted-foreground">
            <p>Assurance report not ready, this scan hasn&apos;t completed yet.</p>
            <Link
              href={`/scans/${encodeURIComponent(scanId)}`}
              className="mt-3 inline-flex text-xs uppercase tracking-[0.15em] text-rogue-green hover:underline"
            >
              ← watch scan progress
            </Link>
          </div>
        ) : report ? (
          <AssuranceBody report={report} scanId={scanId} />
        ) : null}
      </div>
    </main>
  );
}

function AssuranceBody({
  report,
  scanId,
}: {
  report: AssuranceReportJson;
  scanId: string;
}) {
  return (
    <>
      {/* (a) Non-certification disclaimer — mandatory, the lead element, visually
          unmistakable that this is NOT a certification. */}
      <NonCertificationBanner text={report.non_certification} />

      {/* (b) Scope & posture. */}
      <ScopeSection report={report} />
      <PostureSection report={report} />

      {/* (c) Breach breakdowns: by severity, by verdict, by exfiltration channel. */}
      <BreakdownsSection report={report} />

      {/* (d) Framework coverage — the credibility centerpiece. */}
      <FrameworksSection report={report} />

      {/* (e) Evidence & attestation. */}
      <AttestationSection report={report} />

      {/* (f) Link back to the scan report. */}
      <div className="rounded-lg border border-border bg-card/30 p-5">
        <Link
          href={`/scans/${encodeURIComponent(scanId)}/report`}
          className="inline-flex text-xs uppercase tracking-[0.15em] font-mono text-rogue-green hover:underline"
        >
          ← view the full scan report
        </Link>
      </div>
    </>
  );
}

/** The non-certification disclaimer, rendered as a prominent, clearly-not-a-cert banner. */
function NonCertificationBanner({ text }: { text: string }) {
  return (
    <section
      role="note"
      className="rounded-lg border-2 border-yellow-500/50 bg-yellow-500/10 p-5 sm:p-6 space-y-2 animate-rogue-fade-up"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] font-bold text-yellow-300">
        Not a certification · informational assurance only
      </p>
      <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap break-words">
        {text}
      </p>
    </section>
  );
}

/** Scope: the deployment under test + the reproduction window. */
function ScopeSection({ report }: { report: AssuranceReportJson }) {
  const s = report.scope;
  const window =
    s.window_start || s.window_end
      ? `${s.window_start ? fmtDate(s.window_start) : "—"} → ${
          s.window_end ? fmtDate(s.window_end) : "—"
        }`
      : "all-time";
  return (
    <section className="rogue-card p-6 sm:p-7 space-y-4 animate-rogue-fade-up">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        Deployment under test
      </h2>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <Field label="Configuration" value={s.config_name || s.config_id || "—"} />
        <Field label="Target model" value={s.target_model || "—"} mono />
        <Field label="System prompt" value={s.system_prompt_label || "—"} />
        <Field label="Reproduction window" value={window} mono />
        <Field
          label="Tools"
          value={s.tools.length > 0 ? s.tools.join(", ") : "none configured"}
          mono
          muted={s.tools.length === 0}
        />
        <Field label="Corpus as of" value={report.posture.corpus_as_of || "—"} mono />
      </dl>
    </section>
  );
}

/** Posture: the headline counts — attacks reproduced, trials, breaching primitives. */
function PostureSection({ report }: { report: AssuranceReportJson }) {
  const p = report.posture;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      <Kpi label="Attacks reproduced">
        <span className="text-2xl font-bold tabular-nums">{p.n_primitives}</span>
      </Kpi>
      <Kpi label="Trials">
        <span className="text-2xl font-bold tabular-nums">{p.n_trials}</span>
      </Kpi>
      <Kpi label="Breaching primitives">
        <span
          className={`text-2xl font-bold tabular-nums ${
            p.n_breaching_primitives > 0 ? "text-rogue-red" : "text-rogue-green"
          }`}
        >
          {p.n_breaching_primitives}
        </span>
      </Kpi>
    </div>
  );
}

/** Breakdowns: by severity (reusing the severity color vocabulary), by verdict,
 *  and by exfiltration channel. Empty maps get an honest "none observed" note. */
function BreakdownsSection({ report }: { report: AssuranceReportJson }) {
  const p = report.posture;
  const severities: Array<["critical" | "high" | "medium" | "low", number]> = [
    ["critical", p.by_severity.critical],
    ["high", p.by_severity.high],
    ["medium", p.by_severity.medium],
    ["low", p.by_severity.low],
  ];
  const verdicts = Object.entries(p.by_verdict);
  const exfil = Object.entries(p.by_exfil_method);

  return (
    <section className="space-y-3">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
        Breach breakdown
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* By severity */}
        <div className="rounded-lg border border-border bg-card/30 p-5 space-y-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
            By severity
          </p>
          <ul className="space-y-1.5">
            {severities.map(([sev, n]) => (
              <li key={sev} className="flex items-center justify-between gap-3">
                <span
                  className={`inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.15em] font-bold ${SEVERITY_CLASS[sev]}`}
                >
                  {sev}
                </span>
                <span
                  className={`font-mono text-sm font-bold tabular-nums ${
                    n > 0 ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {n}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* By verdict */}
        <div className="rounded-lg border border-border bg-card/30 p-5 space-y-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
            By verdict
          </p>
          {verdicts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No trials recorded.</p>
          ) : (
            <ul className="space-y-1.5">
              {verdicts.map(([verdict, n]) => (
                <li key={verdict} className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-foreground/90 break-words">
                    {verdict.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`font-mono text-sm font-bold tabular-nums ${
                      verdict === "full_breach" && n > 0
                        ? "text-rogue-red"
                        : "text-foreground"
                    }`}
                  >
                    {n}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* By exfiltration channel */}
        <div className="rounded-lg border border-border bg-card/30 p-5 space-y-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
            By exfiltration channel
          </p>
          {exfil.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No exfiltration channel observed in breaching trials.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {exfil.map(([method, n]) => (
                <li key={method} className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-orange-300 break-words">
                    {method.replace(/_/g, " ")}
                  </span>
                  <span className="font-mono text-sm font-bold tabular-nums text-foreground">
                    {n}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

/** Framework coverage — OWASP LLM Top 10 / MITRE ATLAS / NIST AI RMF. The
 *  credibility centerpiece. `frameworks_line` is the ready-made compact summary. */
function FrameworksSection({ report }: { report: AssuranceReportJson }) {
  const fw = report.frameworks;
  const hasAny = fw.owasp.length > 0 || fw.atlas.length > 0 || !!fw.nist;

  return (
    <section className="rogue-card p-6 sm:p-7 space-y-5 animate-rogue-fade-up">
      <div className="space-y-1.5">
        <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
          Framework coverage
        </h2>
        {report.frameworks_line && (
          <p className="font-mono text-xs text-muted-foreground break-words">
            {report.frameworks_line}
          </p>
        )}
      </div>

      {!hasAny ? (
        <p className="text-sm text-muted-foreground">
          No framework mapping for the families in scope.
        </p>
      ) : (
        <div className="space-y-5">
          <FrameworkList
            label="OWASP LLM Top 10 (2025)"
            refs={fw.owasp}
            empty="No OWASP mapping for the families in scope."
          />
          <FrameworkList
            label="MITRE ATLAS"
            refs={fw.atlas}
            empty="No MITRE ATLAS technique cleanly maps to the families in scope."
          />
          <div className="space-y-2">
            <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
              NIST AI RMF
            </p>
            {fw.nist ? (
              <p className="text-sm text-foreground/90">{fw.nist}</p>
            ) : (
              <p className="text-sm text-muted-foreground">No NIST tag for the families in scope.</p>
            )}
          </div>
        </div>
      )}

      <FamiliesSection families={report.families} />
    </section>
  );
}

/** A titled list of framework IDs (OWASP / ATLAS), rendering "ID — Title". */
function FrameworkList({
  label,
  refs,
  empty,
}: {
  label: string;
  refs: FrameworkRef[];
  empty: string;
}) {
  return (
    <div className="space-y-2">
      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        {label}
      </p>
      {refs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {refs.map((r) => (
            <li
              key={r.id}
              className="inline-flex items-baseline gap-1.5 rounded-md border border-border bg-card/40 px-2.5 py-1"
            >
              <span className="font-mono text-xs font-bold text-foreground">{r.id}</span>
              {r.title && (
                <span className="text-xs text-muted-foreground">{r.title}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The ROGUE attack families covered by this assurance report. */
function FamiliesSection({ families }: { families: string[] }) {
  return (
    <div className="space-y-2 border-t border-border pt-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
        Attack families reproduced
      </p>
      {families.length === 0 ? (
        <p className="text-sm text-muted-foreground">No attack families in scope.</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {families.map((f) => (
            <li
              key={f}
              className="inline-flex items-center rounded-md border border-border bg-card/40 px-2.5 py-1 font-mono text-xs text-foreground/90"
            >
              {f.replace(/_/g, " ")}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Evidence & attestation. When the attestation is non-null we render the
 *  verifiable chain fields; when null we say so honestly — informational only. */
function AttestationSection({ report }: { report: AssuranceReportJson }) {
  const a = report.attestation;
  return (
    <section className="rogue-card p-6 sm:p-7 space-y-4 animate-rogue-fade-up">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        Evidence &amp; attestation
      </h2>

      {a === null ? (
        <div className="rounded-md border border-border/60 bg-card/20 p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted-foreground mb-1">
            Unattested
          </p>
          <p className="text-sm leading-relaxed text-foreground/90">
            This report is not cryptographically attested — it is informational only. No
            signed attestation entry was attached to this scan.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-foreground/90 leading-relaxed">
            Verifiable pointer at a signed attestation entry. Re-resolve it against the
            per-org attestation chain to confirm integrity.
          </p>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <Field label="Org" value={a.org_id || "—"} mono />
            <Field label="Sequence" value={a.seq === null ? "—" : String(a.seq)} mono />
            <Field label="Corpus as of" value={a.corpus_as_of || "—"} mono />
            <Field label="Framing" value={a.framing || "—"} />
          </dl>
          {a.entry_hash && (
            <Mono label="Entry hash" value={a.entry_hash} />
          )}
          {a.signature && <Mono label="Signature" value={a.signature} />}
        </div>
      )}

      {report.threat_brief_ref ? (
        <p className="text-xs text-muted-foreground font-mono border-t border-border pt-3 break-words">
          Threat brief: {report.threat_brief_ref}
        </p>
      ) : null}
    </section>
  );
}

// --------------------------------------------------------------------------
// Small presentational primitives (Kpi mirrors the report page's Kpi).
// --------------------------------------------------------------------------

function Kpi({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-card/30 px-4 py-3 space-y-1.5">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <div className="leading-tight">{children}</div>
    </div>
  );
}

function Field({
  label,
  value,
  mono = false,
  muted = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="space-y-1 min-w-0">
      <dt className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={`break-words ${mono ? "font-mono text-xs" : "text-sm"} ${
          muted ? "text-muted-foreground" : "text-foreground/90"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

/** A full-width monospace value (hashes/signatures) that needs to wrap. */
function Mono({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <pre className="overflow-x-auto rounded-md border border-border bg-card/60 p-3 font-mono text-[11px] text-foreground/90 whitespace-pre-wrap break-all">
        {value}
      </pre>
    </div>
  );
}

/** Render an ISO date as a date-only string; degrade to the raw value on parse failure. */
function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}
