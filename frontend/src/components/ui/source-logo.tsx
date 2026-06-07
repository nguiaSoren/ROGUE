import { cn } from "@/lib/utils";

/**
 * Map an open-web source label ("Reddit · r/ChatGPTJailbreak",
 * "GitHub · L1B3RT4S", "X · @elder_plinius", "HF · …", "leak mirrors")
 * to one of the bundled platform logo slugs in /public/logos/. Mirrors
 * ui/provider-logo.tsx, same monochrome CSS-mask render so every place a
 * source is named can show its platform icon the way LLM rows show provider
 * icons.
 *
 * Tries the leading platform token first (robust against the "· detail"
 * suffix), then falls back to recognizable substrings anywhere in the label.
 */
const PREFIX_TO_SLUG: Record<string, string> = {
  reddit: "reddit",
  x: "x",
  twitter: "x",
  github: "github",
  huggingface: "huggingface",
  hf: "huggingface",
  arxiv: "arxiv",
  promptfoo: "discord",
  discord: "discord",
};

const NAME_HINTS: [RegExp, string][] = [
  [/reddit|r\//i, "reddit"],
  [/github/i, "github"],
  [/hugging\s?face|\bhf\b/i, "huggingface"],
  [/arxiv/i, "arxiv"],
  [/discord|promptfoo/i, "discord"],
  // X last, single-letter token is easy to over-match, so keep it specific.
  [/\bx\b|twitter|@/i, "x"],
];

const SLUG_TO_LABEL: Record<string, string> = {
  reddit: "Reddit",
  x: "X",
  github: "GitHub",
  huggingface: "Hugging Face",
  arxiv: "arXiv",
  discord: "Discord",
};

export function sourceSlug(label: string | null | undefined): string | null {
  if (!label) return null;
  // Leading platform token, before any "·", "/", or whitespace separator.
  const prefix = label.split(/[·/\s]/)[0]?.trim().toLowerCase();
  if (prefix && PREFIX_TO_SLUG[prefix]) return PREFIX_TO_SLUG[prefix];
  for (const [re, slug] of NAME_HINTS) if (re.test(label)) return slug;
  return null;
}

/**
 * Tiny monochrome platform logo for an open-web source. Rendered via CSS mask
 * so it inherits the current text color (`currentColor`), works on any theme
 * regardless of each SVG's baked-in fill. Sized to 1em by default so it scales
 * with the text. Returns null for sources with no recognizable platform
 * (e.g. "jailbreakchat", "LeakHub mirrors") so callers can keep their existing
 * dot/marker for those.
 */
export function SourceLogo({
  source,
  className,
  title,
}: {
  source: string | null | undefined;
  className?: string;
  title?: string;
}) {
  const slug = sourceSlug(source);
  if (!slug) return null;
  const label = title ?? SLUG_TO_LABEL[slug] ?? slug;
  const url = `/logos/${slug}.svg`;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn("inline-block shrink-0 align-[-0.125em]", className)}
      style={{
        width: "1em",
        height: "1em",
        backgroundColor: "currentColor",
        WebkitMaskImage: `url(${url})`,
        maskImage: `url(${url})`,
        WebkitMaskRepeat: "no-repeat",
        maskRepeat: "no-repeat",
        WebkitMaskSize: "contain",
        maskSize: "contain",
        WebkitMaskPosition: "center",
        maskPosition: "center",
      }}
    />
  );
}
