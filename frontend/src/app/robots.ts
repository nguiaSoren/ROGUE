import type { MetadataRoute } from "next";

// Reuse the same base URL declared as `metadataBase` in src/app/layout.tsx.
const BASE_URL = "https://rogue-eosin.vercel.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Authed application area + auth entry — keep out of the index.
      disallow: ["/scans", "/sign-in"],
    },
    sitemap: `${BASE_URL}/sitemap.xml`,
    host: BASE_URL,
  };
}
