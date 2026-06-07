import { cn } from "@/lib/utils";

/**
 * Map a model id ("anthropic/claude-haiku-4-5") or a config display name
 * ("Acme · GPT-5.4 Nano") to one of the bundled provider logo slugs in
 * /public/logos/. Tries the provider prefix first (robust), then falls back
 * to recognizable substrings in a free-text name.
 */
const PREFIX_TO_SLUG: Record<string, string> = {
  anthropic: "anthropic",
  openai: "openai",
  "meta-llama": "meta",
  meta: "meta",
  mistralai: "mistralai",
  mistral: "mistralai",
  google: "googlegemini",
  "google-vertex": "googlegemini",
};

const NAME_HINTS: [RegExp, string][] = [
  [/claude|anthropic/i, "anthropic"],
  [/gpt|openai|o[134]\b/i, "openai"],
  [/gemini|google/i, "googlegemini"],
  [/llama|meta/i, "meta"],
  [/mistral|mixtral/i, "mistralai"],
];

const SLUG_TO_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  meta: "Meta",
  mistralai: "Mistral AI",
  googlegemini: "Google",
};

export function providerSlug(modelOrName: string | null | undefined): string | null {
  if (!modelOrName) return null;
  const prefix = modelOrName.split("/")[0]?.trim().toLowerCase();
  if (prefix && PREFIX_TO_SLUG[prefix]) return PREFIX_TO_SLUG[prefix];
  for (const [re, slug] of NAME_HINTS) if (re.test(modelOrName)) return slug;
  return null;
}

/**
 * Tiny monochrome provider logo. Rendered via CSS mask so it inherits the
 * current text color (`currentColor`), works on any theme regardless of each
 * SVG's baked-in fill. Sized to 1em by default so it scales with the text.
 */
export function ProviderLogo({
  model,
  className,
  title,
}: {
  model: string | null | undefined;
  className?: string;
  title?: string;
}) {
  const slug = providerSlug(model);
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
