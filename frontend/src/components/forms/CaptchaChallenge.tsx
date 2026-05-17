"use client";

/**
 * CaptchaChallenge — shows the court-issued CAPTCHA, collects the user's
 * answer, and submits it. Owns:
 *   - the base64 image + countdown timer
 *   - the "Refresh CAPTCHA" button (calls /refresh-captcha, never re-inits)
 *   - auto-refresh on `captcha_failed` (with a 1.5s message hold) and on
 *     `expired` (immediate, with a banner)
 *   - the 3-attempt cap per API contract (attempts_remaining)
 *
 * The session_id is passed in as a prop and never exposed in the DOM beyond
 * the network request to /refresh-captcha (which encodes it in the path). It
 * is treated like a credential per the SearchFlow brief.
 */

import { useEffect, useId, useRef, useState } from "react";

import { ApiError, refreshCaptcha, searchSubmit } from "@/services/api";
import {
  MAX_CAPTCHA_LENGTH,
  MIN_CAPTCHA_LENGTH,
  type RefreshCaptchaResponse,
  type SearchSubmitResponse,
} from "@/types/api";
import { formatCountdown, secondsUntil } from "@/lib/date-format";
import { STRINGS } from "@/lib/strings";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";

export type CaptchaSubmitOutcome =
  | { kind: "result"; response: Extract<SearchSubmitResponse, { status: "success" }> | SearchSubmitResponse }
  | { kind: "court_error"; response: SearchSubmitResponse }
  | { kind: "not_found"; response: SearchSubmitResponse }
  | { kind: "exhausted" } // 3 failed attempts → parent should reset to form
  | { kind: "api_error"; error: ApiError };

export type CaptchaChallengeProps = {
  readonly sessionId: string;
  readonly initialCaptchaB64: string;
  readonly initialCaptchaMime: string;
  readonly initialExpiresAt: string;

  /** Called once a terminal result (or hard error) is reached. */
  readonly onResolve: (outcome: CaptchaSubmitOutcome) => void;

  /**
   * Called when the user clicks "Start over" — parent should drop the session
   * and return to the form. Also invoked internally on `exhausted`.
   */
  readonly onAbort: () => void;
};

type CaptchaState = {
  readonly b64: string;
  readonly mime: string;
  readonly expiresAt: string;
};

export function CaptchaChallenge(props: CaptchaChallengeProps) {
  const {
    sessionId,
    initialCaptchaB64,
    initialCaptchaMime,
    initialExpiresAt,
    onResolve,
    onAbort,
  } = props;

  const [captcha, setCaptcha] = useState<CaptchaState>({
    b64: initialCaptchaB64,
    mime: initialCaptchaMime,
    expiresAt: initialExpiresAt,
  });
  const [text, setText] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [attemptsRemaining, setAttemptsRemaining] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number>(
    secondsUntil(initialExpiresAt),
  );
  const inputRef = useRef<HTMLInputElement | null>(null);
  const inputId = useId();

  // Autofocus the input on mount (US-02 / US-10 AC-2 — mobile autofocus).
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Countdown tick. We intentionally update once per second and never sleep
  // longer than that — `setInterval` is debounced when the tab is backgrounded
  // by the browser, which is fine here (we re-sync on focus).
  useEffect(() => {
    setSecondsLeft(secondsUntil(captcha.expiresAt));
    const handle = window.setInterval(() => {
      setSecondsLeft(secondsUntil(captcha.expiresAt));
    }, 1000);
    return () => window.clearInterval(handle);
  }, [captcha.expiresAt]);

  const isExpired = secondsLeft <= 0;

  async function handleRefresh(reasonMessage?: string): Promise<void> {
    if (refreshing) return;
    setRefreshing(true);
    setStatusMessage(reasonMessage ?? null);
    try {
      const fresh: RefreshCaptchaResponse = await refreshCaptcha(sessionId);
      setCaptcha({
        b64: fresh.captcha_image_b64,
        mime: fresh.captcha_mime,
        expiresAt: fresh.captcha_expires_at,
      });
      setText("");
      inputRef.current?.focus();
      // Clear the "refreshing…" message once the new image is in.
      if (reasonMessage) setStatusMessage(null);
    } catch (err) {
      if (err instanceof ApiError) {
        // Session may have expired (404 session_not_found) or upstream broke.
        onResolve({ kind: "api_error", error: err });
      } else {
        onResolve({
          kind: "api_error",
          error: new ApiError({
            code: "unknown",
            message: "Refresh failed",
            retryable: false,
            httpStatus: 0,
          }),
        });
      }
    } finally {
      setRefreshing(false);
    }
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    if (submitting) return;
    if (text.trim().length < MIN_CAPTCHA_LENGTH) return;

    setSubmitting(true);
    setStatusMessage(null);
    try {
      const res = await searchSubmit({
        session_id: sessionId,
        captcha_text: text.trim(),
      });

      switch (res.status) {
        case "success":
          onResolve({ kind: "result", response: res });
          return;
        case "not_found":
          onResolve({ kind: "not_found", response: res });
          return;
        case "court_error":
          onResolve({ kind: "court_error", response: res });
          return;
        case "captcha_failed": {
          const remaining = res.attempts_remaining ?? null;
          setAttemptsRemaining(remaining);
          if (remaining !== null && remaining <= 0) {
            onResolve({ kind: "exhausted" });
            return;
          }
          // Hold the friendly message for ~1.5s then auto-refresh.
          setStatusMessage(STRINGS.captcha.captchaMismatch);
          window.setTimeout(() => {
            void handleRefresh();
          }, 1500);
          return;
        }
        case "expired": {
          // Auto-refresh CAPTCHA — preserve form state by definition (only the
          // CAPTCHA text is wiped; the session-level case fields stay on the
          // backend).
          await handleRefresh(STRINGS.captcha.expired);
          return;
        }
        default: {
          // Forward-compatibility: unknown status from the backend → bubble up.
          const exhaustive: never = res.status as never;
          void exhaustive;
          onResolve({
            kind: "api_error",
            error: new ApiError({
              code: "unknown",
              message: "Unexpected response status from the server.",
              retryable: false,
              httpStatus: 200,
            }),
          });
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        onResolve({ kind: "api_error", error: err });
      } else {
        onResolve({
          kind: "api_error",
          error: new ApiError({
            code: "unknown",
            message: "Submit failed",
            retryable: false,
            httpStatus: 0,
          }),
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  const submitDisabled =
    submitting ||
    refreshing ||
    text.trim().length < MIN_CAPTCHA_LENGTH ||
    isExpired;

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-5 rounded-md border border-gray-200 bg-white p-4 sm:p-6"
      aria-busy={submitting || refreshing}
    >
      <header className="space-y-1">
        <h2 className="text-base font-semibold text-fg">
          {STRINGS.captcha.title}
        </h2>
        <p className="text-sm text-fg-muted">{STRINGS.captcha.description}</p>
      </header>

      {/* CAPTCHA image + countdown */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center justify-center rounded-md border border-gray-200 bg-gray-50 p-3 min-h-[80px]">
          {refreshing ? (
            <Spinner size="md" label="Loading new CAPTCHA…" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- base64 data URL, not a remote asset
            <img
              src={`data:${captcha.mime};base64,${captcha.b64}`}
              alt={STRINGS.captcha.altText}
              width={240}
              height={72}
              className="block max-h-20 w-auto"
            />
          )}
        </div>

        <div className="flex flex-col items-start gap-2 sm:items-end">
          <div
            className="text-sm text-fg-muted"
            aria-live="polite"
            aria-atomic="true"
          >
            {isExpired ? (
              <span className="text-danger">{STRINGS.captcha.expired}</span>
            ) : (
              <>
                <span>{STRINGS.captcha.expiresIn} </span>
                <span className="font-mono">{formatCountdown(secondsLeft)}</span>
              </>
            )}
          </div>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void handleRefresh()}
            disabled={refreshing || submitting}
            aria-label={STRINGS.captcha.refresh}
          >
            {STRINGS.captcha.refresh}
          </Button>
        </div>
      </div>

      {/* Status message (mismatched / expired) */}
      {statusMessage ? (
        <p
          role="alert"
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          {statusMessage}
          {attemptsRemaining !== null ? (
            <span className="ml-1 text-amber-800">
              ({STRINGS.captcha.attemptsRemaining}: {attemptsRemaining})
            </span>
          ) : null}
        </p>
      ) : null}

      {/* Input */}
      <div>
        <label htmlFor={inputId} className="block text-sm font-medium text-fg">
          {STRINGS.captcha.inputLabel}
        </label>
        <p className="mt-1 text-xs text-fg-muted">{STRINGS.captcha.inputHint}</p>
        <input
          id={inputId}
          ref={inputRef}
          name="captcha_text"
          type="text"
          inputMode="text"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={MAX_CAPTCHA_LENGTH}
          minLength={MIN_CAPTCHA_LENGTH}
          disabled={submitting || refreshing}
          className="mt-2 block w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 text-base tracking-widest text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent min-h-[44px]"
        />
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
        <Button
          type="button"
          variant="ghost"
          onClick={onAbort}
          aria-label={STRINGS.captcha.startOver}
        >
          {STRINGS.captcha.startOver}
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={submitDisabled}
          aria-label={STRINGS.captcha.submit}
        >
          {submitting ? (
            <>
              <Spinner size="sm" />
              <span>{STRINGS.captcha.submitting}</span>
            </>
          ) : (
            STRINGS.captcha.submit
          )}
        </Button>
      </div>
    </form>
  );
}
