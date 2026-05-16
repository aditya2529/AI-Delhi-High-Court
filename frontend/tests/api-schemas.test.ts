import { describe, expect, it } from "vitest";

import {
  ApiErrorEnvelopeSchema,
  ParsedCaseSchema,
  SearchInitResponseSchema,
  SearchSubmitResponseSchema,
} from "@/types/api";

describe("ApiErrorEnvelopeSchema", () => {
  it("accepts the canonical envelope from API-CONTRACT §1.4", () => {
    const parsed = ApiErrorEnvelopeSchema.safeParse({
      error: {
        code: "court_error",
        message: "Upstream unreachable",
        retryable: true,
        request_id: "11111111-1111-1111-1111-111111111111",
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects payloads missing required fields", () => {
    const parsed = ApiErrorEnvelopeSchema.safeParse({
      error: { code: "court_error" },
    });
    expect(parsed.success).toBe(false);
  });
});

describe("SearchInitResponseSchema", () => {
  it("accepts a well-formed init response", () => {
    const parsed = SearchInitResponseSchema.safeParse({
      session_id: "11111111-1111-1111-1111-111111111111",
      captcha_image_b64: "iVBORw0KGgo=",
      captcha_mime: "image/png",
      captcha_expires_at: "2026-05-17T10:01:30Z",
      session_expires_at: "2026-05-17T10:10:00Z",
    });
    expect(parsed.success).toBe(true);
  });

  it("tolerates unknown forward-compatible fields", () => {
    const parsed = SearchInitResponseSchema.safeParse({
      session_id: "11111111-1111-1111-1111-111111111111",
      captcha_image_b64: "abc",
      captcha_mime: "image/png",
      captcha_expires_at: "2026-05-17T10:01:30Z",
      session_expires_at: "2026-05-17T10:10:00Z",
      future_field_we_dont_know_yet: 42,
    });
    expect(parsed.success).toBe(true);
  });
});

describe("SearchSubmitResponseSchema", () => {
  it("accepts a successful response with a ParsedCase", () => {
    const parsed = SearchSubmitResponseSchema.safeParse({
      status: "success",
      result: {
        case_id: "W.P.(C)|1234|2024",
        case_type: "W.P.(C)",
        case_number: "1234",
        year: 2024,
        parties: {
          petitioner: ["ACME"],
          respondent: ["Union of India"],
        },
        status: "Pending",
        orders: [],
        judgments: [],
        raw_html_hash: "abc",
        parsed_at: "2026-05-17T09:42:11Z",
        source_url: "https://delhihighcourt.nic.in/case",
        parser_version: 3,
      },
    });
    expect(parsed.success).toBe(true);
  });

  it("accepts captcha_failed with attempts_remaining", () => {
    const parsed = SearchSubmitResponseSchema.safeParse({
      status: "captcha_failed",
      attempts_remaining: 2,
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects unknown status values", () => {
    const parsed = SearchSubmitResponseSchema.safeParse({
      status: "weird_new_status",
    });
    expect(parsed.success).toBe(false);
  });
});

describe("ParsedCaseSchema", () => {
  it("requires both parties keys (even if one is empty)", () => {
    const bad = ParsedCaseSchema.safeParse({
      case_id: "x",
      case_type: "x",
      case_number: "1",
      year: 2024,
      parties: { petitioner: [] }, // missing respondent
      orders: [],
      judgments: [],
      raw_html_hash: "h",
      parsed_at: "2026-05-17T00:00:00Z",
      source_url: "https://delhihighcourt.nic.in/c",
      parser_version: 1,
    });
    expect(bad.success).toBe(false);
  });
});
