"use client";

import { useEffect, useRef, useState } from "react";

/**
 * IntersectionObserver-backed pause flag for offscreen elements.
 *
 * Spread the returned `ref` onto the element you want to observe, then
 * spread `data-rg-pause={paused || undefined}` onto whichever element
 * owns the running CSS animation (often the same one). The matching
 * global CSS rule in `globals.css` toggles `animation-play-state: paused`.
 *
 * `rootMargin: "200px"` so the resume happens slightly before the
 * element is fully back in view — no perceptible "snap" on scroll-up.
 */
export function usePausedOnOffscreen<T extends HTMLElement>(
  rootMargin: string = "200px",
) {
  const ref = useRef<T | null>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const obs = new IntersectionObserver(
      ([entry]) => setPaused(!entry.isIntersecting),
      { rootMargin },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [rootMargin]);

  return { ref, paused } as const;
}
