/**
 * PrivateAlphaBanner — GREEN-ZONE safety rail.
 *
 * Renders a high-contrast, sticky-top banner warning that this build is a
 * closed-group private alpha using LIVE court data. The banner is env-gated
 * so we can keep the same codebase shippable for the `fake` (fixture) mode
 * the team uses for screenshots and design review.
 *
 * Env wiring
 * ----------
 * The backend's authoritative flag is the server-side `CLIENT_MODE` env var
 * (Arjun owns it). The browser cannot read server-only envs, so we mirror the
 * value into `NEXT_PUBLIC_CLIENT_MODE` at build time — Next.js inlines any
 * `NEXT_PUBLIC_*` variable into the client bundle.
 *
 * Operators MUST set both:
 *   CLIENT_MODE=real                (backend)
 *   NEXT_PUBLIC_CLIENT_MODE=real    (frontend, build-time)
 *
 * When `NEXT_PUBLIC_CLIENT_MODE` is anything other than the literal string
 * "real" (including unset, "fake", "", or typos), the banner renders nothing.
 * Fail-safe-quiet by design: the banner is a UX warning, not a security
 * control. The actual "do not call real court" guard lives in Arjun's
 * backend kill-switch.
 *
 * Dismiss behaviour
 * -----------------
 * A small dismiss control hides the banner for the current page view only.
 * State is NOT persisted (no localStorage / cookie) — the banner re-appears
 * on every navigation and every reload. Alpha is the wrong time for a
 * permanent dismiss.
 *
 * Accessibility
 * -------------
 *   - role="region" + aria-label so screen readers announce it as a landmark
 *   - dismiss is a real <button> with aria-label and visible focus ring
 *   - colour contrast: amber-100 text on red-700 background → > 7:1 (AAA)
 *   - sticky-top with z-50 so it never disappears behind other UI
 *   - mobile: text wraps; on >= sm, it stays single-line with truncation off
 */

"use client";

import { useState } from "react";

const CLIENT_MODE_REAL = "real" as const;

export function PrivateAlphaBanner() {
  // Read at render time. `process.env.NEXT_PUBLIC_*` is inlined by Next at
  // build, so this is a simple string comparison — no runtime fetch.
  const clientMode = process.env.NEXT_PUBLIC_CLIENT_MODE;
  const [dismissed, setDismissed] = useState(false);

  if (clientMode !== CLIENT_MODE_REAL) {
    return null;
  }

  if (dismissed) {
    return null;
  }

  return (
    <div
      role="region"
      aria-label="Private alpha warning"
      className="sticky top-0 z-50 w-full border-b-2 border-amber-300 bg-red-700 text-amber-50 shadow-md"
    >
      <div className="mx-auto flex max-w-screen-lg flex-col items-start gap-2 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between sm:gap-4 sm:px-4">
        <p className="font-semibold leading-snug">
          <span aria-hidden="true">🔒 </span>
          <span className="uppercase tracking-wide">
            Private alpha &mdash; do not share.
          </span>{" "}
          <span className="font-normal">
            This is a closed-group test build using live court data. Do not
            forward this URL. The authoritative case-status page is at{" "}
            <a
              href="https://delhihighcourt.nic.in/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-amber-200 underline-offset-2 hover:decoration-white"
            >
              delhihighcourt.nic.in
            </a>
            .
          </span>
        </p>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss private alpha warning for this page"
          className="self-end rounded border border-amber-200 bg-red-800 px-2 py-1 text-xs font-medium text-amber-50 hover:bg-red-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-200 sm:self-auto"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
