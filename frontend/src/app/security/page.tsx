import { notFound } from "next/navigation";

export const metadata = {
  title: "Security, ROGUE",
  description:
    "How ROGUE keeps your data safe: encrypted secrets, organization isolation, no stored model weights, audit logging, and least-privilege access. ROGUE is the attacker side, it tests your endpoint over the API.",
};

/**
 * /security, a commercial-pitch surface (buyer-facing security posture). The
 * site is permanently non-commercial, so this route always 404s, rendered by
 * the shared not-found chrome.
 */
export default function SecurityPage() {
  notFound();
}
