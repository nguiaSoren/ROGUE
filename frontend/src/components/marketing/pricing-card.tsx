import Link from "next/link"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

interface PricingCardProps {
  /** Tier name, e.g. "Team". */
  name: string
  /** One-line positioning blurb. */
  blurb?: string
  /** Price label, e.g. "$0", "$499", "Custom". */
  price: string
  /** Period suffix, e.g. "/mo". Omitted for custom tiers. */
  period?: string
  /** Bullet features, rendered with Check icons. */
  features: string[]
  ctaLabel: string
  ctaHref: string
  /** Highlighted "Most popular" tier. */
  featured?: boolean
  className?: string
}

export function PricingCard({
  name,
  blurb,
  price,
  period,
  features,
  ctaLabel,
  ctaHref,
  featured = false,
  className,
}: PricingCardProps) {
  return (
    <div
      className={cn(
        "rogue-card relative flex flex-col rounded-xl p-5 md:p-6 bg-card/40 backdrop-blur-sm",
        featured
          ? "border-2 border-rogue-green shadow-[0_0_0_1px_var(--rogue-green-dim)]"
          : "border border-border",
        className
      )}
    >
      {featured && (
        <span className="absolute -top-3 left-6 rounded-full bg-rogue-green px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-black">
          Most popular
        </span>
      )}

      <div className="space-y-1">
        <h3 className="text-xl font-bold tracking-tight">{name}</h3>
        {blurb && <p className="text-sm text-muted-foreground leading-relaxed">{blurb}</p>}
      </div>

      <div className="mt-5 flex items-baseline gap-1">
        <span className="font-mono text-4xl font-bold tracking-tight text-foreground">{price}</span>
        {period && <span className="text-sm text-muted-foreground">{period}</span>}
      </div>

      <ul className="mt-6 space-y-3">
        {features.map((feature) => (
          <li key={feature} className="flex items-start gap-2.5 text-sm text-muted-foreground">
            <Check className="mt-0.5 size-4 shrink-0 text-rogue-green" aria-hidden="true" />
            <span className="leading-relaxed">{feature}</span>
          </li>
        ))}
      </ul>

      <Link
        href={ctaHref}
        className={cn(
          "mt-8 inline-flex items-center justify-center rounded-lg px-6 py-3",
          "font-mono text-sm font-bold tracking-[0.15em] uppercase",
          "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rogue-green/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          featured
            ? "bg-rogue-green text-black hover:opacity-90"
            : "border border-border text-foreground hover:border-rogue-green hover:text-rogue-green"
        )}
      >
        {ctaLabel}
      </Link>
    </div>
  )
}
