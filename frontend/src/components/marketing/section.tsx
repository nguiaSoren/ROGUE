import { cn } from "@/lib/utils"

interface SectionProps {
  /** Mono uppercase tracking eyebrow above the heading. */
  eyebrow?: string
  /** Section H2 heading. */
  title?: string
  /** Optional lede paragraph under the heading. */
  lede?: string
  children?: React.ReactNode
  className?: string
  id?: string
}

/**
 * Standard marketing section: eyebrow → h2 → lede → children, inside the
 * shared container. Server component. Renders the heading block only when
 * the corresponding prop is supplied.
 */
export function Section({ eyebrow, title, lede, children, className, id }: SectionProps) {
  const hasHeader = Boolean(eyebrow || title || lede)
  return (
    <section id={id} className={cn("max-w-7xl mx-auto px-6", className)}>
      {hasHeader && (
        <div className="max-w-3xl space-y-4">
          {eyebrow && (
            <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
              {eyebrow}
            </p>
          )}
          {title && (
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight">{title}</h2>
          )}
          {lede && (
            <p className="text-base text-muted-foreground leading-relaxed">{lede}</p>
          )}
        </div>
      )}
      {children && <div className={cn(hasHeader && "mt-10 md:mt-12")}>{children}</div>}
    </section>
  )
}

/** Form field label, mono uppercase, matches the eyebrow treatment but dimmer. */
export function FieldLabel({ className, children, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn(
        "block font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground",
        className
      )}
      {...props}
    >
      {children}
    </label>
  )
}
