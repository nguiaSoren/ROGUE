import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/sign-out-button";
import { getApiKey, keyHint } from "@/lib/session";

/**
 * Authenticated product shell. The "session" is the customer's API key in an httpOnly cookie; if it's
 * absent we bounce to /sign-in. Adds a product sub-nav (under the marketing nav from the root layout).
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const key = await getApiKey();
  if (!key) {
    redirect("/sign-in");
  }
  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b border-border/60 bg-card/30">
        <div className="mx-auto flex min-h-12 w-full max-w-6xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-sm sm:gap-6 sm:py-0">
          <span className="font-semibold">Dashboard</span>
          <Link href="/scans" className="text-muted-foreground transition-colors hover:text-foreground">
            Scans
          </Link>
          <Link href="/scans/new" className="text-muted-foreground transition-colors hover:text-foreground">
            New scan
          </Link>
          <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
            <span className="hidden max-w-[40vw] truncate font-mono sm:inline" title="your API key (prefix)">{keyHint(key)}</span>
            <SignOutButton />
          </div>
        </div>
      </div>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
