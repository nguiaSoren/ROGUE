"use client";

import { useEffect, useState } from "react";

/**
 * Client-side count-up animation. Tickers from 0 to `value` over `duration`.
 *
 * Uses an ease-out curve so the number snaps in fast then slows, feels
 * "alive" instead of linear/mechanical. Pure setTimeout loop; no library.
 *
 * Use for the hero KPI numbers + any place where a static integer benefits
 * from a brief animated entrance.
 */
export function CountUp({
  value,
  duration = 1400,
  className,
}: {
  value: number | string;
  duration?: number;
  className?: string;
}) {
  const targetNum = typeof value === "number" ? value : NaN;
  const isNumeric = Number.isFinite(targetNum);
  const [display, setDisplay] = useState<number>(0);

  useEffect(() => {
    if (!isNumeric) return;
    let start: number | null = null;
    let frame = 0;
    const tick = (ts: number) => {
      if (start === null) start = ts;
      const t = Math.min(1, (ts - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setDisplay(Math.round(targetNum * eased));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [targetNum, duration, isNumeric]);

  return <span className={className}>{isNumeric ? display : value}</span>;
}
