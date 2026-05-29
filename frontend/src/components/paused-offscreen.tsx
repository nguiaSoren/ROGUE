"use client";

import { createElement, type CSSProperties, type ReactNode } from "react";
import { usePausedOnOffscreen } from "@/lib/use-paused-on-offscreen";

/**
 * Thin client wrapper that renders any element with `data-rg-pause` toggled
 * by an IntersectionObserver. Use when the animated element is inside an
 * otherwise-server component — wrap just the animated element so the parent
 * stays server-rendered.
 *
 * The matching CSS rule in `globals.css`:
 *
 *   [data-rg-pause="true"], [data-rg-pause="true"] * {
 *     animation-play-state: paused !important;
 *   }
 *
 * means any animation on this element or descendants pauses when offscreen.
 */
export function PausedOffscreen({
  tag = "div",
  className,
  style,
  children,
  rootMargin,
}: {
  tag?: keyof React.JSX.IntrinsicElements;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
  rootMargin?: string;
}) {
  const { ref, paused } = usePausedOnOffscreen<HTMLElement>(rootMargin);
  return createElement(
    tag,
    {
      ref,
      className,
      style,
      "data-rg-pause": paused ? "true" : undefined,
    },
    children,
  );
}
