import type { Metadata, Viewport } from "next";
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
  metadataBase: new URL("https://rogue-eosin.vercel.app"),
  title: "ROGUE · AI-Agent Assurance — model, oversight & memory, signed",
  description:
    "ROGUE measures every place a high-stakes AI agent can fail — whether the model can be broken, whether human oversight is meaningful, and whether its accumulated knowledge stays safe — against an independent standard, reproducible and signed.",
  openGraph: {
    title: "ROGUE · AI-Agent Assurance — model, oversight & memory, signed",
    description:
      "Three signed measurements of a high-stakes AI agent: can the model be broken, is human oversight meaningful (false-approve rate), is its accumulated knowledge safe (skill-pool leakage). Independent, reproducible, signed.",
    url: "/",
    siteName: "ROGUE",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ROGUE · AI-Agent Assurance — model, oversight & memory, signed",
    description:
      "Three signed measurements of a high-stakes AI agent: can the model be broken, is human oversight meaningful (false-approve rate), is its accumulated knowledge safe (skill-pool leakage). Independent, reproducible, signed.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
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
