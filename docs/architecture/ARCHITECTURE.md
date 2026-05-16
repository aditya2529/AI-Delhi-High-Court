# Delhi HC Case Tracker — System Architecture (MVP)

**Status:** Draft v0.1 · **Owner:** Arnav (Architecture) · **Last updated:** 2026-05-17
**Audience:** Engineering team (Arjun/backend, Sara/frontend, Rohit/DB, Sneha/sec, Maya/QA)

---

## 1. Executive Overview

The Delhi HC Case Tracker is a **thin workflow-simplification layer** over the Delhi High Court's public case-status page. It does not bypass authentication, does not solve CAPTCHAs algorithmically, and does not scrape at high frequency. A user enters a case identifier; our backend opens an HTTP session against the court site on their behalf, relays the court's image CAPTCHA to the user's browser, accepts the typed answer, submits the form using the **same upstream session**, parses the returned HTML into a stable `ParsedCase` JSON shape, and returns it. All upstream cookies and CSRF tokens stay server-side; the client only ever holds an opaque session ID. The MVP is single-node (FastAPI + SQLite + in-process session store with optional Redis), and is engineered so that the only horizontal-scale blocker is the session store — swappable to Redis without code changes outside one module.

---

## 2. Component Diagram (ASCII)

```
                   ┌──────────────────────────────────────────────────┐
                   │                  User's Browser                  │
                   │  Next.js 14 (App Router, TS, React 18, RSC)      │
                   └────────────┬─────────────────────────────────────┘
                                │  HTTPS · JSON · opaque session_id
                                │  (no upstream cookies ever exposed)
                                ▼
              ┌────────────────────────────────────────────────────┐
              │              FastAPI Edge (Python 3.11)            │
              │   /api/v1/search/* · /api/v1/health · /admin/*     │
              │   middlewares: rate-limit, request-id, CORS,       │
              │                error-envelope, admin-secret-gate   │
              └──┬─────────────────┬─────────────────┬─────────────┘
                 │                 │                 │
                 ▼                 ▼                 ▼
        ┌───────────────┐  ┌────────────────┐  ┌────────────────────┐
        │ Session Store │  │ Court Client   │  │  Result Cache /    │
        │ (Redis OR     │  │ (httpx.AsyncCli│  │  Persistence (DB)  │
        │  SQLite-back  │  │  ent, cookie-  │  │  SQLite (MVP) →    │
        │  ed kv)       │  │  jar, retries) │  │  Postgres (v2)     │
        │ TTL 10 min    │  │ outbound rate- │  │  parsed_case,      │
        │ key:session_id│  │ limit, backoff │  │  failure_log,      │
        └───────┬───────┘  └────────┬───────┘  │  parser_version    │
                │                   │          └──────────┬─────────┘
                │                   ▼                     │
                │          ┌────────────────────┐         │
                │          │ Delhi HC Public    │         │
                │          │ Case-Status Site   │         │
                │          │ (upstream, HTML +  │         │
                │          │  CAPTCHA image)    │         │
                │          └────────┬───────────┘         │
                │                   │                     │
                │                   ▼                     │
                │          ┌────────────────────┐         │
                └─────────►│ HTML Parser        │◄────────┘
                           │ BS4 + lxml         │
                           │ layered selectors  │
                           │ parser_version=N   │
                           └────────┬───────────┘
                                    │ ParsedCase JSON
                                    ▼
                              (back to FastAPI Edge → client)
```

---

## 3. Component Responsibilities

### 3.1 Next.js Frontend
**Owns:** form UX, CAPTCHA image rendering (data-URL from b64), countdown timer for CAPTCHA freshness, optimistic state, simplified ParsedCase view, error banners keyed by `error.code`.
**Does NOT own:** any upstream session, any cookie, any retry logic against the court site, any CAPTCHA solving, any HTML parsing.

### 3.2 FastAPI Edge
**Owns:** request validation (pydantic), session-id minting, middleware stack (rate-limit, request-id, CORS, error envelope, admin secret gate), JSON response shaping, OpenAPI surface.
**Does NOT own:** direct HTTP to the court site (delegates to Court Client), parsing (delegates to Parser), schema migrations.

### 3.3 Session Store
**Owns:** mapping `session_id → { upstream_cookies, csrf_token, form_state, captcha_fetched_at, captcha_expires_at, court_view_state, status }`. TTL 10 min sliding.
**Does NOT own:** parsed results, audit log, user identity (none in MVP).
**Interface:** `get(sid)`, `put(sid, state, ttl)`, `touch(sid)`, `delete(sid)`. Backed by an abstract `SessionStore` protocol. MVP impl: SQLite-backed kv (single file, WAL mode). v2 impl: Redis.

### 3.4 Court Client (outbound)
**Owns:** httpx.AsyncClient per session (cookie jar isolation), upstream rate-limit token bucket (default **2 req/sec global**, **1 req/sec per upstream path**, TO BE VERIFIED IN SPIKE), retry with exponential backoff + jitter (max 3 attempts on 5xx/network), polite User-Agent string, timeout policy (connect 5s, read 15s).
**Does NOT own:** business logic, parsing, session lifecycle.

### 3.5 Parser
**Owns:** mapping court-site HTML → `ParsedCase`. Versioned (`parser_version` field). Defensive: CSS selector first, XPath fallback, regex last; on total failure returns `{parsed: false, raw_html_hash, source_url}` rather than throwing.
**Does NOT own:** HTTP, retry, caching.

### 3.6 Result Cache / Persistence
**Owns:** `parsed_case` table (cache of successful parses, keyed by `case_id` = `case_type|case_number|year`, TTL 6 h), `failure_log` (last 30 days for ops), `parser_version` registry.
**Does NOT own:** sessions, CAPTCHA images, raw HTML beyond a 30-day rolling sample for parser regression.

---

## 4. Happy-Path Data Flow

1. Client → `POST /api/v1/search/init { case_type, case_number, year }`.
2. Edge validates, mints `session_id` (uuid4), inserts empty state into Session Store with TTL 10 min.
3. Court Client (under rate-limit) GETs the court case-status page, captures cookies + CSRF/state tokens, then GETs the CAPTCHA image URL using the **same cookie jar**.
4. Edge persists `{cookies, csrf_token, form_state, captcha_expires_at = now + 90s}` into Session Store. (90s is conservative; TO BE VERIFIED IN SPIKE.)
5. Edge returns `{session_id, captcha_image_b64, captcha_expires_at}` to client.
6. User types CAPTCHA → client → `POST /api/v1/search/submit { session_id, captcha_text }`.
7. Edge loads session, calls Court Client which POSTs the form (case fields + CAPTCHA + CSRF + cookies). On 200, Parser converts HTML → `ParsedCase`.
8. Edge writes `parsed_case` row (idempotent on `case_id`), deletes the Session Store entry, returns `{status: 'success', result: ParsedCase}`.

---

## 5. Concurrency Model

| Concern | MVP target | Bottleneck |
|---|---|---|
| Concurrent in-flight sessions | 50 | Outbound rate-limit to court site (2 req/s global) |
| Median user CAPTCHA-type time | ~15 s | Human, not us |
| p95 CAPTCHA-type time | ~60 s | Human |
| Outbound HTTP p95 (court site) | unknown — assume 3–8 s | Court infra (TO BE VERIFIED IN SPIKE) |
| FastAPI worker model | 1 uvicorn process · 2 workers · async | Single-node only in MVP |

**Why this works:** the dominant time component is the human typing the CAPTCHA, not our compute. While the user types, the FastAPI event loop is idle for that session — async httpx lets one worker hold dozens of sessions cheaply. The true ceiling is the **outbound 2 req/s** budget against the court site, *not* our process. At 2 req/s × avg 2 upstream calls per session ≈ **~60 sessions/min sustained**; bursty up to 120/min before rate-limit blocks.

**Bottleneck order at 10x load (target = 500 sessions/min):**
1. Outbound rate-limit budget — must negotiate w/ court site or queue.
2. Session Store contention — SQLite write-lock under concurrent puts → switch to Redis.
3. FastAPI single-node — add LB + N workers; pin session affinity OR move session to Redis.

---

## 6. Caching Strategy

| What | Where | TTL | Why |
|---|---|---|---|
| Parsed `ParsedCase` by `case_id` | DB `parsed_case` | 6 h | Court data changes slowly; cuts upstream load on repeat queries |
| Session state | Session Store | 10 min sliding | Long enough for slow typists, short enough to bound memory |
| CAPTCHA image bytes | **NOT cached** | n/a | One-shot, tied to session; caching is a correctness bug |
| Upstream cookies / CSRF | Session Store only | session TTL | Security: never on client, never in logs |
| Raw HTML | Sampled 1% to `failure_log` for regression | 30 d | Parser change-detection only |
| `parser_version` registry | DB | permanent | Audit + replay |

Cache key for parsed results: `sha1(f"{case_type}|{case_number}|{year}".lower())`. Cache **bypass** flag: `?fresh=1` query param on init for ops use (rate-limited separately).

---

## 7. Failure Modes (architectural concerns)

| # | Failure | Detection | Mitigation |
|---|---|---|---|
| F1 | Court site 5xx / timeout on init | httpx exception or status ≥ 500 | Court Client retries 3× w/ expo backoff + jitter (200ms→1s→4s). Final: return `court_error` w/ retryable=true. |
| F2 | CAPTCHA image fetch fails (200 but empty / wrong MIME) | content-length < 200 OR MIME not image/* | Treat as F1; surface as `captcha_unavailable`. |
| F3 | User takes > captcha TTL to submit | `now > captcha_expires_at` at submit | Return `expired` with `retry_url` pointing to refresh endpoint. **Do NOT auto-retry** — frontend prompts user. |
| F4 | CAPTCHA token expired upstream but our TTL didn't catch it | upstream returns the "wrong CAPTCHA" page | Parser detects sentinel string ("Invalid Captcha") → return `captcha_failed`, decrement attempts; after 3 attempts force `expired` + new fetch. |
| F5 | Parser breaks (court HTML layout changed) | Parser returns `parsed=false` | Log raw HTML sample + bump alert; return `{status: 'success', result: partial, parser_degraded: true, source_url}` so user still gets the upstream link. |
| F6 | Session store unavailable | put/get raises | Edge returns 503 `session_store_down`, retryable=true. Health probe flips. |
| F7 | Concurrent submit on same session_id | second submit while first in flight | Optimistic lock on session row (`status='submitting'`); second request gets 409 `in_progress`. |
| F8 | Browser tab closes mid-flow | no detection — TTL cleanup | Session GC runs every 60s, deletes entries past TTL. |
| F9 | Our rate-limit exhausted | token bucket returns 0 | Queue with 5s max wait; if still 0, return 429 with `Retry-After`. |
| F10 | Court site detects/blocks our IP | sudden run of 403s | Circuit-breaker: open after 5 consecutive 403s, all requests fail-fast with `upstream_blocked` for 5 min. Page on-call. |

---

## 8. Scalability Path

**Phase 0 (today, MVP):** Single VM. FastAPI (2 workers) + SQLite + in-process+SQLite-backed session store. Handles ~60 sessions/min sustained. Sufficient for pilot.

**Phase 1 (post-pilot, ~500 sessions/min):**
- Swap Session Store → Redis (already abstracted behind `SessionStore` protocol).
- Swap SQLite → Postgres for `parsed_case` + `failure_log`.
- Two FastAPI nodes behind a load balancer. **Session affinity not required** once Redis is in.
- Outbound rate-limit becomes a **distributed token bucket** in Redis (Lua script).

**Phase 2 (only if upstream tolerates, ~5k sessions/min):**
- Negotiate with court IT for an allowlisted partner channel (formal MoU). Without this, we will hit upstream rate-limits regardless of our scaling.
- Move parsing to a worker pool (Celery/Arq) if parser CPU > 30% of request budget.
- Read-replica for `parsed_case` reads (cache hits).

**Do not build any of Phase 1/2 in MVP.** The point of the abstractions is so we can.

---

## 9. NFRs (target)

| NFR | Target (MVP) | Notes |
|---|---|---|
| Availability | 99.0% (single VM) | 99.9% requires Phase 1 |
| p95 latency `/search/init` | < 2.5s | excludes court site latency tail — TO BE VERIFIED IN SPIKE |
| p95 latency `/search/submit` | < 4.0s | dominated by upstream POST + parse |
| Parser success rate | > 98% on known layouts | golden fixtures gate CI |
| Outbound politeness | ≤ 2 req/s global to court site | hard cap |
| Data retention | sessions 10 min · parsed_case 6 h cache · failure_log 30 d | |

---

## 10. Cross-team flags

- **→ Rohit:** the only join we issue is `parsed_case` lookup by `case_id` hash. No high-volume tables yet, but `failure_log` will need a `created_at` index for the admin endpoint. Confirm.
- **→ Sneha:** new auth boundary on `/api/v1/admin/*` (shared secret header — explicitly **NOT production-grade**, MVP-only; needs SSO/OIDC by v2). Also: upstream cookies are session-secret material — confirm storage requirements (at-rest encryption on session store?).
- **→ Arjun:** the Court Client + Session Store interfaces are the contract; everything else is implementation. Do not let HTTP details leak above Court Client.
- **→ Sara:** the only contract you bind to is `docs/api/API-CONTRACT.md`. Anything not in there is not promised.

---

## 11. Open Questions (block implementation)

1. **Court site CAPTCHA TTL** — we assume 90s; actual value unknown. Spike must measure.
2. **Court site session cookie names + CSRF mechanism** — unknown. Spike must map.
3. **Court site rate-limit thresholds** — we self-cap at 2 req/s, but their threshold may be higher or lower. Spike must probe (carefully).
