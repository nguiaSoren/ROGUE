/**
 * Site feature flags — build-time, via NEXT_PUBLIC_* env vars set in Vercel.
 *
 * COMMERCIAL — when "true", the commercial layer is shown: the /pricing page is
 * reachable and pricing links/CTAs appear (the full startup / investor pitch).
 * When unset or anything other than "true" (the DEFAULT), the site runs in its
 * honest hiring mode: /pricing returns 404 and the commercial CTAs route to
 * /early-access instead.
 *
 * The operator alone controls this: Vercel → Project → Settings → Environment
 * Variables → set NEXT_PUBLIC_SHOW_COMMERCIAL=true, then redeploy. It is a
 * single GLOBAL value — every visitor sees the same toggled state; it is not
 * per-visitor and visitors cannot change it. Flipping it requires a redeploy
 * because NEXT_PUBLIC_* vars are baked into the build.
 */
export const COMMERCIAL = process.env.NEXT_PUBLIC_SHOW_COMMERCIAL === "true";
