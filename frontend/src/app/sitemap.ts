import type { MetadataRoute } from "next";

// Reuse the same base URL declared as `metadataBase` in src/app/layout.tsx.
const BASE_URL = "https://rogue-eosin.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  // Public marketing routes only — the authed (app)/ pages and /sign-in are
  // intentionally excluded (see robots.ts).
  const staticRoutes: Array<{
    path: string;
    changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"];
    priority: number;
  }> = [
    { path: "/", changeFrequency: "daily", priority: 1 },
    { path: "/product", changeFrequency: "weekly", priority: 0.9 },
    { path: "/research", changeFrequency: "weekly", priority: 0.8 },
    { path: "/resources", changeFrequency: "weekly", priority: 0.7 },
    { path: "/about", changeFrequency: "monthly", priority: 0.6 },
    { path: "/try", changeFrequency: "monthly", priority: 0.7 },
    { path: "/deck", changeFrequency: "monthly", priority: 0.6 },
    { path: "/feed", changeFrequency: "daily", priority: 0.6 },
    { path: "/matrix", changeFrequency: "daily", priority: 0.6 },
    { path: "/brief", changeFrequency: "daily", priority: 0.6 },
    { path: "/analytics", changeFrequency: "daily", priority: 0.6 },
  ];

  const staticEntries: MetadataRoute.Sitemap = staticRoutes.map((route) => ({
    url: `${BASE_URL}${route.path}`,
    lastModified,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));

  return staticEntries;
}
