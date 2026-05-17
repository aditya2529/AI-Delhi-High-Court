/**
 * Zod schemas + inferred TS types for the public API.
 *
 * Source of truth: `docs/api/API-CONTRACT.md`. If the backend ever drifts from
 * this shape we either (a) bump the parser, or (b) flag Arjun — we do NOT
 * paper over the drift in this file.
 *
 * Forward-compatibility rule (per API-CONTRACT §7.1): unknown fields are
 * IGNORED, not rejected. Hence `.passthrough()` on the response objects.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Common
// ---------------------------------------------------------------------------

/** Error envelope shape from API-CONTRACT §1.4 — every non-2xx response. */
export const ApiErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    retryable: z.boolean(),
    hint: z.string().optional(),
    request_id: z.string(),
  }),
});

export type ApiErrorEnvelope = z.infer<typeof ApiErrorEnvelopeSchema>;

/** Stable error-code enum, from API-CONTRACT §7.2. */
export const API_ERROR_CODES = [
  "invalid_request",
  "session_not_found",
  "in_progress",
  "session_consumed",
  "rate_limited",
  "court_error",
  "captcha_unavailable",
  "upstream_blocked",
  "session_store_down",
  "internal_error",
  "unauthorized",
] as const;
export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

// ---------------------------------------------------------------------------
// /search/init
// ---------------------------------------------------------------------------

export const SearchInitRequestSchema = z.object({
  case_type: z.string().min(1),
  case_number: z.string().regex(/^\d+$/, "digits only").min(1).max(7),
  year: z
    .number()
    .int()
    .gte(1950)
    .lte(new Date().getUTCFullYear()),
});
export type SearchInitRequest = z.infer<typeof SearchInitRequestSchema>;

export const SearchInitResponseSchema = z
  .object({
    session_id: z.string().min(8).max(64),
    captcha_image_b64: z.string().min(1),
    captcha_mime: z.string().min(1),
    captcha_expires_at: z.string(),
    session_expires_at: z.string(),
  })
  .passthrough();
export type SearchInitResponse = z.infer<typeof SearchInitResponseSchema>;

// ---------------------------------------------------------------------------
// /search/submit
// ---------------------------------------------------------------------------

export const PartiesSchema = z
  .object({
    petitioner: z.array(z.string()),
    respondent: z.array(z.string()),
  })
  .passthrough();
export type Parties = z.infer<typeof PartiesSchema>;

export const OrderOrJudgmentSchema = z
  .object({
    date: z.string().nullable().optional(),
    title: z.string(),
    url: z.string().url().nullable().optional(),
  })
  .passthrough();
export type OrderOrJudgment = z.infer<typeof OrderOrJudgmentSchema>;

export const ParsedCaseSchema = z
  .object({
    case_id: z.string(),
    case_type: z.string(),
    case_number: z.string(),
    year: z.number().int(),
    parties: PartiesSchema,
    status: z.string().nullable().optional(),
    last_hearing_date: z.string().nullable().optional(),
    next_hearing_date: z.string().nullable().optional(),
    court_no: z.string().nullable().optional(),
    judge_bench: z.string().nullable().optional(),
    orders: z.array(OrderOrJudgmentSchema),
    judgments: z.array(OrderOrJudgmentSchema),
    raw_html_hash: z.string(),
    parsed_at: z.string(),
    source_url: z.string().url(),
    parser_version: z.number().int(),
    /*
     * `parse_confidence` was REMOVED from the UI contract (Bucket 2 drift #1).
     * The backend's authoritative signal that the parsed result is partial
     * is `parser_degraded` on the SearchSubmitResponse envelope — see below.
     * If the backend ever emits `parse_confidence`, `.passthrough()` will
     * carry it across silently; we deliberately do not key UI behaviour off
     * it.
     */
  })
  .passthrough();
export type ParsedCase = z.infer<typeof ParsedCaseSchema>;

export const SUBMIT_STATUSES = [
  "success",
  "captcha_failed",
  "expired",
  "not_found",
  "court_error",
] as const;
export type SubmitStatus = (typeof SUBMIT_STATUSES)[number];

/**
 * CAPTCHA answer length bounds — the single source of truth for both the
 * Zod request schema below and any UI component that gates submit on length.
 *
 * Mirrors backend Pydantic `SearchSubmitRequest.captcha_text =
 * Field(..., min_length=1, max_length=10)` in `backend/app/schemas/search.py`.
 *
 * Why 1 (not 3)? Delhi HC serves MATH CAPTCHAs (e.g. "19 + 3 =") whose
 * answers can be a single digit ("5+2=7"). Pinning min to 3 silently blocks
 * the most common case. See docs/DEMO-FEEDBACK.md item #6.
 *
 * If these bounds ever change, change them HERE — every downstream consumer
 * (Zod schema, UI input attrs, submit-disable check) imports them.
 */
export const MIN_CAPTCHA_LENGTH = 1;
export const MAX_CAPTCHA_LENGTH = 10;

export const SearchSubmitRequestSchema = z.object({
  session_id: z.string().min(8).max(64),
  captcha_text: z.string().min(MIN_CAPTCHA_LENGTH).max(MAX_CAPTCHA_LENGTH),
});
export type SearchSubmitRequest = z.infer<typeof SearchSubmitRequestSchema>;

export const SearchSubmitResponseSchema = z
  .object({
    status: z.enum(SUBMIT_STATUSES),
    result: ParsedCaseSchema.nullable().optional(),
    parser_degraded: z.boolean().optional(),
    retry_url: z.string().nullable().optional(),
    attempts_remaining: z.number().int().nullable().optional(),
  })
  .passthrough();
export type SearchSubmitResponse = z.infer<typeof SearchSubmitResponseSchema>;

// ---------------------------------------------------------------------------
// /search/{session_id}/refresh-captcha
// ---------------------------------------------------------------------------

export const RefreshCaptchaResponseSchema = z
  .object({
    captcha_image_b64: z.string().min(1),
    captcha_mime: z.string().min(1),
    captcha_expires_at: z.string(),
    session_expires_at: z.string(),
  })
  .passthrough();
export type RefreshCaptchaResponse = z.infer<typeof RefreshCaptchaResponseSchema>;
