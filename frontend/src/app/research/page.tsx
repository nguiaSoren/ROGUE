import Link from "next/link";
import {
  Scale,
  ListOrdered,
  Microscope,
  Ruler,
  ArrowRight,
  TriangleAlert,
  Download,
} from "lucide-react";
import { Section } from "@/components/marketing/section";
import {
  JudgeAgreementFig,
  SchedulingFig,
  FalsePositiveModesFig,
  BreachRejudgeFig,
  NullResultForestFig,
  MethodNote,
} from "@/components/research-figures";

export const metadata = {
  title: "Research, ROGUE",
  description:
    "The methods and measured results behind ROGUE, a solo research build of a continuous open-web LLM red-team. Judge calibration against human-labeled benchmarks, scheduling as a capability lever, a publication-grade null result, and measure-before-build discipline. Including the negative results.",
};

/**
 * /research, the research-forward surface. Ungated (no COMMERCIAL gate): a
 * scholarly, scannable account of the methods and the measured results,
 * including the negative ones. No demo/pricing/pilot CTAs by design, the only
 * outbound links are to the live-evidence routes (/matrix, /analytics, /feed).
 * All numbers are verbatim from the operator's brief; do not invent figures.
 * Server component, matching the /about dark "rogue" aesthetic.
 */
export default function ResearchPage() {
  return (
    <main className="flex-1 bg-rogue-grid bg-rogue-spotlight">
      <div className="space-y-20 md:space-y-28 py-16 md:py-24">
        {/* HERO ---------------------------------------------------------- */}
        <Section
          eyebrow="research"
          title="The methods, and the measured results."
          lede="A solo research build, the methods and the measured results, including the negative ones."
        >
          <a
            href="/rogue-research-brief.pdf"
            className="inline-flex items-center gap-2 rounded-lg border border-rogue-green/50 px-4 py-2 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green transition-colors hover:bg-rogue-green/10"
          >
            <Download className="h-4 w-4" aria-hidden />
            Download the research brief (PDF)
          </a>
        </Section>

        {/* 1. JUDGE CALIBRATION ----------------------------------------- */}
        <Section
          eyebrow="finding 01"
          title="Calibrating an LLM-as-judge against human labels, then recalibrating when a benchmark exposed it."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <Scale
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-base text-muted-foreground leading-relaxed">
                Every breach verdict is an LLM judgment, so the judge is the
                load-bearing weakness. It was validated four ways, three
                against independent human-annotated benchmarks: blind stratified
                in-distribution hand-labels, WildGuardTest (Allen AI
                annotators), StrongREJECT, and JailbreakBench&rsquo;s{" "}
                <code className="font-mono text-[13px] text-foreground/90">
                  judge_comparison
                </code>{" "}
                (300 human-labeled rows against four field classifiers).
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              JBB exposed over-flagging. The v1 judge agreed with the human
              majority only{" "}
              <span className="text-foreground font-medium">
                70.3%, last of five
              </span>{" "}
              (behind HarmBench / LlamaGuard-2 / GPT-4 / Llama-3), at recall 98%
              / precision 55%. A 20-row false-positive audit diagnosed{" "}
              <span className="text-foreground font-medium">
                five recurring failure modes
              </span>
              ; the root cause was a <em>rubric</em> problem, it rewarded{" "}
              <span className="text-foreground font-medium">
                engagement with the attack frame
              </span>{" "}
              (persona acceptance, acknowledgment, format mimicry) over{" "}
              <span className="text-foreground font-medium">
                transfer of harmful content
              </span>
              .
            </p>

            <p className="text-base text-muted-foreground leading-relaxed">
              The fix, a{" "}
              <span className="text-foreground font-medium">
                content-transfer-gate rubric (v3)
              </span>{" "}
, moved the same 300 rows to{" "}
              <span className="text-foreground font-medium">
                89.3% agreement / 79.5% precision / 95.5% recall
              </span>{" "}
              (+19 / +24.5 / −2.5 pp), dead-last → 3rd of five, tied with the
              frontier classifiers, via a cost-controlled tiered evaluation
              (~$8.4).
            </p>

            <div className="animate-rogue-fade-up">
              <JudgeAgreementFig />
            </div>

            <div className="animate-rogue-fade-up">
              <FalsePositiveModesFig />
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              Then the honest part: re-judging the stored breach matrix under v3{" "}
              <span className="text-foreground font-medium">
                dropped breach cells 2,429 → 1,371 (−43.6%)
              </span>
              , correcting prior over-reporting. All three external axes were
              re-measured under v3 (WildGuard harm 88.5%, StrongREJECT inflation
              −26%).
            </p>

            <div className="animate-rogue-fade-up">
              <BreachRejudgeFig />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <Metric value="70.3 → 89.3%" label="JBB agreement" accent="green" />
              <Metric value="55 → 79.5%" label="precision" accent="green" />
              <Metric value="−43.6%" label="breach cells re-judged" accent="red" />
              <Metric value="2.56%" label="in-dist false-positive" accent="green" />
            </div>

            <MethodNote>
              Method, 300 frozen JBB rows, human-majority ground truth, 4 field
              classifiers as baselines; v3 is a rubric change (content-transfer
              gate), same rows re-scored; tiered eval (n=25 pilot → full).
            </MethodNote>

            <NovelNote>
              A named FP taxonomy for a safety judge, plus a{" "}
              <span className="text-rogue-green">⚑</span> finding that two
              respected benchmarks (WildGuardTest harm labels, StrongREJECT)
              themselves <span className="text-foreground/90">over-count</span>{" "}
              relative to a strict content-transfer standard.
            </NovelNote>

            <div className="pt-5 mt-2 border-t border-border/60 space-y-5">
              <p className="text-base text-muted-foreground leading-relaxed">
                <span className="text-foreground font-medium">
                  The gate isn&apos;t harm-specific, it&apos;s a methodology.
                </span>{" "}
                The same consummation gate (
                <span className="text-foreground/90">
                  engagement is not breach; consummation is breach
                </span>
                ), re-instantiated per breach type, now calibrates{" "}
                <span className="text-foreground/90">four</span> structurally
                different policies: <em>harm</em> (capability transfer),{" "}
                <em>information-disclosure</em> (content, &ldquo;did the
                protected datum appear?&rdquo;), <em>unauthorized-action</em>{" "}
                (action, &ldquo;did the agent execute?&rdquo;), and{" "}
                <em>fabricated-sensitive-value</em> (a fabrication and trust
                breach distinct from disclosure, &ldquo;did the model invent a
                value it presents as real?&rdquo;). The harness{" "}
                <span className="text-foreground font-medium">
                  self-diagnoses
                </span>
                : it returned REFINE on the action type, a targeted rubric fix
                was applied, and re-measurement shipped it. The deeper result is
                that the{" "}
                <span className="text-foreground font-medium">
                  tool-trace upgrade turned a stated limitation into a measured
                  resolution
                </span>
                . The action type&apos;s earlier weakness (κ 0.746 plus a
                residual false-positive mode) was an artifact of the text-only
                proxy, not the gate: once a tool-call trace makes
                &ldquo;executed&rdquo; a fact rather than a prose inference, the
                simulate-versus-claim confusion that tripped both judge and human
                dissolves.
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <Metric value="91.0%" label="harm · top-of-field" accent="green" />
                <Metric value="97.35%" label="info-disclosure v2" accent="green" />
                <Metric value="98.89%" label="unauth · tool-trace" accent="green" />
                <Metric value="100%" label="fabricated · new type" accent="green" />
              </div>

              <NovelNote>
                The contribution isn&apos;t &ldquo;a better harm judge&rdquo; but a{" "}
                <span className="text-rogue-green">⚑</span>{" "}
                <span className="text-foreground/90">
                  repeatable methodology for calibrating breach judges across
                  four breach classes
                </span>{" "}
                from one gate template: harm (91.0%, top-of-field, above Llama-3
                90.7% and GPT-4 90.3%), information-disclosure (v2: 97.35%
                agreement, 100% recall, 0% false-positive mode), unauthorized-action
                (v3 tool-trace: 98.89%, 100% recall, false-positive mode driven
                9.38 to 6.25 to 3.12%), and the new fabricated-sensitive-value
                type (100%, 0% false-positive mode, first pass). The harness
                exposes type-dependent failure modes, then resolves them by
                upgrading the evidence, not the rubric. That pattern generalizes:
                provenance-dependent breach types need an evidence trace, and the
                independence check names the missing evidence. Shown twice, on
                unauthorized-action (a tool-call trace lifted second-labeler κ
                from 0.746 to 0.917) and on fabricated-value (a retrieval trace
                lifted κ from 0.723 to 0.909).
              </NovelNote>

              <MethodNote>
                Method: per-type designed-label corpora with independent
                second-labeler κ checks (information-disclosure κ 0.80 base /
                0.786 boundary, unauthorized-action κ 0.746 pre-trace then 0.917
                with the tool-trace; harm uses JailbreakBench human-majority
                agreement, not a κ); single-operator calibration and synthetic
                designed-label corpora throughout. The fabricated-value
                retrieval-trace lifts its human κ from 0.723 to 0.909 (the judge
                ships 96.88%); in calibration the traces are
                embedded in the graded text, the production seam being the scan
                engine&apos;s Capture. Descriptive measurements, not validated
                generalizations.
              </MethodNote>
            </div>
          </div>
        </Section>

        {/* 2. SCHEDULING AS A CAPABILITY LEVER -------------------------- */}
        <Section
          eyebrow="finding 02"
          title="Scheduling as a capability lever, not just an optimization."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <ListOrdered
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-base text-muted-foreground leading-relaxed">
                A within-tier greedy reorder was replaced with a{" "}
                <span className="text-foreground font-medium">
                  target-conditioned cross-tier scheduler
                </span>{" "}
, a static, explainable blend (
                <code className="font-mono text-[13px] text-foreground/90">
                  0.5·global + 0.3·vendor + 0.2·family
                </code>{" "}
                breach-rate, Laplace-smoothed, deliberately no ML / no bandit so
                it stays reproducible).
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              A single-variable controlled experiment, same ladder, attacks,
              corpus, judge, and target (Claude Haiku, AdvBench + JailbreakBench);
              only the order changed, beat the production baseline on every
              axis:{" "}
              <span className="text-foreground font-medium">
                median winner-rank 22 → 11 to 13.5
              </span>
              ,{" "}
              <span className="text-foreground font-medium">
                attack-success-rate 50% → 60%
              </span>
              , and{" "}
              <span className="text-foreground font-medium">
                cost-per-success $1.25 → $0.74 (−41%)
              </span>
              .
            </p>

            <div className="animate-rogue-fade-up">
              <SchedulingFig />
            </div>

            <div className="grid grid-cols-3 gap-3 pt-1">
              <Metric value="22 → 11 to 13.5" label="median winner-rank" accent="green" />
              <Metric value="50 → 60%" label="attack-success-rate" accent="green" />
              <Metric value="−41%" label="cost-per-success" accent="green" />
            </div>

            <MethodNote>
              Method, single-variable controlled experiment: only the ladder
              order changed (ladder, attacks, corpus, judge, target fixed);
              Claude Haiku; AdvBench + JailbreakBench; primary metric =
              winner-rank.
            </MethodNote>

            <NovelNote>
              The mechanism: rank↓ <em>caused</em> ASR↑, the old order
              exhausted the per-scan budget cap before reaching the winning
              technique, so reordering improved coverage, cost, and latency at
              once with zero new attacks. The reproducibility invariant is{" "}
              <span className="text-foreground/90">
                &ldquo;reorder, never exclude&rdquo;
              </span>
              : same ladder, different order, full reachability preserved.
            </NovelNote>
          </div>
        </Section>

        {/* 3. NULL RESULT ----------------------------------------------- */}
        <Section
          eyebrow="finding 03"
          title="A publication-grade null result: grammar-component predictive power."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <Microscope
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-base text-muted-foreground leading-relaxed">
                Before building a grammar/AST attack-composition engine, a{" "}
                <span className="text-foreground font-medium">
                  $0 observational study over 1,540 (primitive × target) cells
                </span>{" "}
                tested whether grammar-structure nodes predict breach{" "}
                <em>beyond</em>{" "}attack-family membership, with full confound
                controls: Benjamini-Hochberg FDR across hundreds of node/pair
                tests, Mantel-Haenszel stratification by target model,
                within-family lift, and Cramér&rsquo;s-V collinearity flagging.
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              Verdict <span className="text-foreground font-medium">weak/none</span>{" "}
, the family label carries the predictive weight. Cross-family
              structural nodes show ~1.0 to 1.1× non-significant lift, and the
              striking pre-FDR pairwise synergies (odds ratios up to 16.8)
              survived <span className="text-foreground font-medium">none</span>{" "}
              of the four controls.
            </p>

            <div className="animate-rogue-fade-up">
              <NullResultForestFig />
            </div>

            <div className="grid grid-cols-3 gap-3 pt-1">
              <Metric value="1,540" label="cells, $0 study" accent="green" />
              <Metric value="~1.0 to 1.1×" label="cross-family lift (n.s.)" accent="red" />
              <Metric value="0 / 4" label="synergies surviving controls" accent="red" />
            </div>

            <MethodNote>
              Method, $0 observational study over 1,540 (primitive × target)
              cells; controls: BH-FDR, Mantel-Haenszel by target, within-family
              lift, Cramér&rsquo;s-V collinearity.
            </MethodNote>

            <NovelNote>
              A cheap, rigorous falsification that{" "}
              <span className="text-foreground/90">
                redirected engineering away from a months-long build
              </span>{" "}
, a successful negative result.
            </NovelNote>
          </div>
        </Section>

        {/* 4. MEASURE-BEFORE-BUILD -------------------------------------- */}
        <Section
          eyebrow="finding 04"
          title="Measure-before-build discipline."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <Ruler
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-base text-muted-foreground leading-relaxed">
                $0 measurements from existing telemetry were used repeatedly to{" "}
                <em>invert</em> &ldquo;build it&rdquo; decisions, each parked
                with an explicit trigger-to-revisit.
              </p>
            </div>

            <ul className="space-y-3">
              <InvertedDecision title="Per-model ladder routing">
                The spread was a model{" "}
                <span className="text-foreground/90">main effect</span>, not a
                family×model interaction → not worth the rewrite.
              </InvertedDecision>
              <InvertedDecision title="LLM renderer-synthesis">
                Synthesis-grade backlog flat at{" "}
                <span className="text-foreground/90">7</span> across two widening
                harvests → parked.
              </InvertedDecision>
              <InvertedDecision title="HF jailbreak-dataset bulk-import">
                Measured <span className="text-foreground/90">0 new attack families</span>{" "}
                → declined.
              </InvertedDecision>
            </ul>

            <MethodNote>
              Method, each decision gated on a $0 telemetry measurement with a
              pre-stated trigger-to-revisit.
            </MethodNote>
          </div>
        </Section>

        {/* LIVE EVIDENCE ------------------------------------------------ */}
        <Section
          eyebrow="see the live evidence"
          title="The system is running. These are its live surfaces."
        >
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <EvidenceLink
              href="/matrix"
              path="/matrix"
              title="Breach Matrix"
              desc="The breach heatmap, with 95% bootstrap CIs on every cell."
            />
            <EvidenceLink
              href="/analytics"
              path="/analytics"
              title="Analytics"
              desc="Live telemetry from the running red-team."
            />
            <EvidenceLink
              href="/feed"
              path="/feed"
              title="Live Feed"
              desc="Newest harvested attacks and their breach trails."
            />
          </div>
        </Section>

        {/* LIMITATIONS -------------------------------------------------- */}
        <Section eyebrow="limitations">
          <div className="rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm max-w-3xl flex gap-4">
            <TriangleAlert
              className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
              strokeWidth={1.75}
              aria-hidden
            />
            <div className="space-y-3">
              <p className="text-base text-muted-foreground leading-relaxed">
                These are honest constraints, not caveats buried in a footnote.
                Targets are black-box live-API models whose versions are not
                pinned; some cells are small-n (95% bootstrap CIs are persisted
                precisely because of this); the judge is single-operator-calibrated.
              </p>
              <p className="text-base text-foreground/90 leading-relaxed">
                These are descriptive measurements of a live system, not
                validated generalizations.
              </p>
            </div>
          </div>
        </Section>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------

/** A single headline number in the rogue-card style. */
function Metric({
  value,
  label,
  accent,
}: {
  value: string;
  label: string;
  accent: "green" | "red";
}) {
  return (
    <div className="rogue-card border border-border rounded-xl p-4 bg-card/40 backdrop-blur-sm">
      <p
        className={`text-xl md:text-2xl font-bold tracking-tight tabular-nums ${
          accent === "red" ? "text-rogue-red" : "text-rogue-green"
        }`}
      >
        {value}
      </p>
      <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground leading-snug">
        {label}
      </p>
    </div>
  );
}

/** The "why this is novel/notable" one-liner under each finding. */
function NovelNote({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-l-2 border-rogue-green/50 pl-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        why this is notable
      </p>
      <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed">
        {children}
      </p>
    </div>
  );
}

function InvertedDecision({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="rogue-card border border-border rounded-xl p-4 md:p-5 bg-card/40 backdrop-blur-sm">
      <p className="text-base font-semibold text-foreground">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
        {children}
      </p>
    </li>
  );
}

function EvidenceLink({
  href,
  path,
  title,
  desc,
}: {
  href: string;
  path: string;
  title: string;
  desc: string;
}) {
  return (
    <Link
      href={href}
      className="rogue-card border border-border rounded-xl p-5 bg-card/40 backdrop-blur-sm block group"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-rogue-green">
        {path}
      </p>
      <p className="text-lg font-bold mt-1 group-hover:text-rogue-green transition-colors flex items-center gap-1.5">
        {title}
        <ArrowRight
          className="h-4 w-4 opacity-0 -translate-x-1 transition-all group-hover:opacity-100 group-hover:translate-x-0"
          aria-hidden
        />
      </p>
      <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
        {desc}
      </p>
    </Link>
  );
}
