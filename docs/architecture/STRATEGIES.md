# Delhi HC Case Tracker — Cross-Cutting Strategies

**Status:** Draft v0.1 · **Owner:** Arnav (Architecture) · **Last updated:** 2026-05-17

Four strategies that span components. Each is the **definitive answer** for its concern; if implementation diverges, this doc is updated first.

---

## 1. Session Management Strategy

The session is the **single most important runtime object** in this system. It exists for one reason: the upstream court site has a stateful session (cookies + CSRF + form state) that must be preserved across two of our endpoint calls (`/init` and `/submit`), separated by a human waiting to read a CAPTCHA. Our `session_id` is the handle to that upstream state, held entirely server-side.

**Shape.** A session record contains: `session_id` (uuid4), `created_at`, `case_type`/`case_number`/`year` (echo of the user's input — needed for repeat-form posts and admin observability), `upstream_cookies` (the cookie jar dict), `csrf_token` (or whatever the upstream form's hidden field turns out to be — TO BE VERIFIED IN SPIKE), `captcha_fetched_at`, `captcha_expires_at`, `attempts_used` (0..3), `status` (`pending_captcha` | `submitting` | `consumed` | `expired`), `last_touched_at`. **No PII beyond what the user typed** (which is the case identifier — public information).

**Keying.** Single key: `session_id`. We do **not** key by client IP or browser fingerprint — a user can refresh their tab and lose their session ID; that's acceptable, they simply start over. We never let two browsers share a session because there is no need to.

**TTL.** Sliding TTL of 10 minutes from `last_touched_at`. Any `/refresh-captcha` or successful `/submit` precondition check refreshes the TTL. `captcha_expires_at` is independent and shorter (~90s, TO BE VERIFIED IN SPIKE). Two timers, two failure modes: CAPTCHA expiry → user re-fetches; session expiry → user starts over.

**Storage.** Behind an abstract `SessionStore` protocol with two implementations: `SqliteSessionStore` (MVP, WAL mode, single file `sessions.db`, hot path `SELECT/UPDATE/DELETE` by primary key) and `RedisSessionStore` (Phase 1, `SET sid <json> EX 600`). The protocol exposes `get/put/touch/delete/list_active/gc_expired` — implementation is opaque to callers. Switching is a one-line config change. **No ORM on this path** — it's a kv lookup; SQLAlchemy is overhead we don't need.

**Cleanup.** A background asyncio task runs every 60s, deletes rows where `last_touched_at + ttl < now`. The admin endpoint surfaces the queue depth. We do not rely on the OS or Redis eviction; we explicitly delete so we have an auditable trail.

**Tab-closes-mid-flow.** We have no signal that the browser closed. The session sits idle until TTL expires, then GC removes it. This is intentional — heartbeats add complexity for marginal benefit. The upstream cookie eventually times out on the court side too; we accept a small window where we hold a dead upstream session. The 2 req/s outbound rate-limit guarantees this never balloons.

**Concurrency.** Optimistic lock: `/submit` does `UPDATE sessions SET status='submitting' WHERE session_id=? AND status='pending_captcha'` and proceeds only if rowcount=1. A double-submit gets `409 in_progress`. On completion, we `UPDATE … SET status='consumed'` and queue for deletion (kept 30s for idempotent reads).

**Security.** Cookie jar is **only** in the session store; never logged, never returned in any response (including admin), never written to disk outside the session store. Logging middleware has a denylist on `cookie*`, `csrf*`, `captcha*` keys. At-rest encryption on the session store is a Sneha decision; flag is on.

---

## 2. CAPTCHA Handling Strategy

The CAPTCHA is human-solved (see ADR-003). Our job is to fetch the image bytes from the court site, hand them to the user's browser intact and quickly, and detect when the underlying token has gone stale.

**Fetch.** When `/search/init` runs, Court Client does **two sequential upstream calls** sharing the same `httpx.AsyncClient` (and therefore the same cookie jar): (1) `GET` the case-status form page — this establishes session cookies and exposes a CSRF token plus the CAPTCHA image URL (typically a relative path like `/captcha?_=<rand>`); (2) `GET` the CAPTCHA image URL. The order matters: fetching the image without the form-page cookies will either fail or return a CAPTCHA bound to a different session. Both calls go through the outbound rate-limiter.

**Encode.** The image bytes come back as `image/jpeg` or `image/png` (TO BE VERIFIED IN SPIKE). We base64-encode and ship inside the JSON response: `{captcha_image_b64, captcha_mime}`. The frontend renders via `<img src="data:${mime};base64,${b64}">`. No separate `/captcha.jpg` endpoint — that would either require us to expose the upstream cookies (bad) or stream from server with a separate auth dance (complexity for no gain). One JSON response, one image, one render.

**Freshness.** We assume the upstream CAPTCHA is valid for 90 seconds (TO BE VERIFIED IN SPIKE — could be longer or tied to session, not to image). We store `captcha_fetched_at` and `captcha_expires_at = fetched_at + 90s` and ship `captcha_expires_at` to the client so the UI can show a countdown. The client should refuse to submit if local clock says expired and instead call `/refresh-captcha` proactively.

**Expiry detection.** Three layers, in order:
1. **Client-side timer** — best UX; refuse submit past expiry, auto-call refresh.
2. **Server-side timestamp check** — at `/submit`, if `now > captcha_expires_at`, return `200 {status: "expired", retry_url}` without an upstream call. Saves a wasted CAPTCHA attempt against the court site.
3. **Upstream rejection** — even if both above pass, the court site may still reject (clock skew, our TTL estimate wrong). Parser detects the "Invalid Captcha" sentinel page → return `captcha_failed` and decrement `attempts_used`.

**Refresh.** `/refresh-captcha` does **only step 2** of the original fetch (GET captcha image) reusing the existing cookie jar and CSRF. This is one upstream call, not two, and preserves the form state — the user doesn't have to retype the case fields. After 3 failed CAPTCHA attempts on the same session, we force-refresh the whole session (new `/init`) because the upstream form may have invalidated.

**What we never do.** No CAPTCHA caching (correctness bug — image is one-shot). No OCR. No re-use across sessions. No client-side image storage beyond the in-memory `<img>`.

**Telemetry.** We count `captcha_fetched`, `captcha_submitted`, `captcha_failed`, `captcha_expired_at_server`, `captcha_refresh_requested`. The ratio `captcha_failed / captcha_submitted` is the canonical "user-friendliness" metric — too high means the image is hard to read; too low (suspiciously close to 100%) means OCR is happening somewhere it shouldn't.

---

## 3. Parsing Strategy

The court site's HTML is the most brittle dependency we have. We don't control it, and it will change. Our strategy is **defensive layered extraction** with explicit regression detection.

**Tooling.** BeautifulSoup4 + lxml parser. Not Selenium (no JS execution needed for case-status — TO BE VERIFIED IN SPIKE). Not regex over HTML (banned except as last-resort fallback).

**Layered selectors.** Each field in `ParsedCase` is extracted via a **fallback chain**:
1. **Primary:** CSS selector (e.g., `table#caseDetails tr:nth-child(2) td:nth-child(2)`).
2. **Secondary:** CSS selector with looser anchoring (e.g., `table tr:has(td:contains('Petitioner')) td + td`).
3. **Tertiary:** XPath (for cases where CSS can't express the predicate cleanly).
4. **Quaternary (last resort):** labeled-regex over the page text (e.g., `r'Petitioner\s*:\s*(.+?)\n'`).

Each chain is encoded as a list of `(selector_kind, selector, post_processor)` tuples. The parser tries them in order; first non-empty result wins. Each field knows whether it is **required** (parties — fail the whole parse if missing) or **optional** (court_no, judge_bench — `null` is fine).

**Parser versioning.** A module-level constant `PARSER_VERSION: int`. Every commit that changes selectors bumps it. Emitted on every parsed result so we can correlate cache entries with parser revisions and invalidate stale ones on rollout.

**Golden fixtures + regression detection.** We maintain a directory of `tests/fixtures/court_html/*.html` — real HTML pages captured (with PII scrubbed) for ~20 representative case types/states (pending, disposed, reserved, multi-petitioner, no-orders, no-judgments, etc.). For each fixture, an `expected.json` of the `ParsedCase` we should produce. CI runs the parser against all fixtures on every commit; any diff fails the build. **This is the only way we catch layout changes before users do.**

**Live canary.** In addition to fixtures, a daily scheduled job (Phase 1 — not MVP) runs 5 known-good case lookups end-to-end and alerts if the result diverges from the previous day's parse. MVP substitute: any production parse where `parser_degraded=true` increments a counter that the admin endpoint surfaces.

**Failure handling.** If the required fields can't be extracted:
- If we detected "Invalid Captcha" sentinel → `status: "captcha_failed"`.
- If we detected "No record found" sentinel → `status: "not_found"`.
- Otherwise → `status: "success", parser_degraded: true, result: {case_id, raw_html_hash, source_url, parsed_at, parser_version, ...nulls/empties}`. The user at least gets a clickable upstream link. We log the raw HTML (sampled, with hash) to `failure_log` for manual triage.

**What we don't parse.** Cause list / daily order / interlocutory applications — out of scope for MVP. Just `ParsedCase` as defined. If the page has them, we ignore.

---

## 4. Error Handling Approach

A single, ruthless rule: **the frontend should never have to guess what to do**. Every error response tells it exactly that.

**Envelope.** Defined in `docs/api/API-CONTRACT.md §1.4`. Shape: `{error: {code, message, retryable, hint, request_id}}`. Every non-2xx response. No exceptions, no variants.

**Code taxonomy.** Codes are `snake_case`, stable, enumerated in API-CONTRACT.md §7.2. Categories:
- **Validation** (400 family) — `invalid_request`. Not retryable.
- **State** (404/409/410) — `session_not_found`, `in_progress`, `session_consumed`. Retryability varies; `in_progress` is retryable-after-delay, others are not.
- **Throttling** (429) — `rate_limited`. Retryable with `Retry-After`.
- **Upstream** (503) — `court_error`, `captcha_unavailable`, `upstream_blocked`. First two retryable; `upstream_blocked` only after `Retry-After` (circuit breaker).
- **Internal** (500) — `internal_error`. Not retryable; investigate.

Business-logical outcomes (success / not-found / captcha-failed / expired) are **2xx body-level statuses**, not HTTP errors. The frontend branches on `body.status`, not on HTTP code, for these.

**Retryable vs not.** `retryable: true` means "the client may safely retry this exact request, possibly after waiting." `retryable: false` means "retrying will produce the same result; show the user, don't loop." The frontend MAY honor `retryable=true` with its own backoff but MUST NOT auto-retry `retryable=false`. `Retry-After` (when present) is authoritative for delay.

**Frontend display matrix.**

| Code | UI element | Auto-retry? | User action |
|---|---|---|---|
| `invalid_request` | inline form error | no | fix input |
| `session_not_found` | toast "Session expired, please start over" + redirect to form | no | re-enter case |
| `in_progress` | spinner "Still processing…" | yes (1×, 2s delay) | wait |
| `rate_limited` | banner "Slow down" | yes (honor Retry-After) | wait |
| `court_error` | banner "Court site error" + manual retry button | no (manual) | click retry |
| `captcha_unavailable` | banner "CAPTCHA didn't load" + retry | no (manual) | click retry |
| `upstream_blocked` | banner "Temporarily paused, auto-resumes in X" | no | wait |
| `session_store_down` | full-page "Service is down" | no | retry later |
| `internal_error` | banner "Something went wrong; ref ID shown" + request_id | no | contact support |

**Server-side logging.** Every error logs at appropriate level:
- 4xx → `INFO` (expected, not an alert)
- 503 upstream → `WARN`
- 500 internal → `ERROR` with full stack trace
- Repeated upstream errors → triggers circuit breaker counter, no extra log
- Parser degradation → `WARN` + raw HTML sample (sha256 + ≤1KB head) to `failure_log` table

Logs include: `request_id`, endpoint, `error.code`, `session_id` (when present), `case_id_hash` (never raw case_id at INFO+), upstream status code (when relevant), and elapsed ms. **Never:** cookies, CSRF tokens, captcha bytes, raw case_id.

**Alerts (Phase 1, not MVP):** rates of `court_error`, `parser_degraded`, and `upstream_blocked` over 5-min windows feed dashboards; threshold alerts page on-call. MVP substitute: admin endpoint + manual review.
