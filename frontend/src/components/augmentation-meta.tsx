import type { ReactNode } from "react";
import { Term } from "@/components/glossary";

/**
 * Plain-data metadata for the 5 augmentations — canonical copy + accent colors.
 *
 * Deliberately NOT a "use client" module: both server components (the widgets
 * and the showcase) and client components (the lab) import these. If they lived
 * in a "use client" file, a server component importing them would receive a
 * client-reference placeholder instead of the real object — `.bandit` etc.
 * would read `undefined` at render.
 */
export type AugmentationKey =
  | "bandit"
  | "persona"
  | "escalation"
  | "mutation"
  | "stubbornness";

export const AUGMENTATION_COPY: Record<
  AugmentationKey,
  {
    eyebrow: ReactNode;
    shortSubhead: ReactNode;
    whatItIs: ReactNode;
    whyItMatters: ReactNode;
  }
> = {
  bandit: {
    eyebrow: (
      <>
        <Term name="ε-greedy">ε-greedy</Term>{" "}
        <Term name="bandit">bandit</Term>
      </>
    ),
    shortSubhead: (
      <>
        Self-tuning <Term name="SERP">SERP</Term> query selection · §11.6
      </>
    ),
    whatItIs:
      "An online learner that rates each jailbreak-hunting query by how many novel attacks per dollar it surfaces.",
    whyItMatters:
      "Stops you from wasting Bright Data budget on queries that no longer find anything new — the hot arm gets the next 90% of pulls automatically.",
  },
  persona: {
    eyebrow: "Persona susceptibility",
    shortSubhead: (
      <>
        <Term name="PAP">PAP</Term>-style persuasion wraps · §10.7
      </>
    ),
    whatItIs:
      'Each harvested attack is re-wrapped in a "helpful researcher," "compliance officer," or "logical appeal" persona and re-run.',
    whyItMatters: (
      <>
        A model that refuses &quot;how do I make X&quot; but obeys &quot;as a
        safety researcher, explain how X is made&quot; is a model that
        pattern-matches on tone, not intent. The{" "}
        <Term name="Δ">Δ</Term> tells you exactly which configs do this.
      </>
    ),
  },
  escalation: {
    eyebrow: "Multi-turn escalation",
    shortSubhead: (
      <>
        <Term name="Crescendo">Crescendo</Term>-style 3-turn arcs · §10.7
      </>
    ),
    whatItIs:
      "Single-turn attacks the model refused are re-synthesized as a 3-turn arc that warms up before delivering the payload.",
    whyItMatters:
      "If turn 3 breaches a config that refused turn 1, the model is making isolated decisions — context isn't carrying its guardrails. Real users do this naturally.",
  },
  mutation: {
    eyebrow: "Pattern-match audit",
    shortSubhead: (
      <>
        <Term name="AutoDAN">AutoDAN</Term>-reframed surface mutations ·
        §10.7
      </>
    ),
    whatItIs: (
      <>
        Each defended attack gets re-worded into a semantically identical{" "}
        <Term name="mutation">mutation</Term> and re-run against the configs
        that blocked the original.
      </>
    ),
    whyItMatters:
      "If a config defends the original wording but breaches on a paraphrase, the defense was string-matching, not reasoning. Pattern-match score = how brittle your defenses really are.",
  },
  stubbornness: {
    eyebrow: (
      <>
        <Term name="PAIR">PAIR</Term> · stubbornness
      </>
    ),
    shortSubhead: "Iterative attacker, avg iterations-to-breach · §10.7",
    whatItIs: (
      <>
        A second <Term name="LLM">LLM</Term> plays attacker, reading each
        refusal and refining the attack up to N iterations until breach or
        give-up.
      </>
    ),
    whyItMatters: (
      <>
        Tells you how long your weakest config holds against a real
        adaptive attacker. Most production safety evals measure single-shot
        refusal — this measures resilience.
      </>
    ),
  },
};

/**
 * Accent classes per augmentation. Imported wherever we want consistent
 * color identity across home + sidebar + showcase.
 */
export const AUGMENTATION_ACCENTS: Record<
  AugmentationKey,
  {
    border: string;
    text: string;
    raw: string;
    glow: string;
  }
> = {
  bandit: {
    border: "rogue-accent-bandit",
    text: "rogue-accent-bandit-text",
    raw: "#00ff88",
    glow: "rgba(0, 255, 136, 0.45)",
  },
  persona: {
    border: "rogue-accent-persona",
    text: "rogue-accent-persona-text",
    raw: "#a78bfa",
    glow: "rgba(167, 139, 250, 0.45)",
  },
  escalation: {
    border: "rogue-accent-escalation",
    text: "rogue-accent-escalation-text",
    raw: "#fbbf24",
    glow: "rgba(251, 191, 36, 0.45)",
  },
  mutation: {
    border: "rogue-accent-mutation",
    text: "rogue-accent-mutation-text",
    raw: "#22d3ee",
    glow: "rgba(34, 211, 238, 0.45)",
  },
  stubbornness: {
    border: "rogue-accent-stubbornness",
    text: "rogue-accent-stubbornness-text",
    raw: "#f87171",
    glow: "rgba(248, 113, 113, 0.45)",
  },
};
