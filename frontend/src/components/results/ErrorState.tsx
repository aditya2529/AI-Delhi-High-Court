"use client";

/**
 * ErrorState — graceful failure UI. Four variants, mapped from the backend's
 * stable error codes / business statuses by the parent SearchFlow.
 *
 * Every variant carries:
 *   1. A plain-English explanation (no jargon, no stack traces).
 *   2. A primary action button (retry or restart).
 *   3. The "this is a third-party wrapper" disclaimer.
 *
 * If the upstream is the issue (court_error) and we have a source_url, we
 * also offer a direct link to the official Delhi HC site so the user is never
 * a dead end (PRD US-07 AC-1).
 */

import { STRINGS } from "@/lib/strings";
import { Button } from "@/components/ui/Button";

export type ErrorVariant = "court_error" | "not_found" | "network" | "unknown";

export type ErrorStateProps = {
  readonly variant: ErrorVariant;
  /** Optional ref id from the API envelope — helpful for support. */
  readonly requestId?: string;
  /** Optional escape-hatch link to the official site (used on court_error). */
  readonly courtSiteUrl?: string;
  /** Optional retry handler. Some variants (e.g. not_found) hide retry. */
  readonly onRetry?: () => void;
  /** Reset to the form. Always present. */
  readonly onStartOver: () => void;
};

type VariantCopy = {
  readonly title: string;
  readonly body: string;
  readonly showRetry: boolean;
  readonly toneClasses: string;
};

const COPY: Record<ErrorVariant, VariantCopy> = {
  court_error: {
    title: STRINGS.error.courtErrorTitle,
    body: STRINGS.error.courtErrorBody,
    showRetry: true,
    toneClasses: "border-amber-300 bg-amber-50 text-amber-900",
  },
  not_found: {
    title: STRINGS.error.notFoundTitle,
    body: STRINGS.error.notFoundBody,
    showRetry: false,
    toneClasses: "border-gray-300 bg-gray-50 text-fg",
  },
  network: {
    title: STRINGS.error.networkTitle,
    body: STRINGS.error.networkBody,
    showRetry: true,
    toneClasses: "border-red-300 bg-red-50 text-red-900",
  },
  unknown: {
    title: STRINGS.error.unknownTitle,
    body: STRINGS.error.unknownBody,
    showRetry: true,
    toneClasses: "border-red-300 bg-red-50 text-red-900",
  },
};

export function ErrorState({
  variant,
  requestId,
  courtSiteUrl,
  onRetry,
  onStartOver,
}: ErrorStateProps) {
  const copy = COPY[variant];
  const showRetry = copy.showRetry && Boolean(onRetry);
  return (
    <section
      role="alert"
      aria-live="polite"
      className={`space-y-4 rounded-md border p-4 sm:p-6 ${copy.toneClasses}`}
    >
      <header className="space-y-1">
        <h2 className="text-base font-semibold">{copy.title}</h2>
        <p className="text-sm">{copy.body}</p>
      </header>

      {requestId ? (
        <p className="text-xs text-fg-muted">
          {STRINGS.error.requestIdLabel}: <span className="font-mono">{requestId}</span>
        </p>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row">
        {showRetry && onRetry ? (
          <Button variant="primary" onClick={onRetry} aria-label={STRINGS.error.retry}>
            {STRINGS.error.retry}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          onClick={onStartOver}
          aria-label={STRINGS.error.startOver}
        >
          {STRINGS.error.startOver}
        </Button>
        {courtSiteUrl ? (
          <a
            href={courtSiteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-accent hover:bg-gray-50 min-h-[44px]"
          >
            {STRINGS.error.openCourt} &rarr;
          </a>
        ) : null}
      </div>

      <p className="text-xs text-fg-muted">{STRINGS.error.wrapperDisclaimer}</p>
    </section>
  );
}
