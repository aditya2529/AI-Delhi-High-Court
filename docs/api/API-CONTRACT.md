# Delhi HC Case Tracker — Public API Contract (v1)

**Status:** Draft v0.1 · **Owner:** Arnav (Architecture) · **Last updated:** 2026-05-17
**Spec convention:** OpenAPI 3.1-compatible, expressed in markdown tables for review speed. A formal `openapi.yaml` will be generated from FastAPI's pydantic models — this document is the **source of truth for shapes**, not for syntax.

**Base URL (MVP):** `https://delhihc-tracker.local/api/v1` (dev) · `/api/v1` (relative path always works)

**Versioning:** URL-versioned (`/api/v1/...`). Breaking changes bump to `/api/v2/...`. The `parser_version` field inside `ParsedCase` is independent — it reflects the parser revision, not the API.

---

## 1. Common Conventions

### 1.1 Content type
- All requests/responses are `application/json; charset=utf-8` unless otherwise noted.
- CAPTCHA images are returned **base64-encoded inside JSON**, never as `image/*` bytes — keeps the frontend uniform and avoids extra round-trips.

### 1.2 Request headers

| Header | Required | Notes |
|---|---|---|
| `Content-Type: application/json` | yes (on POST) | |
| `X-Request-Id` | optional | UUID; if absent, server mints one and echoes in response |
| `X-Admin-Secret` | required on `/admin/*` | shared secret; MVP-only auth boundary |
| `Idempotency-Key` | optional | reserved; honored on `/search/init` only |

### 1.3 Response headers (all responses)

| Header | Value |
|---|---|
| `X-Request-Id` | echo of incoming or freshly minted |
| `X-RateLimit-Limit` | configured limit per client IP per minute (default 30) |
| `X-RateLimit-Remaining` | remaining in current window |
| `X-RateLimit-Reset` | unix epoch seconds when the window resets |
| `Retry-After` | seconds, only on 429 / 503 |

### 1.4 Error envelope

Every non-2xx response uses **exactly this shape**:

```json
{
  "error": {
    "code": "snake_case_machine_code",
    "message": "Human-readable, safe to show end-user",
    "retryable": true,
    "hint": "Optional next-action guidance for the UI",
    "request_id": "uuid-echo-of-request"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `code` | string | yes | machine code; stable enum (see §6) |
| `message` | string | yes | safe to render to end-user verbatim |
| `retryable` | boolean | yes | `true` → client may retry the same call; `false` → don't |
| `hint` | string | no | actionable suggestion |
| `request_id` | string (uuid) | yes | for support correlation |

**Rule:** 2xx responses NEVER contain an `error` key. 4xx/5xx responses ALWAYS contain `error` and NEVER `result`.

### 1.5 Idempotency
- `POST /search/init` is idempotent **per `Idempotency-Key`** within a 60s window — repeats return the original `session_id` and `captcha_image_b64`. Without the header, every call mints a new session.
- `POST /search/submit` is **NOT idempotent**. A repeat submit on the same `session_id` returns `409 in_progress` if first is still running, or `410 session_consumed` if it completed.
- `GET /search/{session_id}/refresh-captcha` is idempotent in the everyday sense but **does cause an upstream call**; clients should debounce.

### 1.6 Rate limiting
- Inbound: 30 req/min per client IP across all endpoints (configurable). Exceeded → `429 rate_limited`.
- Inbound to `/admin/*`: 60 req/min per admin secret.
- Outbound (we → court site): 2 req/s global, enforced server-side; not visible to client.

---

## 2. POST /api/v1/search/init

Initialize a search session. Server opens an upstream session, fetches the CAPTCHA image, and returns it to the client.

### Request body

| Field | Type | Required | Constraints |
|---|---|---|---|
| `case_type` | string | yes | enum, validated against the court's published list; uppercase, e.g. `"W.P.(C)"`, `"CRL.A."` |
| `case_number` | string | yes | digits only, 1–7 chars; leading zeros stripped. Reserved sentinel `"COURT_ERROR"` routes to the COURT_ERROR fixture when `CLIENT_MODE=fake` (no-op selector when `CLIENT_MODE=real`); test plumbing only. |
| `year` | integer | yes | 1950 ≤ year ≤ current_year |

### Response 200

| Field | Type | Notes |
|---|---|---|
| `session_id` | string (UUID v4, dashed — see §7.3) | opaque to client; used in subsequent calls |
| `captcha_image_b64` | string | base64-encoded PNG/JPEG (whatever upstream sends; MIME normalized to PNG when feasible) |
| `captcha_mime` | string | `"image/png"` \| `"image/jpeg"` |
| `captcha_expires_at` | string (RFC 3339) | absolute expiry; client should show a countdown |
| `session_expires_at` | string (RFC 3339) | typically captcha_expires_at + several minutes; for state-machine display |

### Status codes

| Status | Code | Meaning |
|---|---|---|
| 200 | — | session created, CAPTCHA returned |
| 400 | `invalid_request` | body validation failed |
| 429 | `rate_limited` | inbound rate-limit exceeded |
| 503 | `court_error` | upstream unreachable after retries (retryable) |
| 503 | `captcha_unavailable` | upstream reached but CAPTCHA image fetch failed |
| 503 | `upstream_blocked` | circuit breaker open |
| 500 | `internal_error` | unexpected; logs have `request_id` |

---

## 3. POST /api/v1/search/submit

Submit the user's CAPTCHA answer. Server submits the form upstream using the same session, parses the result.

### Request body

| Field | Type | Required | Constraints |
|---|---|---|---|
| `session_id` | string (UUID v4, dashed — see §7.3) | yes | must match an active session |
| `captcha_text` | string | yes | 1–10 chars, trimmed; server normalizes case if upstream is case-insensitive (TO BE VERIFIED IN SPIKE) |

### Response 200

The response is a **discriminated union** on `status`:

| Field | Type | Notes |
|---|---|---|
| `status` | string | enum: `success` \| `captcha_failed` \| `expired` \| `not_found` \| `court_error` |
| `result` | `ParsedCase` \| null | present iff `status === "success"` |
| `parser_degraded` | boolean | `true` iff parser fell back to partial extraction |
| `retry_url` | string \| null | only on `expired`; relative URL to refresh CAPTCHA |
| `attempts_remaining` | integer \| null | only on `captcha_failed`; default 3 attempts per session |

### Per-status semantics

| `status` | Meaning | HTTP code | Frontend action |
|---|---|---|---|
| `success` | upstream returned a case page, parsed (possibly degraded) | 200 | render `ParsedCase`, end session |
| `captcha_failed` | upstream rejected the CAPTCHA text | 200 | show error, re-prompt with same image (if attempts > 0) or refresh |
| `expired` | CAPTCHA/upstream session expired | 200 | call `retry_url` and re-prompt |
| `not_found` | upstream confirmed no such case | 200 | render "no case found" UI |
| `court_error` | upstream errored mid-submit | 200 (logical) — body says court_error | show "Court site error; try again" |

**Note** on HTTP status: business-logical outcomes (success/not-found/captcha-failed/expired) are **200 OK** with `status` in body. We reserve 4xx/5xx for **transport-level** problems (validation, rate-limit, server bug, unreachable upstream after retries). This keeps the client's error-handling crisp.

**LOCKED behaviour — wrong/expired CAPTCHA returns HTTP 200:** Wrong-CAPTCHA and expired-CAPTCHA conditions return HTTP `200` with a body-level `status` of `captcha_failed` or `expired` respectively. This is deliberate — the request was structurally valid, the upstream just returned a rejection. Future devs should **NOT** "fix" these to `4xx` (e.g., 422). The frontend dispatches on the body-level `status` field; switching to a 4xx HTTP code would silently break that contract because the JSON envelope changes from a success body to an `error` envelope (see §1.4 rule: "4xx/5xx responses ALWAYS contain `error` and NEVER `result`").

### Status codes

| Status | Code | Meaning |
|---|---|---|
| 200 | — | submit processed; see `status` in body |
| 400 | `invalid_request` | body validation failed |
| 404 | `session_not_found` | session_id unknown or expired (TTL passed) |
| 409 | `in_progress` | a previous submit is still running for this session |
| 410 | `session_consumed` | this session already produced a result |
| 429 | `rate_limited` | inbound rate-limit exceeded |
| 503 | `court_error` | upstream unreachable after retries |
| 503 | `upstream_blocked` | circuit breaker open |
| 500 | `internal_error` | unexpected |

---

## 4. GET /api/v1/search/{session_id}/refresh-captcha

Re-fetch the CAPTCHA image for an existing session without losing form state. Used when the CAPTCHA expires before submit.

### Path params

| Param | Type | Notes |
|---|---|---|
| `session_id` | string (UUID v4, dashed — see §7.3) | from /init |

### Response 200

Same shape as `/search/init` minus `session_id` (already known):

| Field | Type |
|---|---|
| `captcha_image_b64` | string |
| `captcha_mime` | string |
| `captcha_expires_at` | string (RFC 3339) |
| `session_expires_at` | string (RFC 3339) |

### Status codes

| Status | Code | Meaning |
|---|---|---|
| 200 | — | new CAPTCHA returned |
| 404 | `session_not_found` | session expired or unknown |
| 410 | `session_consumed` | already submitted, refresh meaningless |
| 503 | `court_error` / `captcha_unavailable` | upstream errored |

---

## 5. GET /api/v1/health

Liveness/readiness probe. No auth.

### Response 200

| Field | Type | Notes |
|---|---|---|
| `status` | string | `"ok"` \| `"degraded"` |
| `version` | string | semver |
| `parser_version` | integer | current parser revision |
| `checks` | object | `{ db: "ok", session_store: "ok", court_circuit: "closed" | "open" | "half_open" }` |
| `uptime_seconds` | integer | |

Status 200 always while process is up; the `status` field reflects whether the breaker is open. 503 only if app cannot serve at all.

---

## 6. Admin Endpoints

Gated by `X-Admin-Secret` header matching `ADMIN_SHARED_SECRET` env var. **MVP-only** auth; production needs proper SSO (see ADR notes).

### 6.1 GET /api/v1/admin/sessions

Lists active sessions for observability. **Never** returns upstream cookies or CSRF tokens.

#### Query params

| Param | Type | Notes |
|---|---|---|
| `status` | string | optional filter: `pending_captcha` \| `submitting` \| `expired` |
| `limit` | integer | default 50, max 500 |

#### Response 200

```json
{
  "sessions": [
    {
      "session_id": "uuid",
      "case_type": "W.P.(C)",
      "case_number": "1234",
      "year": 2024,
      "status": "pending_captcha",
      "created_at": "RFC3339",
      "captcha_expires_at": "RFC3339",
      "session_expires_at": "RFC3339",
      "attempts_used": 0
    }
  ],
  "count": 17
}
```

### 6.2 GET /api/v1/admin/failures

Recent failed requests (for ops + parser regression triage).

#### Query params

| Param | Type | Notes |
|---|---|---|
| `since` | string (RFC 3339) | optional; default = now - 24h |
| `code` | string | optional; filter by error code |
| `limit` | integer | default 100, max 1000 |

#### Response 200

```json
{
  "failures": [
    {
      "request_id": "uuid",
      "occurred_at": "RFC3339",
      "endpoint": "/api/v1/search/submit",
      "code": "court_error",
      "upstream_status": [503, 502],
      "case_id_hash": "sha1...",
      "parser_version": 3,
      "raw_html_sampled": false
    }
  ],
  "count": 42
}
```

### 6.4 POST /api/v1/admin/kill-switch

Flip Sneha's outbound kill-switch (`OUTBOUND_FETCH_ENABLED`) at runtime, without a process restart. The flag is process-local — restarting the backend resets it to the value in the env at boot.

#### Auth

| Header | Required | Notes |
|---|---|---|
| `X-Admin-Secret` | yes | constant-time compare against `ADMIN_SHARED_SECRET` env var |

#### Request body

```json
{ "enabled": true }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `enabled` | boolean | yes (or `outbound_fetch_enabled`) | target value of the kill-switch |
| `outbound_fetch_enabled` | boolean | optional alias | accepted as a verbose synonym for `enabled`; if both supplied, `outbound_fetch_enabled` wins |

#### Response 200

```json
{
  "outbound_fetch_enabled": false,
  "note": "outbound_fetch_enabled: true -> false"
}
```

| Field | Type | Notes |
|---|---|---|
| `outbound_fetch_enabled` | boolean | the **new** effective value after the flip |
| `note` | string | human-readable transition (`previous -> new`); for ops audit logs |

#### Status codes

| Status | Code | Meaning |
|---|---|---|
| 200 | — | flag updated; body reflects new value |
| 400 | `invalid_request` | neither `enabled` nor `outbound_fetch_enabled` provided, or non-boolean |
| 401 | `unauthorized` | missing or wrong `X-Admin-Secret` |
| 422 | `invalid_request` | body is not valid JSON / shape (pydantic envelope) |

#### Side-effect contract

When `enabled=false`, every subsequent `POST /api/v1/search/init` (and any other call that would touch the outbound client) returns **`503`** with `error.code = "upstream_blocked"`. In-flight outbound calls are NOT cancelled; the flag is checked at the start of each outbound op.

**State scope:** the flag is held in process memory (`app.runtime_flags`). Restarting the backend resets it to whatever `OUTBOUND_FETCH_ENABLED` is in the environment at boot. Multi-node deploys must coordinate the flip out-of-band (or move the flag to Redis in v2).

---

## 7. Canonical Schemas

### 7.1 `ParsedCase`

Returned by `/search/submit` on `status="success"`. **All clients must treat unknown fields as forward-compatible (ignore, don't crash).**

| Field | Type | Required | Notes |
|---|---|---|---|
| `case_id` | string | yes | canonical id: `f"{case_type}|{case_number}|{year}"` (the literal string, not the hash) |
| `case_type` | string | yes | echoes request |
| `case_number` | string | yes | echoes request |
| `year` | integer | yes | echoes request |
| `parties` | object | yes | `{ petitioner: string[], respondent: string[] }`; each name a free-text string; **never** empty arrays both — at least one side is populated |
| `status` | string \| null | no | upstream "Status" field, e.g. `"Pending"`, `"Disposed"`, `"Reserved for Judgment"` |
| `last_hearing_date` | string (RFC 3339 date) \| null | no | ISO date only, no time |
| `next_hearing_date` | string (RFC 3339 date) \| null | no | |
| `court_no` | string \| null | no | upstream `"Court No."` field |
| `judge_bench` | string \| null | no | upstream bench composition string |
| `orders` | object[] | yes | array (possibly empty) of `{ date: string\|null, title: string, url: string\|null }` |
| `judgments` | object[] | yes | same shape as `orders` |
| `raw_html_hash` | string | yes | sha256 of the upstream HTML for reproducibility |
| `parsed_at` | string (RFC 3339) | yes | server-side parse timestamp |
| `source_url` | string | yes | the upstream URL the user could open directly |
| `parser_version` | integer | yes | parser revision; bumps when selectors change |

#### Nested: `Order` / `Judgment`

| Field | Type | Required |
|---|---|---|
| `date` | string (RFC 3339 date) \| null | no |
| `title` | string | yes |
| `url` | string \| null | no — null when upstream doesn't publish a doc URL |

#### Example

```json
{
  "case_id": "W.P.(C)|1234|2024",
  "case_type": "W.P.(C)",
  "case_number": "1234",
  "year": 2024,
  "parties": {
    "petitioner": ["ACME Industries Pvt Ltd"],
    "respondent": ["Union of India", "Ministry of Commerce"]
  },
  "status": "Pending",
  "last_hearing_date": "2026-04-22",
  "next_hearing_date": "2026-06-10",
  "court_no": "Court No. 12",
  "judge_bench": "Hon'ble Mr. Justice X, Hon'ble Ms. Justice Y",
  "orders": [
    {"date": "2026-04-22", "title": "Interim Order", "url": "https://delhihighcourt.../order/..."}
  ],
  "judgments": [],
  "raw_html_hash": "a3f1...",
  "parsed_at": "2026-05-17T09:42:11Z",
  "source_url": "https://delhihighcourt.nic.in/case-status?...",
  "parser_version": 3
}
```

### 7.2 Error codes (enum, stable)

| Code | HTTP | Retryable | Meaning |
|---|---|---|---|
| `invalid_request` | 400 | false | validation failed |
| `session_not_found` | 404 | false | session_id unknown / expired |
| `in_progress` | 409 | true (after delay) | another submit running |
| `session_consumed` | 410 | false | session already produced a result |
| `rate_limited` | 429 | true (honor Retry-After) | inbound rate-limit exceeded |
| `court_error` | 503 | true | upstream errored after retries |
| `captcha_unavailable` | 503 | true | CAPTCHA image fetch failed |
| `upstream_blocked` | 503 | false (auto-retry only after `Retry-After`) | circuit breaker open |
| `session_store_down` | 503 | true | internal store unreachable |
| `internal_error` | 500 | false | unexpected; investigate via request_id |
| `unauthorized` | 401 | false | admin endpoints, bad/missing secret |

Body-level (`status` field on 200) values:

| Status | Meaning |
|---|---|
| `success` | parsed case returned |
| `captcha_failed` | upstream said wrong CAPTCHA |
| `expired` | CAPTCHA/upstream-session expired |
| `not_found` | upstream confirmed no such case |
| `court_error` | upstream errored mid-submit (returned as 200 body so frontend can branch cleanly) |

### 7.3 `session_id` format (LOCKED)

`session_id` is a **canonical RFC 4122 dashed UUID v4** string,
lowercase, e.g. `6f89d33b-faf8-4834-8959-609e1a6dcabb` (36 chars,
including the four `-` separators).

This is the **normative** wire format for every appearance of
`session_id` in this contract:

- `POST /api/v1/search/init` response body
- `POST /api/v1/search/submit` request body
- `GET  /api/v1/search/{session_id}/refresh-captcha` path param
- `GET  /api/v1/admin/sessions` response rows

Servers MUST emit, and clients MAY validate against, the regex
`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (the
Pydantic `UUID` type and the JavaScript `crypto.randomUUID()` output
both satisfy this).

**Why this is locked:** This shape was the second contract-drift bug
(see DRIFT-001 — `parse_confidence` vs `parser_degraded`). The 2026-05-17
founder demo (docs/DEMO-FEEDBACK.md item #4) caught the backend emitting
dashless 32-char hex (`uuid.uuid4().hex`) while the frontend Zod schema
required dashed UUID. The fix is on the backend — it now generates and
validates the dashed form — and the spec is fixed here so a future
change to either side fails loudly instead of silently.

Backwards-compatible relaxations on the **client validator** side
(e.g. `min(8).max(64)` in Zod) are tolerated as defensive belt-and-
braces, but the **server** is the source of truth for the canonical
shape.

---

## 8. Security notes (inline, for Sneha)

- `X-Admin-Secret` is **MVP-only**. Document as "to be replaced by SSO/OIDC before any external deployment".
- `ParsedCase` is treated as public data (court records are public), but `raw_html_hash` and `source_url` must not leak any session-specific tokens. The parser strips query-string tokens before emitting `source_url`.
- Upstream cookies, CSRF tokens, and CAPTCHA images are **never** logged. Logging middleware has an explicit denylist on `cookie`, `set-cookie`, `csrf*`, `captcha*` keys.
- `case_id` may be considered semi-sensitive in some contexts (litigant privacy) — we cache it but admin endpoints expose only the **hash**, not the raw id. Confirm with Sneha.

---

## 9. Open contract questions (for human architect)

1. Should `/search/submit` also accept a fresh `case_type/case_number/year` so the user can correct a typo without restarting? (Pro: better UX. Con: complicates state machine; the upstream form requires re-submission anyway.) **Recommendation: no, keep submit narrow; let frontend call /init again.**
2. Should `ParsedCase.orders` and `judgments` include a `document_hash` for tamper-evident references? (Pro: defensible if a doc is later changed upstream. Con: requires fetching the PDF for hash, doubles upstream load.) **Recommendation: defer to v2.**
3. Pagination on `/admin/failures` — cursor or offset? **Recommendation: cursor on `occurred_at desc, request_id`; offset is fine for MVP scale.**
