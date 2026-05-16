/**
 * Tests for the api.ts client — maps backend error envelopes to ApiError.
 *
 * Maps to: API-CONTRACT §1.4 (error envelope shape).
 *
 * Strategy: stub `globalThis.fetch` with vi.fn(). No msw dependency required.
 * (The brief mentions msw — fine, but a vi-mocked fetch is the simpler
 * version that runs today on the existing vitest config.) If/when msw is
 * added for richer interception, swap the fetch stub for an msw handler;
 * the assertions stay the same.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, searchInit, searchSubmit, refreshCaptcha } from "@/services/api";

function jsonResponse(body: unknown, init: { status: number }): Response {
  return new Response(JSON.stringify(body), {
    status: init.status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api.ts — error envelope mapping (API-CONTRACT §1.4)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("maps a 503 court_error envelope to an ApiError with code='court_error'", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "court_error",
            message: "Upstream unreachable",
            retryable: true,
            request_id: "11111111-1111-1111-1111-111111111111",
          },
        },
        { status: 503 },
      ),
    );

    await expect(
      searchInit({ case_type: "W.P.(C)", case_number: "1234", year: 2024 }),
    ).rejects.toMatchObject({
      code: "court_error",
      retryable: true,
      httpStatus: 503,
      requestId: "11111111-1111-1111-1111-111111111111",
    });
  });

  it("maps a 404 session_not_found envelope to ApiError (retryable=false)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        {
          error: {
            code: "session_not_found",
            message: "Session expired",
            retryable: false,
            request_id: "22222222-2222-2222-2222-222222222222",
          },
        },
        { status: 404 },
      ),
    );

    await expect(
      refreshCaptcha("00000000-0000-0000-0000-000000000000"),
    ).rejects.toMatchObject({
      code: "session_not_found",
      retryable: false,
      httpStatus: 404,
    });
  });

  it("falls back to code='unknown' when 5xx body is not a valid envelope", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response("<html>500</html>", {
        status: 500,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(
      searchInit({ case_type: "W.P.(C)", case_number: "1", year: 2024 }),
    ).rejects.toMatchObject({
      code: "unknown",
      httpStatus: 500,
    });
  });

  it("throws ApiError(code='network') when fetch itself rejects", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new TypeError("Failed to fetch"),
    );

    const promise = searchInit({
      case_type: "W.P.(C)",
      case_number: "1",
      year: 2024,
    });
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    await expect(promise).rejects.toMatchObject({
      code: "network",
      retryable: true,
    });
  });

  it("does NOT throw on a 200 success — returns parsed body to caller", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        {
          session_id: "11111111-1111-1111-1111-111111111111",
          captcha_image_b64: "abc",
          captcha_mime: "image/png",
          captcha_expires_at: "2026-05-17T10:01:30Z",
          session_expires_at: "2026-05-17T10:10:00Z",
        },
        { status: 200 },
      ),
    );

    const resp = await searchInit({
      case_type: "W.P.(C)",
      case_number: "1234",
      year: 2024,
    });
    expect(resp.session_id).toBe("11111111-1111-1111-1111-111111111111");
  });

  it("body-level status='captcha_failed' on a 200 is NOT thrown — caller branches", async () => {
    /**
     * Per API-CONTRACT §3, business-logical outcomes (captcha_failed, expired,
     * not_found, court_error inside submit) are 200-OK with `status` in body.
     * The api client MUST surface them as resolved values, NOT thrown errors.
     */
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(
        { status: "captcha_failed", attempts_remaining: 2, result: null },
        { status: 200 },
      ),
    );

    const resp = await searchSubmit({
      session_id: "11111111-1111-1111-1111-111111111111",
      captcha_text: "WRONG",
    });
    expect(resp.status).toBe("captcha_failed");
    expect(resp.attempts_remaining).toBe(2);
  });

  it("rejects with code='unknown' when 200 body fails schema validation", async () => {
    // Schema drift surface: backend returns the wrong shape => api.ts MUST
    // produce a typed error (not crash). Pins the contract guard at the seam.
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({ session_id: "not-a-uuid" }, { status: 200 }),
    );

    await expect(
      searchInit({ case_type: "W.P.(C)", case_number: "1", year: 2024 }),
    ).rejects.toMatchObject({
      code: "unknown",
      retryable: false,
    });
  });
});
