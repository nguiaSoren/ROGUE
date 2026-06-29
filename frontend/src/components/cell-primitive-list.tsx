"use client";

import type { CellPrimitive } from "@/lib/api";
import { CopyButton, PayloadImage, VerdictBar } from "@/components/matrix-drawer";
import { sourceBackendLabel } from "@/lib/source-backend";

/**
 * Full list of EVERY breaching primitive in one (family × config) cell, the
 * matrix grid only shows the single worst per cell; this expands it. Each card
 * mirrors the drawer's layout (rate + CI, payload, image, verdict histogram,
 * provenance), sorted worst-first by the API.
 */
export function CellPrimitiveList({ primitives }: { primitives: CellPrimitive[] }) {
  if (primitives.length === 0) {
    return (
      <p className="font-mono text-sm text-muted-foreground">
        {"// no breaching primitives (>0% any-breach) in this cell"}
      </p>
    );
  }
  return (
    <div className="space-y-5">
      {primitives.map((p, i) => (
        <CellCard key={p.primitive_id} p={p} rank={i + 1} />
      ))}
    </div>
  );
}

function CellCard({ p, rank }: { p: CellPrimitive; rank: number }) {
  const rate = p.any_breach_rate;
  const rateTint =
    rate >= 0.7 ? "text-rogue-red" : rate >= 0.3 ? "text-orange-300" : "text-rogue-green";

  return (
    <section className="rogue-card border border-border rounded-lg p-5 bg-card/40 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1.5">
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
            #{rank} · {p.vector} · severity {p.base_severity}
          </p>
          <h3 className="text-lg font-bold leading-tight">{p.title}</h3>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {p.short_description}
          </p>
          <div className="flex items-center gap-1.5 flex-wrap">
            {(p.technique === "persona" || p.technique === "pair") && (
              <span
                className="inline-flex items-center gap-1 rounded border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-orange-300"
                title={
                  p.technique === "pair"
                    ? "Only breached after PAIR iterative refinement, not single-shot"
                    : "Only breached after persona-wrap, not single-shot"
                }
              >
                via {p.technique === "pair" ? "PAIR" : "persona"}
              </span>
            )}
            {p.refused && (
              <span className="inline-flex items-center gap-1 rounded border border-rogue-red/30 bg-rogue-red/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-rogue-red">
                judge refused → fallback
              </span>
            )}
          </div>
        </div>
        <div className="text-right shrink-0">
          <p className={`text-3xl font-bold tabular-nums ${rateTint}`}>
            {Math.round(rate * 100)}%
          </p>
          <p className="text-[10px] font-mono text-muted-foreground">
            CI {Math.round(p.any_breach_ci_lo * 100)}–{Math.round(p.any_breach_ci_hi * 100)}% ·
            n={p.n_trials}
          </p>
          <p className="text-[10px] font-mono text-muted-foreground">
            full {Math.round(p.full_breach_rate * 100)}%
            {p.avg_confidence !== null && (
              <> · conf {(p.avg_confidence * 100).toFixed(0)}%</>
            )}
          </p>
        </div>
      </div>

      {(p.example_payload ?? p.payload_template) && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-rogue-green">
              {p.example_payload ? "payload · sent" : "payload_template"}
            </p>
            <CopyButton text={p.example_payload ?? p.payload_template ?? ""} />
          </div>
          <pre className="text-[11px] font-mono leading-relaxed text-foreground/85 bg-card/60 rounded-md p-3 max-h-72 overflow-y-auto whitespace-pre-wrap break-words border border-border/40">
            {p.example_payload ?? p.payload_template}
          </pre>
        </div>
      )}

      {p.has_image && <PayloadImage primitiveId={p.primitive_id} />}

      <VerdictBar
        full={p.histogram.full_breach}
        partial={p.histogram.partial_breach}
        refused={p.histogram.refused}
        evaded={p.histogram.evaded}
        error={p.histogram.error}
        total={
          p.histogram.full_breach +
          p.histogram.partial_breach +
          p.histogram.evaded +
          p.histogram.refused +
          p.histogram.error
        }
      />

      {p.sources && p.sources.length > 0 && (
        <div>
          <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground mb-1.5">
            provenance
          </p>
          <ul className="space-y-1">
            {p.sources.slice(0, 5).map((s) => (
              <li key={s.url} className="text-[11px] font-mono">
                {s.bright_data_product && (
                  <span className="text-[10px] px-1.5 py-0.5 border border-rogue-green/40 text-rogue-green rounded-sm uppercase tracking-wider mr-2">
                    {sourceBackendLabel(s.bright_data_product)}
                  </span>
                )}
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-rogue-green hover:underline truncate inline-block max-w-full sm:max-w-[380px] align-middle"
                  title={s.url}
                >
                  {s.url} ↗
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
