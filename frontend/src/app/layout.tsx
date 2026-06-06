import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Analytics } from "@vercel/analytics/next";
import { ThemeProvider } from "@/components/theme-provider";
import { Nav } from "@/components/nav";
import { Footer } from "@/components/marketing/footer";
import { SseFeedProvider } from "@/components/sse-feed-provider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ROGUE · Open-web LLM Threat Intelligence",
  description:
    "Continuous red-team for production LLM deployments. Harvests new jailbreaks from the open web, reproduces them against your deployment configuration, ships a daily diff of which attacks now bypass your guardrails.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased dark`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
        >
          <SseFeedProvider>
            <Nav />
            {children}
            <Footer />
          </SseFeedProvider>
        </ThemeProvider>
        <Analytics />
      </body>
    </html>
  );
}
