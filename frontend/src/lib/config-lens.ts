/**
 * Shared helper for the `?config=<config_id>` deployment lens.
 *
 * Returns the validated config_id when:
 *   1. the `config` search-param is present and non-empty, AND
 *   2. it matches at least one entry in the provided configs list.
 *
 * Returns `null` when absent, empty, or unknown — callers fall through to the
 * global (unfiltered) view rather than erroring.
 */
export function resolveConfigLens(
  rawParam: string | string[] | undefined,
  configs: { config_id: string }[],
): string | null {
  const id = Array.isArray(rawParam) ? rawParam[0] : rawParam;
  if (!id) return null;
  const matched = configs.some((c) => c.config_id === id);
  return matched ? id : null;
}
