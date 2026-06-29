import Link from "next/link";
import {
  Scale,
  ListOrdered,
  Microscope,
  Ruler,
  ShieldCheck,
  ArrowRight,
  TriangleAlert,
  Download,
  Gavel,
} from "lucide-react";
import { Section } from "@/components/marketing/section";
import { OVERSIGHT } from "@/lib/proof";
import {
  JudgeAgreementFig,
  SchedulingFig,
  FalsePositiveModesFig,
  BreachRejudgeFig,
  NullResultForestFig,
  ReproductionFunnelFig,
  MethodNote,
} from "@/components/research-figures";

export const metadata = {
  title: "Research, ROGUE",
  description:
    "The methods and measured results behind ROGUE, a solo research build of a continuous open-web LLM red-team. Judge calibration against human-labeled benchmarks, scheduling as a capability lever, a publication-grade null result, measure-before-build discipline, measured remediation, and a grey-literature reproducibility audit (claimed jailbreak success doesn't predict what reproduces). Including the negative results.",
};

/**
 * /research, the research-forward surface. Ungated: a
 * scholarly, scannable account of the methods and the measured results,
 * including the negative ones. No sales CTAs by design, the only
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
          lede="A solo research build, the methods and the measured results, including the negative ones. Eight findings across three surfaces — the model can be broken, the human gate can rubber-stamp, shared knowledge can leak — each measured against an independent standard, signed."
        >
          <a
            href="/rogue-research-brief.pdf"
            className="inline-flex items-center gap-2 rounded-lg border border-rogue-green/50 px-4 py-2 font-mono text-xs uppercase tracking-[0.15em] text-rogue-green transition-colors hover:bg-rogue-green/10"
          >
            <Download className="h-4 w-4" aria-hidden />
            Download the research brief (PDF)
          </a>
        </Section>

        {/* PAPERS ------------------------------------------------------- */}
        <Section eyebrow="papers" title="Written up, and openly archived.">
          <p className="-mt-2 mb-5 max-w-3xl text-[15px] text-muted-foreground leading-relaxed">
            The findings below are written up as solo-authored papers, each
            openly archived as a citable Zenodo preprint. Three are under peer
            review at <span className="text-foreground/90">TMLR</span>; two are
            headed to <span className="text-foreground/90">NDSS</span> (submission
            planned August&nbsp;2026). Full manuscripts on request.
          </p>
          <div className="space-y-3 max-w-3xl">
            <PaperLink
              title="Open-Web Jailbreaks Mostly Don't Reproduce in Deployment: A Provenance-Stratified Audit Against a Patch-Immune Anchor"
              venue="NDSS · planned Aug 2026"
              finding="finding 01"
              doi="10.5281/zenodo.21016390"
            />
            <PaperLink
              title="Allocation Is a Capability-Growth Mechanism: Telemetry and Scheduling in a Self-Growing LLM Red-Team"
              venue="Preprint"
              finding="finding 02"
              doi="10.5281/zenodo.21016849"
            />
            <PaperLink
              title="Calibrating LLM-as-Judge Breach Detectors: A Per-Type Consummation Gate and an Independence Discipline for Operator-Labeled Ground Truth"
              venue="Under review · TMLR 2026"
              finding="finding 03"
              doi="10.5281/zenodo.21016697"
            />
            <PaperLink
              title="A Dead Call Cannot Leak: Liveness-Guarded Measurement of Canary Leakage from Shared Agent Skill Pools"
              venue="NDSS · planned Aug 2026"
              finding="finding 06"
              doi="10.5281/zenodo.21016278"
            />
            <PaperLink
              title="Measuring Verifier Leakage for LLM Judges: Strict Breach Rates Are a Lower Bound on Payment Errors"
              venue="Under review · TMLR 2026"
              doi="10.5281/zenodo.21017684"
            />
            <PaperLink
              title="When Does Agent Shape Matter, Per Instance? A Calibrated, Abstaining Study of Coordination-Architecture Selection"
              venue="Under review · TMLR 2026"
              doi="10.5281/zenodo.21030368"
            />
          </div>
        </Section>

        {/* AT A GLANCE -------------------------------------------------- */}
        <Section eyebrow="at a glance" title="Eight findings, in about a minute.">
          <p className="-mt-2 mb-5 max-w-3xl text-[15px] text-muted-foreground leading-relaxed">
            The findings group under three surfaces — the{" "}
            <span className="text-foreground/90">model can be broken</span>, the{" "}
            <span className="text-foreground/90">human gate can rubber-stamp</span>,
            and <span className="text-foreground/90">shared knowledge can leak</span>{" "}
            — each measured against an independent standard and signed, plus a
            verified-remediation loop that refuses any fix it can&rsquo;t prove.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <GlanceCard
              href="#finding-01"
              eyebrow="01 · reproduction"
              headline="100% → 13%"
              desc="A source's claimed success rate doesn't predict what reproduces against your deployment (ρ ≈ −0.07). ROGUE re-measures every technique."
              accent="red"
            />
            <GlanceCard
              href="#finding-02"
              eyebrow="02 · scheduling"
              headline="ASR 50 → 60%"
              desc="Cross-tier scheduling as a capability lever: rank down caused ASR up, at −41% cost."
            />
            <GlanceCard
              href="#finding-03"
              eyebrow="03 · judge"
              headline="70.3 → 89.3%"
              desc="Calibrated an LLM-judge to human labels, then generalized it across four breach types."
            />
            <GlanceCard
              href="#finding-04"
              eyebrow="04 · null result"
              headline="0 of 4 survive"
              desc="Grammar structure does not predict breach beyond attack family. A clean negative result."
              accent="red"
            />
            <GlanceCard
              href="#finding-05"
              eyebrow="05 · remediation"
              headline="0% → 20%"
              desc="The calibrated over-block judge caught an over-block that a marker heuristic scored 0%, flipping a would-be accept into a correct refusal."
              accent="red"
            />
            <GlanceCard
              href="#finding-06"
              eyebrow="06 · skill pools"
              headline="audit before sharing"
              desc="Shared agent-skill pools are an unaudited surface — leakage, useless skills, and dangerous combinations. ROGUE measures and signs each pool before it ships."
              accent="red"
            />
            <GlanceCard
              href="#finding-07"
              eyebrow="07 · discipline"
              headline="measure first"
              desc="$0 telemetry measurements inverted three build decisions before any code was written."
            />
            <GlanceCard
              href="#finding-08"
              eyebrow="08 · human gate"
              headline={`${OVERSIGHT.falseApproveRate}% waved through`}
              desc={`When a human approves a risky AI action, is that oversight meaningful? Measured against an independent answer key, a reviewer waved through ${OVERSIGHT.falseApproveRate}% of actions that should have been denied (CI [${OVERSIGHT.ciLow},${OVERSIGHT.ciHigh}], n=${OVERSIGHT.reviewers}) — the rubber-stamping failure mode regulators rely on, measured. Signed.`}
              accent="red"
            />
          </div>
        </Section>

        {/* 1. REPRODUCIBILITY (LEAD) ------------------------------------ */}
        <Section
          id="finding-01"
          eyebrow="finding 01"
          title="Claimed potency doesn't predict what reproduces against your deployment."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <Scale
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
                Of 17 harvested techniques whose source claimed{" "}
                <span className="text-foreground font-medium">~100% success</span>,
                only <span className="text-foreground font-medium">6</span>{" "}
                reproduce at all, and their mean measured breach rate is{" "}
                <span className="text-foreground font-medium">13%</span>. Across the
                56 techniques that publish a number, claimed success and measured
                reproduction are{" "}
                <span className="text-foreground font-medium">
                  uncorrelated (Spearman −0.07, 95% CI [−0.34, +0.19])
                </span>
                {" "}— a claimed rate is not portable signal, which is why ROGUE
                re-measures every technique against your model and system prompt,
                not the source&rsquo;s.
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              The same pattern shows up as a reproduction funnel. Across 301
              techniques harvested from 15 open-web sources and reproduced on a
              five-model panel, the &ldquo;works on at least one of five
              models&rdquo; rate{" "}
              <span className="text-foreground font-medium">(40%)</span> is
              inflated by the weakest target: on a{" "}
              <span className="text-foreground font-medium">
                frozen open-weight model only ~9% reproduce
              </span>
              , and{" "}
              <span className="text-foreground font-medium">
                ~4% on the most robust model
              </span>
              . Paper-sourced techniques degrade more slowly than
              grey-literature ones, a directional gap that widens on the harder
              targets.
            </p>

            <div className="animate-rogue-fade-up">
              <ReproductionFunnelFig />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <Metric value="−0.07" label="claimed vs measured (ρ, n=56)" accent="red" />
              <Metric value="100% → 13%" label="claimed ~100%, mean measured" accent="red" />
              <Metric value="~9%" label="reproduce on a frozen model" accent="red" />
              <Metric value="$0" label="on already-collected data" accent="green" />
            </div>

            <MethodNote>
              Method, 301 baseline techniques × a five-model panel,{" "}
              <span className="text-foreground/90">10,244 trials already collected</span>;
              breach = the calibrated v3 judge (tuned to under-count) at
              any_breach_rate ≥ 0.4; reproduction is measured as whether the
              technique still produces a consummated breach against a current model,
              toward whatever objective it natively carries (a mixed corpus,
              predominantly harmful); the panel is anchored by a frozen open-weight
              model so non-reproduction isn&rsquo;t confounded by silent vendor patching.
              A stronger-model re-extraction (Sonnet 4.6, Batch API) of all 148
              candidate sources confirmed the null is not an extraction
              artifact, it recovered a claimed rate for only 1 of 94
              unquantified sources, so the small claimed-rate sample reflects
              that the open web rarely quantifies these claims, not a weak
              extractor.
            </MethodNote>

            <NovelNote>
              The honest version of &ldquo;we test real attacks&rdquo;: a success
              rate claimed in a paper or a forum is{" "}
              <span className="text-foreground/90">
                not portable to your deployment
              </span>
              {" "}(measured ρ ≈ 0). The value is the re-measurement against your
              model, system prompt, and tools, under a judge calibrated to
              under-count. Honest caveats, &ldquo;reproduction&rdquo; means the
              technique still defeats alignment toward its native objective (a mixed
              corpus, predominantly harmful, the audit elicited harmful content against
              our own API accounts and releases none); the paper-vs-forum gap is
              directional (borderline-significant); temperature was checked and is
              not a confound (the funnel holds across temperature subsets); and the
              claimed rates carry ~17% extraction noise, so −0.07 reads as &ldquo;no
              predictive signal,&rdquo; not a precise estimate.{" "}
              <span className="text-rogue-green">⚑</span>
            </NovelNote>
          </div>
        </Section>

        {/* 2 + 3 SIDE BY SIDE ---------------------------------------- */}
        <Section>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8">
            <FindingCard
              id="finding-02"
              eyebrow="finding 02"
              title="Scheduling as a capability lever, not just an optimization."
            >
            <div className="flex gap-4">
              <ListOrdered
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
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

            <p className="text-[17px] text-foreground leading-relaxed">
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
            </FindingCard>
            <FindingCard
              id="finding-03"
              eyebrow="finding 03"
              title="Calibrating an LLM-as-judge against human labels, then recalibrating when a benchmark exposed it."
            >
            <div className="flex gap-4">
              <Scale
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
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

            <p className="text-[17px] text-foreground leading-relaxed">
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

            <p className="text-[17px] text-foreground leading-relaxed">
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

            <p className="text-[17px] text-foreground leading-relaxed">
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
              <p className="text-[17px] text-foreground leading-relaxed">
                <span className="text-foreground font-medium">
                  The gate isn&apos;t harm-specific, it&apos;s a calibration
                  discipline, an established practice taken rigorously, not a new
                  method.
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
                <Metric value="89.3%" label="harm · 3rd of 5" accent="green" />
                <Metric value="97.35%" label="info-disclosure v2" accent="green" />
                <Metric value="98.89%" label="unauth · tool-trace" accent="green" />
                <Metric value="100%" label="fabricated · new type" accent="green" />
              </div>

              <NovelNote>
                The contribution isn&apos;t &ldquo;a better harm judge&rdquo; but a{" "}
                <span className="text-foreground/90">
                  repeatable discipline for calibrating breach judges across
                  four breach classes
                </span>{" "}
                from one gate template: harm (89.3%, 3rd of 5 — tied with the
                frontier baselines Llama-3 90.7% and GPT-4 90.3%),
                information-disclosure (v2: 97.35%
                agreement, 100% recall, 0% false-positive mode), unauthorized-action
                (v3 tool-trace: 98.89%, 100% recall, false-positive mode driven
                9.38 to 6.25 to 3.12%), and the new fabricated-sensitive-value
                type (100%, 0% false-positive mode, first pass). The harness
                exposes type-dependent failure modes, then resolves them by
                upgrading the evidence, not the rubric.{" "}
                <span className="text-rogue-green">⚑</span> Then the discipline
                turned on its own headline. A single second labeler suggested a
                trace-modality ceiling — supplying the captured trace appeared to
                lift inter-rater κ (unauthorized-action 0.746→0.917,
                fabricated-value 0.723→0.909; Δκ +0.171). An independent{" "}
                <span className="text-foreground/90">
                  6-labeler panel did not replicate it
                </span>{" "}
                (raw Δκ +0.011, divergences in both directions). The cross-class
                calibration holds; the trace-modality boost does not — and we
                report that null on our own result, not the post-hoc subset it
                could be tuned to (all 45 panel divergences released for
                case-by-case adjudication). The building blocks here are
                established (trace-grounded agent evaluation, κ-gated calibration,
                cross-type judge generalization such as CompliBench); the
                contribution is the rigor, an independence-invariant discipline, a
                self-diagnosing harness, and a null reported on its own headline,
                not a new mechanism.
              </NovelNote>

              <MethodNote>
                Method: per-type designed-label corpora with independent
                second-labeler κ checks (information-disclosure κ 0.80 base /
                0.786 boundary; unauthorized-action κ 0.746, with a single second
                labeler reading 0.917 under the tool-trace; harm uses
                JailbreakBench human-majority agreement, not a κ). The
                single-labeler trace-modality lift (Δκ +0.171) did not survive an
                independent 6-labeler panel (raw Δκ +0.011), reported as a
                disclosed null; the fabricated-value retrieval-trace single-labeler
                reading is 0.723→0.909 (the judge ships 96.88%). Single-operator
                calibration and synthetic designed-label corpora throughout.
                Descriptive measurements, not validated generalizations.
              </MethodNote>
            </div>
            </FindingCard>
          </div>
        </Section>

        {/* 4 + 5 SIDE BY SIDE ---------------------------------------- */}
        <Section>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8">
            <FindingCard
              id="finding-04"
              eyebrow="finding 04"
              title="A publication-grade null result: grammar-component predictive power."
            >
            <div className="flex gap-4">
              <Microscope
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
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

            <p className="text-[17px] text-foreground leading-relaxed">
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
            </FindingCard>

            <FindingCard
              id="finding-05"
              eyebrow="finding 05"
              title="Measured remediation: prove a fix closes the breach without over-blocking, or refuse to ship it."
            >
              <div className="flex gap-4">
                <ShieldCheck
                  className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                  strokeWidth={1.75}
                  aria-hidden
                />
                <p className="text-[17px] text-foreground leading-relaxed">
                  Finding a breach is half the job. ROGUE also{" "}
                  <span className="text-foreground font-medium">
                    generates a candidate fix
                  </span>
                  , then <em>measures</em>, by re-scanning a mutated test config
                  with the same calibrated judge, whether it closes the breach{" "}
                  <span className="text-foreground font-medium">
                    without over-blocking
                  </span>{" "}
                  legitimate traffic, and{" "}
                  <span className="text-foreground font-medium">refuses</span> any
                  it can&rsquo;t prove. It generates and verifies; the client
                  deploys; it never sits in the request path.
                </p>
              </div>

              <p className="text-[17px] text-foreground leading-relaxed">
                Across live runs it{" "}
                <span className="text-foreground font-medium">
                  refused every offline patch
                </span>
                , each for a distinct measured reason. A medical/financial-directive
                patch{" "}
                <span className="text-foreground font-medium">
                  didn&rsquo;t reduce the breach
                </span>{" "}
                (<span className="text-foreground font-medium">20.8% → ~25%</span>).
                A system-prompt-extraction patch{" "}
                <span className="text-foreground font-medium">
                  over-blocked legitimate traffic
                </span>
                , the calibrated over-block judge flagged{" "}
                <span className="text-foreground font-medium">~20%</span> where a
                marker heuristic had scored{" "}
                <span className="text-foreground font-medium">0%</span>, so the loop
                refused it and recommended an architecture change rather than ship a
                fix that doesn&rsquo;t measurably work.
              </p>

              <p className="text-[17px] text-foreground leading-relaxed">
                The &ldquo;without over-blocking&rdquo; check is itself{" "}
                <span className="text-foreground font-medium">calibrated</span>, and
                it earned its keep: an over-block judge scored against a 50-case
                independent set reaches{" "}
                <span className="text-foreground font-medium">
                  98% agreement, 100% precision, 0% over-flag
                </span>{" "}
                (vs an 88% marker heuristic), and it{" "}
                <span className="text-foreground font-medium">
                  caught the over-block the heuristic missed
                </span>
                .
              </p>

              <div className="grid grid-cols-2 gap-3 pt-1">
                <Metric value="0% → ~20%" label="RD04 over-block: heuristic → judge" accent="red" />
                <Metric value="20.8 → ~25%" label="RA06 patch: no reduction" accent="red" />
                <Metric value="98% / 0%" label="over-block judge: agree / over-flag" accent="green" />
                <Metric value="88 → 98%" label="over-block detector calibrated" accent="green" />
              </div>

              <MethodNote>
                Method, the calibrated per-rule judge scores breach rate pre/post on
                a re-scan of a mutated test config; over-block on an independent
                legitimate-traffic set via the calibrated over-block judge; a
                candidate is accepted only on a CI-confident reduction with
                over-block near 0, else architecture. Across the live runs no
                offline patch met both bars on these demo models.
              </MethodNote>

              <NovelNote>
                The contribution isn&rsquo;t a new mitigation, it&rsquo;s that a fix
                is{" "}
                <span className="text-foreground/90">
                  accepted only when a re-scan proves it closes the breach without
                  over-blocking
                </span>
                , and refused otherwise, and the calibrated judge is what makes
                &ldquo;doesn&rsquo;t over-block&rdquo; trustworthy: it flipped a
                would-be accept (heuristic 0% over-block) into a correct refusal
                (judge ~20%). A runtime guardrail asserts it blocks; this{" "}
                <em>measures</em> it, and says no when a patch doesn&rsquo;t hold or
                over-blocks. <span className="text-rogue-green">⚑</span>
              </NovelNote>
            </FindingCard>
          </div>
        </Section>

        {/* 6 + 7 SIDE BY SIDE ---------------------------------------- */}
        <Section>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8">
            <FindingCard
              id="finding-06"
              eyebrow="finding 06"
              title="Shared skill pools are an assurance surface, not a free upgrade."
            >
            <div className="flex gap-4">
              <ShieldCheck
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
                Agents increasingly accumulate and{" "}
                <span className="text-foreground font-medium">
                  share skills and memory
                </span>{" "}
                across a fleet. Pooling them is an unaudited surface: a skill
                distilled from private work can leak it, a popular skill can
                quietly make the agent worse, two benign skills can combine into
                something harmful. ROGUE treats a pool as a red-team target, it
                measures each risk and emits a{" "}
                <span className="text-foreground font-medium">
                  signed, tamper-evident attestation
                </span>{" "}
                for the pool before it ships.
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              A first measurement. Against a{" "}
              <span className="text-foreground font-medium">
                deliberately weak agent
              </span>{" "}
              (Llama-3.1-8B) holding a planted secret, a standard extraction pack
              recovered it on{" "}
              <span className="text-foreground font-medium">17 of 20</span> skills,
              with{" "}
              <span className="text-foreground font-medium">
                zero false positives
              </span>{" "}
              on the 12 controls, despite an explicit &ldquo;never reveal&rdquo;
              instruction, instruction-following is not containment. And of four
              candidate skills with enough held-out tasks to measure, only{" "}
              <span className="text-foreground font-medium">one</span> earned
              promotion under a verified-net-effect gate; the rest were neutral or
              worse. Accumulated skills are not free upgrades.
            </p>

            <p className="text-base text-muted-foreground leading-relaxed">
              A 22-model census (23 runs across two providers) makes the surprise
              precise: leakage doesn&rsquo;t fall with size or capability, it
              tracks{" "}
              <span className="text-foreground font-medium">alignment</span>.
              Within a family, scale doesn&rsquo;t contain it — Qwen2.5-instruct
              rises 0.5B 45% → 32B 100%, and Llama-3.x-instruct is flat (8B ≈ 70B).
              What moves leakage is alignment: a safety-tuned gemma-2-9b leaks 65%
              where its instruct sibling leaks 100%, and stripping the refusal
              direction from identical Llama-3.1-8B weights (abliteration) raises
              leakage 83% → 97%. The reasoning trace is a distinct leak surface —
              gpt-oss returns 0% in its answer but{" "}
              <span className="text-foreground font-medium">
                87% once the reasoning channel is counted
              </span>{" "}
              (DeepSeek-R1-70B mirrors it). A skill-pool leakage audit
              can&rsquo;t be waved off by pointing at how big or capable the model
              is.
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <Metric value="45 → 100%" label="qwen2.5 · 0.5B → 32B (scale ≠ safety)" accent="red" />
              <Metric value="83 → 97%" label="llama-8b · instruct → abliterated" accent="red" />
              <Metric value="65%" label="gemma-2-9b · safety-tuned (vs 100% instruct)" accent="green" />
              <Metric value="0 → 87%" label="gpt-oss · answer → reasoning channel" accent="red" />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <Metric value="17 / 20" label="canary leak · weak target" accent="red" />
              <Metric value="0 / 12" label="control false positives" accent="green" />
              <Metric value="1 of 4" label="skills earn promotion" accent="red" />
              <Metric value="signed" label="tamper-evident attestation" accent="green" />
            </div>

            <MethodNote>
              Method, the pool is 55 real harvested agent-skills + 20 planted
              canaries (single trust domain). Leakage is{" "}
              <span className="text-foreground/90">
                marker-based exact recovery
              </span>{" "}
              (deterministic ground truth, not a judge estimate); the target is a
              deliberately weak open model, the pack is standard (4 templates),
              n = 20. The 22-model alignment census is a separate sweep (23 runs,
              2 providers, 3-run t-intervals on the alignment arms); rates are
              per-model exact-marker recovery, never pooled across providers (a
              15-pt serving-stack gap on the same Llama-8B). Verified-promotion
              runs each skill with vs without injection
              over a held-out set, graded by a net-effect judge calibrated to human
              labels (100% agreement on a 20-case set built to be hard, ship gate);
              a skill promotes only if its repair-fraction CI clears 0.5.
            </MethodNote>

            <NovelNote>
              The under-discussed part is the{" "}
              <span className="text-foreground/90">surface</span>, not the number.
              That a weak model leaks a secret it was told to hold is expected, it
              is the known extraction / prompt-injection mechanism; the contribution
              is treating{" "}
              <span className="text-foreground/90">
                shared skill and memory pools
              </span>{" "}
              as something to audit before sharing, leakage, verified promotion,
              dangerous combinations, signed, rather than &ldquo;faster coding.&rdquo;
              Honest caveats, this is a first measurement on a{" "}
              <span className="text-foreground/90">weak</span> target with a small n
              and a standard pack, so 85% is illustrative of the surface, not a
              hardened &ldquo;agent pools leak 85%&rdquo; claim; the
              verified-promotion sample is n = 4 (one promotion rests on a single
              decisive case); single trust domain, cross-team isolation is roadmap.{" "}
              <span className="text-rogue-green">⚑</span>
            </NovelNote>
            </FindingCard>

            <FindingCard
              id="finding-07"
              eyebrow="finding 07"
              title="Measure-before-build discipline."
            >
              <div className="flex gap-4">
                <Ruler
                  className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                  strokeWidth={1.75}
                  aria-hidden
                />
                <p className="text-[17px] text-foreground leading-relaxed">
                  $0 measurements from existing telemetry were used repeatedly to{" "}
                  <em>invert</em> &ldquo;build it&rdquo; decisions, each parked
                  with an explicit trigger-to-revisit.
                </p>
              </div>

              <ul className="space-y-3">
                <li className="text-[15px] text-foreground/85 leading-relaxed">
                  <span className="font-semibold text-foreground">
                    Per-model ladder routing
                  </span>{" "}
                  — the spread was a model{" "}
                  <span className="text-foreground/90">main effect</span>, not a
                  family×model interaction, so not worth the rewrite.
                </li>
                <li className="text-[15px] text-foreground/85 leading-relaxed">
                  <span className="font-semibold text-foreground">
                    LLM renderer-synthesis
                  </span>{" "}
                  — synthesis-grade backlog flat at{" "}
                  <span className="text-foreground/90">7</span> across two
                  widening harvests, so parked.
                </li>
                <li className="text-[15px] text-foreground/85 leading-relaxed">
                  <span className="font-semibold text-foreground">
                    HF jailbreak-dataset bulk-import
                  </span>{" "}
                  — measured{" "}
                  <span className="text-foreground/90">
                    0 new attack families
                  </span>
                  , so declined.
                </li>
              </ul>

              <MethodNote>
                Method, each decision gated on a $0 telemetry measurement with a
                pre-stated trigger-to-revisit.
              </MethodNote>
            </FindingCard>
          </div>
        </Section>

        {/* 8. HUMAN GATE ------------------------------------------------ */}
        <Section
          id="finding-08"
          eyebrow="finding 08"
          title="When a human approves a risky AI action, is that oversight meaningful? Measured."
        >
          <div className="max-w-3xl space-y-6">
            <div className="flex gap-4">
              <Gavel
                className="h-6 w-6 text-rogue-green shrink-0 mt-0.5"
                strokeWidth={1.75}
                aria-hidden
              />
              <p className="text-[17px] text-foreground leading-relaxed">
                &ldquo;A human is in the loop&rdquo; is the control regulators and
                safety cases lean on hardest, and it is almost never measured.
                ROGUE measures it: against an{" "}
                <span className="text-foreground font-medium">
                  independent answer key
                </span>{" "}
                — a ground truth provably independent of what the reviewer sees —
                a reviewer{" "}
                <span className="text-foreground font-medium">
                  waved through {OVERSIGHT.falseApproveRate}% of actions that
                  should have been denied
                </span>{" "}
                (95% CI [{OVERSIGHT.ciLow}%, {OVERSIGHT.ciHigh}%]). The
                rubber-stamping failure mode the oversight story relies on,
                quantified — and{" "}
                <span className="text-foreground font-medium">signed</span> with a
                reproducible attestation.
              </p>
            </div>

            <p className="text-base text-muted-foreground leading-relaxed">
              The honest scope: this is{" "}
              <span className="text-foreground font-medium">
                n = {OVERSIGHT.reviewers} reviewer
              </span>{" "}
              — a directional measurement of a single human gate, not a
              population estimate of how all reviewers behave. The contribution
              isn&rsquo;t the rate itself but the apparatus around it: a{" "}
              <span className="text-foreground/90">false-approve rate</span> is a
              measurable property of an oversight gate, scored against a key the
              reviewer cannot game, and the result carries a tamper-evident
              signature like every other ROGUE surface. The number is a
              first reading; the method generalizes to more reviewers.
            </p>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
              <Metric
                value={`${OVERSIGHT.falseApproveRate}%`}
                label="false-approve rate (vs answer key)"
                accent="red"
              />
              <Metric
                value={`[${OVERSIGHT.ciLow}, ${OVERSIGHT.ciHigh}]`}
                label="95% CI"
                accent="red"
              />
              <Metric
                value={`n=${OVERSIGHT.reviewers}`}
                label="reviewer (directional)"
                accent="red"
              />
              <Metric value="signed" label="reproducible attestation" accent="green" />
            </div>

            <MethodNote>
              Method, a single reviewer adjudicates a corpus of risky agent
              actions; each verdict is scored against an answer key constructed
              to be independent of the cues the reviewer sees, so an approval of
              a should-deny action is an unambiguous false-approve; rate and 95%
              CI are computed over that key, and the result is signed
              (tamper-evident attestation). n = {OVERSIGHT.reviewers} —
              directional, not a population.
            </MethodNote>

            <NovelNote>
              The under-measured part is the{" "}
              <span className="text-foreground/90">gate itself</span>. &ldquo;A
              human approves it&rdquo; is treated as a guarantee; here it is a{" "}
              <span className="text-foreground/90">measurable surface</span> with
              a false-approve rate against an independent key — the same
              independence discipline as the breach judge, turned on the human.
              Honest caveat: a single reviewer (n = {OVERSIGHT.reviewers}) makes
              this directional, not a claim about reviewers in general; the value
              is the apparatus, a signed false-approve measurement of an
              oversight gate. <span className="text-rogue-green">⚑</span>
            </NovelNote>
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
              <p className="text-[17px] text-foreground leading-relaxed">
                These are honest constraints, not caveats buried in a footnote.
                Targets are black-box live-API models whose versions are not
                pinned; some cells are small-n (95% bootstrap CIs are persisted
                precisely because of this); the judge is single-operator-calibrated.
              </p>
              <p className="text-[17px] text-foreground leading-relaxed">
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
      <p className="mt-1.5 text-[15px] text-foreground/85 leading-relaxed">
        {children}
      </p>
    </div>
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

/** A compact at-a-glance card that links to a full finding below. */
function GlanceCard({
  href,
  eyebrow,
  headline,
  desc,
  accent = "green",
}: {
  href: string;
  eyebrow: string;
  headline: string;
  desc: string;
  accent?: "green" | "red";
}) {
  return (
    <a
      href={href}
      className="rogue-card border border-border rounded-xl p-4 md:p-5 bg-card/40 backdrop-blur-sm block group hover:border-rogue-green/50 transition-colors"
    >
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-rogue-green">
        {eyebrow}
      </p>
      <p
        className={`mt-2 text-lg md:text-xl font-bold tracking-tight tabular-nums ${
          accent === "red" ? "text-rogue-red" : "text-foreground"
        }`}
      >
        {headline}
      </p>
      <p className="mt-1 text-[13px] text-foreground/80 leading-snug">{desc}</p>
    </a>
  );
}

/** A finding rendered as a bordered card (for the side-by-side grid). */
function FindingCard({
  id,
  eyebrow,
  title,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      id={id}
      className="rogue-card border border-border rounded-2xl p-6 md:p-7 bg-card/30 backdrop-blur-sm scroll-mt-24"
    >
      <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
        {eyebrow}
      </p>
      <h2 className="mt-3 text-2xl font-bold tracking-tight">{title}</h2>
      <div className="mt-6 space-y-5">{children}</div>
    </div>
  );
}

/** A single paper row linking out to its Zenodo DOI. */
function PaperLink({
  title,
  venue,
  finding,
  doi,
}: {
  title: string;
  venue: string;
  finding?: string;
  doi: string;
}) {
  return (
    <a
      href={`https://doi.org/${doi}`}
      target="_blank"
      rel="noopener noreferrer"
      className="rogue-card border border-border rounded-xl p-4 bg-card/40 backdrop-blur-sm block group hover:border-rogue-green/50 transition-colors"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-rogue-green">
          {venue}
        </span>
        {finding ? (
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            · {finding}
          </span>
        ) : null}
      </div>
      <p className="mt-1.5 text-[15px] font-medium text-foreground leading-snug group-hover:text-rogue-green transition-colors">
        {title}
      </p>
      <p className="mt-1 font-mono text-[11px] text-muted-foreground">
        Zenodo · {doi}
      </p>
    </a>
  );
}
