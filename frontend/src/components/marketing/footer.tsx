import Link from "next/link";

import { NewsletterSignup } from "@/components/marketing/newsletter-signup";

/**
 * Global marketing footer. Server component, hosts the (client) newsletter
 * signup but is otherwise non-interactive.
 *
 * Matches the ROGUE dark terminal house style: mono eyebrows, rogue-green
 * wordmark, subtle bordered columns over the deep blue-black background.
 */

type FooterLink = { label: string; href: string; external?: boolean };

const PRODUCT: FooterLink[] = [
  { label: "Overview", href: "/" },
  { label: "Live feed", href: "/feed" },
  { label: "Breach matrix", href: "/matrix" },
  { label: "Threat brief", href: "/brief" },
];

const COMPANY: FooterLink[] = [
  { label: "About", href: "/about" },
];

const DEVELOPERS: FooterLink[] = [
  { label: "Resources", href: "/resources" },
  { label: "Sample report", href: "/sample-report.html", external: true },
];

export function Footer() {
  return (
    <footer className="mt-auto border-t border-border bg-background/80">
      <div className="max-w-7xl mx-auto px-6 py-14">
        <div className="grid gap-10 md:grid-cols-12">
          {/* Brand + tagline + primary CTA */}
          <div className="md:col-span-4">
            <Link
              href="/"
              className="inline-flex items-center gap-2 font-mono text-sm font-bold tracking-tight group"
            >
              <span className="inline-block w-2 h-2 rounded-full bg-rogue-green animate-rogue-pulse-green" />
              <span className="text-rogue-green group-hover:rogue-glitch">
                ROGUE
              </span>
            </Link>
            <p className="mt-4 max-w-xs text-sm text-muted-foreground leading-relaxed">
              Independent assurance for high-stakes AI agents — model, oversight, and memory, measured and signed.
            </p>
            <Link
              href="/try"
              className="mt-6 inline-flex items-center rounded-md bg-rogue-green px-4 py-2 font-mono text-xs font-semibold uppercase tracking-[0.18em] text-[#050508] transition-opacity hover:opacity-90"
            >
              Try the demo
            </Link>
          </div>

          {/* Link columns + newsletter */}
          <div className="md:col-span-8 grid grid-cols-2 gap-8 sm:grid-cols-4">
            <FooterColumn title="Product" links={PRODUCT} />
            <FooterColumn title="Company" links={COMPANY} />
            <FooterColumn title="Developers" links={DEVELOPERS} />
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <NewsletterSignup variant="footer" />
            </div>
          </div>
        </div>

        {/* Bottom row */}
        <div className="mt-12 flex flex-col gap-3 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
            © ROGUE
          </p>
          <p className="font-mono text-[11px] tracking-[0.12em] text-muted-foreground/70">
            Built on Bright Data
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({
  title,
  links,
}: {
  title: string;
  links: FooterLink[];
}) {
  return (
    <div>
      <h3 className="font-mono text-[11px] uppercase tracking-[0.22em] text-rogue-green">
        {title}
      </h3>
      <ul className="mt-4 space-y-2.5">
        {links.map((link) => (
          <li key={link.label}>
            {link.external ? (
              <a
                href={link.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {link.label}
              </a>
            ) : (
              <Link
                href={link.href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {link.label}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
