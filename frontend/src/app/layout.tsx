import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Delhi HC Case Tracker",
  description:
    "Workflow-simplification wrapper over the public Delhi High Court case-status search. NOT a court-operated site.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
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
