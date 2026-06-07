import { describe, expect, it } from "vitest";
import { plainifyPP, plainifyRate } from "@/lib/plain-numbers";

/**
 * Unit tests for the plain-English number translators used across the breach
 * dashboard. These are pure functions (rate/delta in → human phrase out), so
 * they're tested at their threshold boundaries — the only place the mapping can
 * silently regress.
 */
describe("plainifyRate", () => {
  it("maps breach rates to the correct human-fraction band at each boundary", () => {
    expect(plainifyRate(0)).toBe("nothing has breached yet");
    expect(plainifyRate(0.05)).toBe("a few breaches per 100 attempts");
    expect(plainifyRate(0.1)).toBe("1 in 10 attacks breaches");
    expect(plainifyRate(0.2)).toBe("1 in 5 attacks breaches");
    expect(plainifyRate(0.3)).toBe("1 in 3 attacks breaches");
    expect(plainifyRate(0.45)).toBe("about half of attacks breach");
    expect(plainifyRate(0.65)).toBe("2 out of 3 attacks breach");
    expect(plainifyRate(0.8)).toBe("4 out of 5 attacks breach");
    expect(plainifyRate(0.95)).toBe("almost every attack breaches");
    expect(plainifyRate(1)).toBe("almost every attack breaches");
  });
});

describe("plainifyPP", () => {
  it("treats sub-0.5pp moves as no change", () => {
    expect(plainifyPP(0)).toBe("no measurable change");
    expect(plainifyPP(0.004)).toBe("no measurable change");
  });

  it("without a baseline, describes the directional point delta", () => {
    expect(plainifyPP(0.15)).toBe(
      "15 percentage points more attacks breaching",
    );
    expect(plainifyPP(-0.15)).toBe(
      "15 percentage points fewer attacks breaching",
    );
    expect(plainifyPP(0.01)).toBe("1 percentage point more attacks breaching");
  });

  it("with a baseline, renders the before→after jump and clamps to [0,100]", () => {
    expect(plainifyPP(0.15, 0.31)).toBe("31% → 46%, a 15-point jump");
    expect(plainifyPP(-0.15, 0.31)).toBe("31% → 16%, a 15-point drop");
    // after-value clamps at 100 rather than overflowing
    expect(plainifyPP(0.5, 0.9)).toBe("90% → 100%, a 50-point jump");
  });
});
