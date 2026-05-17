"use client";

/**
 * SearchFlow — top-level state machine for the case-search workflow.
 *
 * Phases:
 *   form    → user enters case_type/number/year
 *   captcha → CAPTCHA presented; user solves it
 *   loading → /submit in flight (own phase so we can show a deterministic
 *             "waiting on court site" message; CaptchaChallenge owns
 *             in-button spinners, this phase owns the full-card spinner)
 *   result  → ParsedCase rendered
 *   error   → graceful failure UI
 *
 * The `session_id` returned by /init lives ONLY inside the reducer state of
 * this component. It never goes into localStorage, never into a URL, never
 * into a log line. Per Sneha + the brief: treat it like a credential.
 *
 * The reducer is a strict discriminated union — zero `any`. Every action
 * lists the phases it is legal in; an illegal pairing returns the previous
 * state unchanged, which is safer than throwing in production.
 */

import { useCallback, useReducer } from "react";

import { ApiError, searchInit } from "@/services/api";
import type {
  ParsedCase,
  SearchInitResponse,
  SearchSubmitResponse,
} from "@/types/api";
import type { SearchFormValues } from "@/components/forms/SearchForm";
import { SearchForm } from "@/components/forms/SearchForm";
import {
  CaptchaChallenge,
  type CaptchaSubmitOutcome,
} from "@/components/forms/CaptchaChallenge";
import { CaseResult } from "@/components/results/CaseResult";
import {
  ErrorState,
  type ErrorVariant,
} from "@/components/results/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { STRINGS } from "@/lib/strings";

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type FlowState =
  | {
      phase: "form";
      submitting: boolean;
      lastValues?: SearchFormValues;
      banner?: string;
    }
  | {
      phase: "captcha";
      values: SearchFormValues;
      sessionId: string;
      captchaB64: string;
      captchaMime: string;
      captchaExpiresAt: string;
    }
  | {
      phase: "loading";
      values: SearchFormValues;
    }
  | {
      phase: "result";
      values: SearchFormValues;
      data: ParsedCase;
      parserDegraded: boolean;
    }
  | {
      phase: "error";
      variant: ErrorVariant;
      requestId?: string;
      courtSiteUrl?: string;
      values?: SearchFormValues;
      // Dev-mode debugging metadata. Captured here so ErrorState can render
      // the dev-only panel without a separate plumbing path. In production
      // builds ErrorState ignores these — they are inert payload.
      devErrorCode?: string;
      devHint?: string;
      devRawMessage?: string;
      devHttpStatus?: number;
      devRawBody?: unknown;
    };

type FlowAction =
  | { type: "form/submit"; values: SearchFormValues }
  | {
      type: "form/init-success";
      values: SearchFormValues;
      response: SearchInitResponse;
    }
  | {
      type: "form/init-failure";
      values: SearchFormValues;
      variant: ErrorVariant;
      requestId?: string;
      error?: ApiError;
    }
  | { type: "captcha/abort" }
  | {
      type: "captcha/result";
      response: SearchSubmitResponse;
    }
  | {
      type: "captcha/court-error";
      requestId?: string;
      values: SearchFormValues;
    }
  | {
      type: "captcha/not-found";
      values: SearchFormValues;
    }
  | { type: "captcha/exhausted" }
  | {
      type: "captcha/api-error";
      error: ApiError;
      values: SearchFormValues;
    }
  | { type: "result/search-again" }
  | { type: "error/retry" }
  | { type: "error/start-over" };

function initialState(): FlowState {
  return { phase: "form", submitting: false };
}

function mapApiErrorToVariant(err: ApiError): ErrorVariant {
  switch (err.code) {
    case "court_error":
    case "captcha_unavailable":
    case "upstream_blocked":
      return "court_error";
    case "invalid_request":
    case "session_not_found":
    case "session_consumed":
      // The user can't act on these except by starting over; show a generic
      // network-ish error so they reset.
      return "network";
    case "rate_limited":
    case "internal_error":
    case "session_store_down":
    case "network":
      return "network";
    default:
      return "unknown";
  }
}

function reducer(state: FlowState, action: FlowAction): FlowState {
  switch (action.type) {
    case "form/submit": {
      if (state.phase !== "form") return state;
      return {
        phase: "form",
        submitting: true,
        lastValues: action.values,
        banner: undefined,
      };
    }

    case "form/init-success": {
      // Allow from "form" (normal) or "error" (retry path).
      if (state.phase !== "form" && state.phase !== "error") return state;
      return {
        phase: "captcha",
        values: action.values,
        sessionId: action.response.session_id,
        captchaB64: action.response.captcha_image_b64,
        captchaMime: action.response.captcha_mime,
        captchaExpiresAt: action.response.captcha_expires_at,
      };
    }

    case "form/init-failure": {
      return {
        phase: "error",
        variant: action.variant,
        requestId: action.requestId,
        values: action.values,
        devErrorCode: action.error?.code,
        devHint: action.error?.hint,
        devRawMessage: action.error?.message,
        devHttpStatus: action.error?.httpStatus,
        devRawBody: action.error?.rawBody,
      };
    }

    case "captcha/abort": {
      if (state.phase !== "captcha") return state;
      return {
        phase: "form",
        submitting: false,
        lastValues: state.values,
      };
    }

    case "captcha/result": {
      if (state.phase !== "captcha") return state;
      if (action.response.status === "success" && action.response.result) {
        return {
          phase: "result",
          values: state.values,
          data: action.response.result,
          parserDegraded: Boolean(action.response.parser_degraded),
        };
      }
      // Defensive — caller should have routed non-success elsewhere.
      return state;
    }

    case "captcha/court-error": {
      return {
        phase: "error",
        variant: "court_error",
        requestId: action.requestId,
        values: action.values,
      };
    }

    case "captcha/not-found": {
      return {
        phase: "error",
        variant: "not_found",
        values: action.values,
      };
    }

    case "captcha/exhausted": {
      if (state.phase !== "captcha") return state;
      return {
        phase: "form",
        submitting: false,
        lastValues: state.values,
        banner: STRINGS.captcha.tooManyFailures,
      };
    }

    case "captcha/api-error": {
      return {
        phase: "error",
        variant: mapApiErrorToVariant(action.error),
        requestId: action.error.requestId,
        values: action.values,
        devErrorCode: action.error.code,
        devHint: action.error.hint,
        devRawMessage: action.error.message,
        devHttpStatus: action.error.httpStatus,
        devRawBody: action.error.rawBody,
      };
    }

    case "result/search-again":
    case "error/start-over": {
      return initialState();
    }

    case "error/retry": {
      if (state.phase !== "error") return state;
      // Drop to the form, preserve the inputs so the user can re-fire /init.
      return {
        phase: "form",
        submitting: false,
        lastValues: state.values,
      };
    }

    default: {
      const exhaustive: never = action;
      void exhaustive;
      return state;
    }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SearchFlow() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  const handleFormSubmit = useCallback(
    async (values: SearchFormValues): Promise<void> => {
      dispatch({ type: "form/submit", values });
      try {
        const response = await searchInit({
          case_type: values.caseType,
          case_number: values.caseNumber,
          year: values.year,
        });
        dispatch({ type: "form/init-success", values, response });
      } catch (err) {
        if (err instanceof ApiError) {
          dispatch({
            type: "form/init-failure",
            values,
            variant: mapApiErrorToVariant(err),
            requestId: err.requestId,
            error: err,
          });
        } else {
          dispatch({
            type: "form/init-failure",
            values,
            variant: "unknown",
          });
        }
      }
    },
    [],
  );

  const handleCaptchaResolve = useCallback(
    (outcome: CaptchaSubmitOutcome): void => {
      if (state.phase !== "captcha") return;
      switch (outcome.kind) {
        case "result":
          dispatch({ type: "captcha/result", response: outcome.response });
          return;
        case "not_found":
          dispatch({ type: "captcha/not-found", values: state.values });
          return;
        case "court_error":
          dispatch({
            type: "captcha/court-error",
            values: state.values,
          });
          return;
        case "exhausted":
          dispatch({ type: "captcha/exhausted" });
          return;
        case "api_error":
          dispatch({
            type: "captcha/api-error",
            error: outcome.error,
            values: state.values,
          });
          return;
      }
    },
    [state],
  );

  const handleCaptchaAbort = useCallback(() => {
    dispatch({ type: "captcha/abort" });
  }, []);

  switch (state.phase) {
    case "form":
      return (
        <SearchForm
          onSubmit={handleFormSubmit}
          submitting={state.submitting}
          initialValues={state.lastValues}
          bannerMessage={state.banner}
        />
      );

    case "captcha":
      return (
        <CaptchaChallenge
          sessionId={state.sessionId}
          initialCaptchaB64={state.captchaB64}
          initialCaptchaMime={state.captchaMime}
          initialExpiresAt={state.captchaExpiresAt}
          onResolve={handleCaptchaResolve}
          onAbort={handleCaptchaAbort}
        />
      );

    case "loading":
      return (
        <div
          className="flex flex-col items-center gap-3 rounded-md border border-gray-200 bg-white p-6 text-center"
          aria-live="polite"
        >
          <Spinner size="lg" />
          <p className="text-sm font-medium text-fg">
            {STRINGS.loading.submittingTitle}
          </p>
          <p className="text-xs text-fg-muted">
            {STRINGS.loading.submittingBody}
          </p>
        </div>
      );

    case "result":
      return (
        <CaseResult
          data={state.data}
          parserDegraded={state.parserDegraded}
          onSearchAgain={() => dispatch({ type: "result/search-again" })}
        />
      );

    case "error":
      return (
        <ErrorState
          variant={state.variant}
          requestId={state.requestId}
          courtSiteUrl={state.courtSiteUrl}
          onRetry={() => dispatch({ type: "error/retry" })}
          onStartOver={() => dispatch({ type: "error/start-over" })}
          devErrorCode={state.devErrorCode}
          devHint={state.devHint}
          devRawMessage={state.devRawMessage}
          devHttpStatus={state.devHttpStatus}
          devRawBody={state.devRawBody}
        />
      );

    default: {
      const exhaustive: never = state;
      void exhaustive;
      return null;
    }
  }
}
