import { cn } from "@/lib/utils"

export function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(
        "flex h-10 w-full rounded-lg border border-border bg-transparent px-3 py-2 font-sans text-base text-foreground transition-colors outline-none appearance-none",
        "focus:border-ring focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/30",
        // native option list should read on the dark surface
        "[&>option]:bg-card [&>option]:text-foreground",
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
}
