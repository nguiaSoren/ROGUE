import { cn } from "@/lib/utils"

interface StatCardProps {
  /** Big mono headline value, e.g. "358" or "−41%". */
  value: string
  /** Short label under the value. */
  label: string
  /** Optional dimmer line of context. */
  sublabel?: string
  /** Accent color of the value. Defaults to rogue-green. */
  accent?: "green" | "red" | "foreground"
  className?: string
}

const accentClass: Record<NonNullable<StatCardProps["accent"]>, string> = {
  green: "text-rogue-green",
  red: "text-rogue-red",
  foreground: "text-foreground",
}

/** A single proof number in a rogue-card. Map PROOF_POINTS into these. */
export function StatCard({ value, label, sublabel, accent = "green", className }: StatCardProps) {
  return (
    <div
      className={cn(
        "rogue-card border border-border rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm",
        className
      )}
    >
      <div className={cn("font-mono text-4xl md:text-5xl font-bold tracking-tight", accentClass[accent])}>
        {value}
      </div>
      <div className="mt-3 text-base font-medium text-foreground">{label}</div>
      {sublabel && (
        <div className="mt-1 text-sm text-muted-foreground leading-relaxed">{sublabel}</div>
      )}
    </div>
  )
}
