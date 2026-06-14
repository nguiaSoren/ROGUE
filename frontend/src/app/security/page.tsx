import { notFound } from "next/navigation";

export const metadata = {
  title: "Security · ROGUE",
  description: "Security posture — coming soon.",
};

/**
 * /security, a commercial-pitch surface (buyer-facing security posture). The
 * site is permanently non-commercial, so this route always 404s, rendered by
 * the shared not-found chrome.
 */
export default function SecurityPage() {
  notFound();
}
