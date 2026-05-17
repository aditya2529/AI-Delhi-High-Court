import type { Metadata } from "next";
import "./globals.css";
import { PrivateAlphaBanner } from "@/components/layout/PrivateAlphaBanner";

export const metadata: Metadata = {
  title: "Delhi HC Case Tracker",
  description:
    "Workflow-simplification wrapper over the public Delhi High Court case-status search. NOT a court-operated site.",
  /*
   * GREEN-ZONE rail: keep this app out of search indexes while we are in
   * private alpha. Next.js App Router propagates `metadata` to every page,
   * so this single declaration emits `<meta name="robots" content="noindex,
   * nofollow">` on every route — including nested layouts and dynamic pages.
   *
   * Pair this with `frontend/public/robots.txt` (Disallow: /) for crawlers
   * that do not parse meta tags. Remove both ONLY when Phase-0 gates close
   * and counsel signs off on public launch.
   */
  robots: {
    index: false,
    follow: false,
    googleBot: {
      index: false,
      follow: false,
    },
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <PrivateAlphaBanner />
        <header className="dhc-header">
          <h1>Delhi HC Case Tracker</h1>
          <span className="dhc-disclaimer-badge">
            Unofficial · Court page is authoritative
          </span>
        </header>
        <main className="dhc-main">{children}</main>
        <footer className="dhc-footer">
          <small>
            This is NOT a Delhi High Court website. Results are best-effort
            parses of the court's public output. The court's own page is
            authoritative. We never bypass court security controls.{" "}
            <a href="/privacy">Privacy</a> · <a href="/disclaimer">Disclaimer</a>
          </small>
        </footer>
      </body>
    </html>
  );
}
