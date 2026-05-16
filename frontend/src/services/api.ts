/**
 * Type-safe API client for the Delhi HC Case Tracker backend.
 *
 * Three concerns this module owns:
 *   1. Where the backend lives (`NEXT_PUBLIC_API_BASE_URL` with a sane default).
 *   2. JSON serialization + Zod validation of responses.
 *   3. Turning HTTP failures into a single typed `ApiError` that the UI catches
 *      and routes to ErrorState. The caller NEVER deals with raw fetch errors.
 *
 * Per the API contract:
 *   - 2xx responses NEVER contain an `error` key.
 *   - 4xx/5xx responses ALWAYS contain `{ error: { code, message, retryable,
 *     hint?, request_id } }`.
 *   - Business outcomes (success / not_found / captcha_failed / expired /
 *     court_error inside the submit response) are 200 OK with `status` in body;
 *     those are NOT thrown — the caller branches on `status`.
 */

import {
  ApiErrorEnvelopeSchema,
  type ApiErrorCode,
  type RefreshCaptchaResponse,
  RefreshCaptchaResponseSchema,
  type SearchInitRequest,
  type SearchInitResponse,
  SearchInitResponseSchema,
  type SearchSubmitRequest,
  type SearchSubmitResponse,
  SearchSubmitResponseSchema,
} from "@/types/api";

const DEFAULT_BASE_URL = "http://localhost:8000";

function baseUrl(): string {
  // process.env access on the client side requires NEXT_PUBLIC_ prefix in Next.
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL;
  return (fromEnv && fromEnv.trim().length > 0 ? fromEnv : DEFAULT_BASE_URL).replace(
    /\/+$/,
    "",
  );
}

/** Path under `/api/v1`. */
function url(path: string): string {
  return `${baseUrl()}/api/v1${path}`;
}

/**
 * Typed error thrown for ANY non-2xx response or transport failure.
 * UI catches this and renders an ErrorState variant.
 */
export class ApiError extends Error {
  readonly code: ApiErrorCode | "network" | "unknown";
  readonly retryable: boolean;
  readonly httpStatus: number;
  readonly hint?: string;
  readonly requestId?: string;

  constructor(args: {
    code: ApiErrorCode | "network" | "unknown";
    message: string;
    retryable: boolean;
    httpStatus: number;
    hint?: string;
    requestId?: string;
  }) {
    super(args.message);
    this.name = "ApiError";
    this.code = args.code;
    this.retryable = args.retryable;
    this.httpStatus = args.httpStatus;
    this.hint = args.hint;
    this.requestId = args.requestId;
  }
}

/** Coerce any fetch / parse failure into our typed ApiError. */
function toApiError(err: unknown, fallbackStatus = 0): ApiError {
  if (err instanceof ApiError) return err;
  const message = err instanceof Error ? err.message : "Network request failed";
  return new ApiError({
    code: "network",
    message,
    retryable: true,
    httpStatus: fallbackStatus,
  });
}

async function parseError(res: Response): Promise<ApiError> {
  // Try to read the structured envelope; degrade gracefully if it isn't JSON.
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // ignore — fall through to "unknown" below
  }

  const parsed = ApiErrorEnvelopeSchema.safeParse(body);
  if (parsed.success) {
    const e = parsed.data.error;
    return new ApiError({
      // The envelope `code` is a string in the contract; we narrow opportunistically.
      code: e.code as ApiErrorCode,
      message: e.message,
      retryable: e.retryable,
      httpStatus: res.status,
      hint: e.hint,
      requestId: e.request_id,
    });
  }

  // Fallback — the response wasn't a valid envelope. Don't pretend; route to unknown.
  return new ApiError({
    code: "unknown",
    message: `Unexpected response (HTTP ${res.status}).`,
    retryable: res.status >= 500,
    httpStatus: res.status,
  });
}

type FetchOpts = { method: "GET" | "POST"; body?: unknown };

async function request<T>(
  path: string,
  opts: FetchOpts,
  validate: (json: unknown) => T,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url(path), {
      method: opts.method,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      // No credentials — backend uses no cookies (session is opaque server-side).
      credentials: "omit",
      cache: "no-store",
    });
  } catch (err) {
    throw toApiError(err);
  }

  if (!res.ok) {
    throw await parseError(res);
  }

  let json: unknown;
  try {
    json = await res.json();
  } catch (err) {
    throw toApiError(err, res.status);
  }

  try {
    return validate(json);
  } catch (err) {
    // Schema mismatch — backend drifted from the contract.
    // Treat as `unknown` so the UI shows a generic error rather than a blank screen.
    throw new ApiError({
      code: "unknown",
      message:
        err instanceof Error
          ? `Response did not match the API contract: ${err.message}`
          : "Response did not match the API contract.",
      retryable: false,
      httpStatus: res.status,
    });
  }
}

// ---------------------------------------------------------------------------
// Public methods
// ---------------------------------------------------------------------------

export async function searchInit(req: SearchInitRequest): Promise<SearchInitResponse> {
  return request("/search/init", { method: "POST", body: req }, (json) =>
    SearchInitResponseSchema.parse(json),
  );
}

export async function searchSubmit(
  req: SearchSubmitRequest,
): Promise<SearchSubmitResponse> {
  return request("/search/submit", { method: "POST", body: req }, (json) =>
    SearchSubmitResponseSchema.parse(json),
  );
}

export async function refreshCaptcha(sessionId: string): Promise<RefreshCaptchaResponse> {
  // Per Sneha's note: never include the session ID in logs / URLs that aren't
  // strictly necessary. Here it must be in the path; we keep it out of error
  // messages by handing only the typed envelope to the UI.
  return request(
    `/search/${encodeURIComponent(sessionId)}/refresh-captcha`,
    { method: "GET" },
    (json) => RefreshCaptchaResponseSchema.parse(json),
  );
}
