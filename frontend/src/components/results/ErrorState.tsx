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
 *
 * Dev-mode debugging panel
 * ------------------------
 * In development builds ONLY (`process.env.NODE_ENV !== "production"`) the
 * component also renders a visually-distinct secondary card with the raw
 * machine details: `code`, `hint`, `request_id` (copyable), `raw message`,
 * `HTTP status`, and a collapsible pretty-printed response body. None of
 * this leaks to production — every dev field is gated on the same env check.
 *
 * `NODE_ENV` is a special-cased env var in Next.js: it's statically inlined
 * at build time on both server and client, so reading `process.env.NODE_ENV`
 * here is SSR-safe and produces a dead-code branch in production bundles.
 */

import { useCallback, useState } from "react";

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

  // ─── Dev-mode-only props ────────────────────────────────────────────────
  // Optional metadata surfaced ONLY in non-production builds. The
  // production rendering path never reads these. SearchFlow forwards them
  // straight from the typed ApiError so we don't have to plumb a second
  // shape through the reducer.

  /** Backend's stable error code (e.g. "court_error", "captcha_unavailable"). */
  readonly devErrorCode?: string;
  /** Optional `hint` string from the error envelope. */
  readonly devHint?: string;
  /** Technical message from the envelope (not the user-friendly copy). */
  readonly devRawMessage?: string;
  /** HTTP status code that produced this error (0 for transport failures). */
  readonly devHttpStatus?: number;
  /**
   * Raw response payload as captured by api.ts. Parsed JSON object when
   * the response was JSON; raw text string for HTML / plain-text bodies;
   * undefined when there was no body (e.g. network failure).
   */
  readonly devRawBody?: unknown;
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

/**
 * Dev-mode-only check. `NODE_ENV` is statically inlined by Next.js so this
 * resolves to a literal at build time and the dev branch is dead-code
 * eliminated from the production bundle.
 */
function isDevMode(): boolean {
  return process.env.NODE_ENV !== "production";
}

/** Stringify the raw response body for the collapsible Details panel. */
function formatRawBody(rawBody: unknown): string {
  if (rawBody === undefined || rawBody === null) return "";
  if (typeof rawBody === "string") return rawBody;
  try {
    return JSON.stringify(rawBody, null, 2);
  } catch {
    // Cyclic or otherwise un-serialisable — fall back to a best-effort string.
    return String(rawBody);
  }
}

export function ErrorState({
  variant,
  requestId,
  courtSiteUrl,
  onRetry,
  onStartOver,
  devErrorCode,
  devHint,
  devRawMessage,
  devHttpStatus,
  devRawBody,
}: ErrorStateProps) {
  const copy = COPY[variant];
  const showRetry = copy.showRetry && Boolean(onRetry);
  const dev = isDevMode();

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

      {dev ? (
        <DevDetailsPanel
          code={devErrorCode}
          hint={devHint}
          rawMessage={devRawMessage}
          httpStatus={devHttpStatus}
          requestId={requestId}
          rawBody={devRawBody}
        />
      ) : null}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Dev-mode panel
// ──────────────────────────────────────────────────────────────────────────

type DevDetailsPanelProps = {
  readonly code?: string;
  readonly hint?: string;
  readonly rawMessage?: string;
  readonly httpStatus?: number;
  readonly requestId?: string;
  readonly rawBody?: unknown;
};

function DevDetailsPanel({
  code,
  hint,
  rawMessage,
  httpStatus,
  requestId,
  rawBody,
}: DevDetailsPanelProps) {
  const formattedBody = formatRawBody(rawBody);
  const hasAnyDetail =
    Boolean(code) ||
    Boolean(hint) ||
    Boolean(rawMessage) ||
    httpStatus !== undefined ||
    Boolean(requestId) ||
    formattedBody.length > 0;

  if (!hasAnyDetail) return null;

  return (
    <aside
      data-testid="error-state-dev-panel"
      className="space-y-3 rounded-md border border-dashed border-gray-400 bg-gray-100 p-3 text-fg"
    >
      <p className="text-[10px] font-semibold uppercase tracking-wide text-fg-muted">
        {STRINGS.error.devOnlyCaption}
      </p>

      <dl className="space-y-2 text-xs">
        {code ? (
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-fg-muted">{STRINGS.error.devCodeLabel}:</dt>
            <dd>
              <span className="inline-block rounded bg-gray-200 px-2 py-0.5 font-mono text-[11px] text-fg">
                {code}
              </span>
            </dd>
          </div>
        ) : null}

        {hint ? (
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-fg-muted">{STRINGS.error.devHintLabel}:</dt>
            <dd className="font-mono text-[11px]">{hint}</dd>
          </div>
        ) : null}

        {requestId ? (
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-fg-muted">{STRINGS.error.devRequestIdLabel}:</dt>
            <dd>
              <CopyablePill value={requestId} />
            </dd>
          </div>
        ) : null}

        {rawMessage ? (
          <div className="flex flex-wrap items-start gap-2">
            <dt className="text-fg-muted">{STRINGS.error.devRawMessageLabel}:</dt>
            <dd className="font-mono text-[11px] break-words">{rawMessage}</dd>
          </div>
        ) : null}

        {httpStatus !== undefined ? (
          <div className="flex flex-wrap items-center gap-2">
            <dt className="text-fg-muted">{STRINGS.error.devHttpStatusLabel}:</dt>
            <dd className="font-mono text-[11px]">{httpStatus}</dd>
          </div>
        ) : null}
      </dl>

      {formattedBody.length > 0 ? (
        <details
          data-testid="error-state-dev-details"
          className="rounded border border-gray-300 bg-white"
        >
          <summary className="cursor-pointer select-none px-2 py-1 text-xs text-fg-muted">
            {STRINGS.error.devDetailsSummary}
          </summary>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-2 py-2 font-mono text-[11px] text-fg">
            {formattedBody}
          </pre>
        </details>
      ) : null}
    </aside>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Copyable pill
// ──────────────────────────────────────────────────────────────────────────

type CopyablePillProps = {
  readonly value: string;
};

/**
 * Monospace pill rendering `value`, with:
 *  - a Copy button that writes the value to the clipboard, and
 *  - click-to-select-all behaviour on the pill itself (founder grabs the
 *    request_id dozens of times per debugging session).
 *
 * Falls back silently if `navigator.clipboard` is unavailable (older
 * browsers / non-secure contexts) — the click-to-select-all still works.
 */
function CopyablePill({ value }: CopyablePillProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    const nav: Navigator | undefined =
      typeof navigator !== "undefined" ? navigator : undefined;
    const clipboard = nav?.clipboard;
    if (!clipboard) return;
    clipboard.writeText(value).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => {
        // Permission denied / write failed — leave the UI quiet; the
        // click-to-select-all path still lets the user copy manually.
      },
    );
  }, [value]);

  const handlePillClick = useCallback((event: React.MouseEvent<HTMLSpanElement>) => {
    const node = event.currentTarget;
    const selection = typeof window !== "undefined" ? window.getSelection() : null;
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
  }, []);

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        role="textbox"
        tabIndex={0}
        aria-readonly="true"
        onClick={handlePillClick}
        className="inline-block cursor-text select-all rounded bg-gray-200 px-2 py-0.5 font-mono text-[11px] text-fg"
        data-testid="error-state-dev-request-id"
      >
        {value}
      </span>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={STRINGS.error.devCopyRequestIdAria}
        className="inline-flex items-center rounded border border-gray-300 bg-white px-2 py-0.5 text-[11px] font-medium text-fg hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {copied ? STRINGS.error.devCopied : STRINGS.error.devCopy}
      </button>
    </span>
  );
}
