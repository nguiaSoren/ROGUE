import Link from "next/link"
import { cn } from "@/lib/utils"

interface CtaRowProps {
  className?: string
}

/**
 * The standard pair of marketing CTAs. Secondary is always "See a sample
 * report". The primary is "Read the research" (→ /research) so the salesiest
 * CTA isn't shown to an academic visitor. Both rendered as Next.js Links.
 */
export function CtaRow({ className }: CtaRowProps) {
  return (
    <div className={cn("flex flex-col sm:flex-row gap-3 md:gap-4", className)}>
      <Link
        href="/research"
        className={cn(
          "inline-flex items-center justify-center rounded-lg px-6 py-3",
          "bg-rogue-green text-black font-mono text-sm font-bold tracking-[0.15em] uppercase",
          "transition-opacity hover:opacity-90",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        Read the research
      </Link>
      <Link
        href="/sample-report.html"
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "inline-flex items-center justify-center rounded-lg px-6 py-3 border border-border",
          "font-mono text-sm font-bold tracking-[0.15em] uppercase text-foreground",
          "transition-colors hover:border-rogue-green hover:text-rogue-green",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        )}
      >
        See a sample report
      </Link>
    </div>
  )
}
