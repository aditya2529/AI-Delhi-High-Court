# Delhi HC Case Tracker — Executive Summary

> *Drafted 2026-05-17 by the Scrum Team: **Priya** (PM) · **Arnav** (Architecture) · **Rohit** (Database) · **Sneha** (Legal/Security)*

---

## 1. The product, in 150 words

Lawyers in Delhi receive daily calls from clients asking for the latest update on their cases. The court has a public case-status search, but its UX is poor enough that non-technical users routinely fail to use it: too many fields, an opaque image CAPTCHA, and an unstructured result page.

**Delhi HC Case Tracker** is a thin web wrapper that does the form-filling, session management, CAPTCHA presentation, and result-parsing for the user, in a single mobile-friendly screen. The user supplies case-type, case-number, year, and solves the CAPTCHA themselves. The backend handles the rest.

We do **not** bypass any court security control. We do **not** offer legal advice or case prediction. We do **not** store user PII. We **do** rate-limit ourselves, respect `robots.txt`, ship a global kill switch, and surface the court's own URL on every result so the user can always verify the source.

---

## 2. Feasibility verdict

**🟡 Approved with conditions.** This product is technically feasible and legally defensible *contingent on five gates clearing in Phase 0.* No build work past the spike unless and until all five close. Three of the five are external to engineering.

| Gate | Owner | Closes when... |
|---|---|---|
| **G1 — Spike: session + CAPTCHA mechanics mapped** | Arnav + Arjun | A 2-day reconnaissance produces a memo describing the court's actual cookie names, CSRF/state field, CAPTCHA TTL, and form structure. Until this is known, the [court_client](../backend/app/clients/court_client.py) interface cannot be finalised. |
| **G2 — ToS + robots.txt review** | Sneha + counsel | A manual review of the Delhi HC site's Terms of Use and `robots.txt` confirms programmatic session creation (user-solves-CAPTCHA) is permitted. If forbidden → product killed before launch. |
| **G3 — DPDPA classification confirmed** | Counsel | Qualified Indian counsel signs off that data published by the Court under the open-court principle is *not* personal data we process as a Data Fiduciary under DPDPA §3(c)(ii). Sneha's engineering interpretation supports this, but it is the load-bearing legal assumption of the MVP. |
| **G4 — Parser hits ≥80% of 20 real result pages** | Arjun + Maya | Phase-0 spike captures 20 representative result HTMLs (pending, disposed, multi-petitioner, no-orders, edge cases); parser v0 extracts core fields from ≥16 of them. |
| **G5 — 5-10 friendly-lawyer testers lined up** | Owner | Real users committed to Phase-1 pilot before week 4. |

Estimated cost of the Phase-0 spike: **8-10 engineer-days** + 1 day of counsel time. Estimated cost of failing any gate at this stage: ~₹50k of engineer time, zero brand damage, zero court-relationship damage.

---

## 3. What's already drafted

Every detail below has a corresponding doc in `docs/`. **Read in this order:**

| # | Doc | Owner | What it covers |
|---|---|---|---|
| 1 | [prd/PRD.md](prd/PRD.md) | Priya | Personas, JTBD, success metrics, MVP scope, edge cases, product risks, phased roadmap, open questions |
| 2 | [prd/user-stories.md](prd/user-stories.md) | Priya | 11 stories (42 points), 3 sprints, acceptance criteria in Given/When/Then |
| 3 | [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) | Arnav | Component diagram, concurrency model, caching, failure modes, scalability path |
| 4 | [architecture/SEQUENCE-DIAGRAMS.md](architecture/SEQUENCE-DIAGRAMS.md) | Arnav | Happy path, CAPTCHA-expired, court-site-failure |
| 5 | [architecture/STRATEGIES.md](architecture/STRATEGIES.md) | Arnav | Session, CAPTCHA, parsing, error-handling strategies |
| 6 | [architecture/DATA-MODEL.md](architecture/DATA-MODEL.md) | Rohit | Tables, columns, indexes, retention policies, ER diagram |
| 7 | [api/API-CONTRACT.md](api/API-CONTRACT.md) | Arnav | OpenAPI-style spec for all public + admin endpoints |
| 8 | [decisions/ADR-001.md](decisions/ADR-001.md) | Arnav | FastAPI vs Spring Boot |
| 9 | [decisions/ADR-002.md](decisions/ADR-002.md) | Arnav | SQLite-now, Postgres-ready |
| 10 | [decisions/ADR-003.md](decisions/ADR-003.md) | Arnav | Human-in-the-loop CAPTCHA (no model solver) |
| 11 | [legal/LEGAL-COMPLIANCE.md](legal/LEGAL-COMPLIANCE.md) | Sneha | IT Act 2000, DPDPA 2023, Copyright 1957, robots.txt, ToS, take-down process, kill switch |
| 12 | [legal/PRIVACY-NOTICE.md](legal/PRIVACY-NOTICE.md) | Sneha | User-facing privacy notice (`/privacy`) |
| 13 | [legal/SECURITY-CONSIDERATIONS.md](legal/SECURITY-CONSIDERATIONS.md) | Sneha | OWASP-shaped checklist for the MVP |

Plus, an Alembic 0001 migration + 7 SQLAlchemy 2.x model files (`backend/app/models/*.py`) — see [DATA-MODEL.md](architecture/DATA-MODEL.md).

---

## 4. Engineering backlog (sequenced, Phase 0 → Phase 1 → Phase 2)

### Phase 0 — Feasibility spike (1 week)

| ID | Task | Owner | Done when... |
|---|---|---|---|
| **P0-1** | Manual reconnaissance against the court site from a single workstation | Arnav, 2 days | Memo describing cookie names, CSRF/state field, CAPTCHA TTL, request sequence — see Arnav's spike plan |
| **P0-2** | Capture 20 representative result-page HTMLs as golden fixtures (anonymised) | Arnav + Arjun | Fixtures committed under `parsers/fixtures/sample_responses/` with PII scrubbed |
| **P0-3** | Probe upstream rate limit (0.5 → 2 req/s) and circuit-breaker thresholds | Arnav | Document max safe outbound rate; default rate-limit value updated |
| **P0-4** | Manual ToS + robots.txt review | Sneha | Snapshot saved under `docs/legal/`; pass/fail recommendation to owner |
| **P0-5** | DPDPA classification opinion from counsel | Owner | One-paragraph sign-off in `docs/legal/` confirming "not a Data Fiduciary for open-court data" |
| **P0-6** | Recruit 5-10 lawyer testers for Phase-1 pilot | Owner | Names + commit dates collected |

**Phase 0 exit:** all five G-gates closed. Phase 1 begins on owner go.

### Phase 1 — MVP build (3 weeks)

Sprint 1 (week 2) — *Backend session + CAPTCHA round-trip*
| ID | Story (see [user-stories.md](prd/user-stories.md)) | Owner | Pts |
|---|---|---|---|
| S1.1 | `POST /search/init` — open session, fetch CAPTCHA | Arjun | 5 |
| S1.2 | `POST /search/submit` — submit + parse result | Arjun | 8 |
| S1.3 | `GET /search/{id}/refresh-captcha` — refresh without losing state | Arjun | 3 |
| S1.4 | Parser v0 — pass 16/20 golden fixtures | Arjun + Maya | 5 |
| S1.5 | Outbound rate-limit + circuit breaker + SSRF allowlist | Arjun + Sneha | 3 |
| S1.6 | Kill-switch endpoint + env-var gate on every outbound call | Arjun + Sneha | 2 |

Sprint 2 (week 3) — *Frontend search flow + admin*
| ID | Story | Owner | Pts |
|---|---|---|---|
| S2.1 | SearchFlow page — form + CAPTCHA + result render | Sara | 5 |
| S2.2 | Mobile-responsive design (320px → 1440px) | Sara | 3 |
| S2.3 | Disclaimer banner + privacy notice page | Sara | 2 |
| S2.4 | Admin observability dashboard (read-only) | Sara + Arjun | 3 |

Sprint 3 (week 4) — *Hardening + pilot*
| ID | Story | Owner | Pts |
|---|---|---|---|
| S3.1 | Integration tests for full search flow against fixture-driven `FakeCourtClient` | Maya | 5 |
| S3.2 | E2E tests with Playwright on mobile + desktop viewports | Maya | 3 |
| S3.3 | Smoke + load tests (50 concurrent searches) | Maya | 2 |
| S3.4 | Production deploy (single VM + nginx) | Arjun | 3 |
| S3.5 | Pilot with 5-10 lawyers; collect feedback + metric data | Priya + Owner | — |
| S3.6 | Raj's code review on the full PR set before pilot | Raj | — |

**Phase 1 exit (success gate, per Priya's PRD):** ≥70% of pilot searches return a parsed result on first CAPTCHA attempt; median time-to-result ≤12s; ≥50 weekly-active-users by week 4; all three hold for 7 consecutive days before Phase 2 unlocks.

### Phase 2 — Post-MVP (only if Phase 1 succeeds)

Strict order, owner-approved one at a time:
1. **Saved searches + email/WhatsApp notifications on hearing changes** (the engagement multiplier per Priya)
2. **Parser-regression dashboard** — alert when parse_confidence drops below threshold for >5% of requests
3. **PostgreSQL migration** when single-node SQLite becomes the bottleneck
4. **Multi-court roadmap** — second court added with a pluggable `CourtClient` interface
5. **Optional user accounts** (only if user research demands it)

---

## 5. Risk register (consolidated)

Risks merged across PRD, Architecture, Legal, and DB workstreams. Severity × Likelihood ranked top to bottom.

| # | Risk | Severity | Likelihood | Owner | Mitigation |
|---|---|---|---|---|---|
| R1 | DPDPA classification flipped by counsel — we're a Data Fiduciary for case data | Critical | Medium | Sneha + Owner | Gate G3 in Phase 0. Kill product if confirmed; pivot to user-fetches-with-our-help model. |
| R2 | Court site changes HTML / CAPTCHA scheme overnight | High | High (this happens) | Arjun + Maya | Versioned parser, golden fixtures in CI, 2 eng-days/month maintenance budget, raw_html_hash on every failure for fast diagnosis. |
| R3 | Court's ToS forbids programmatic access | Critical | Low-Medium | Sneha + Counsel | Gate G2. Kill switch ready. Take-down SLA documented. |
| R4 | Court applies IP-level rate limiting; we get blocked | High | Medium | Arjun | Polite default (≤1 req/3s). Circuit breaker. IP-pool plan for v2 (NOT MVP). |
| R5 | CAPTCHA token rotates faster than we assume; user-friendly refresh required | Medium | Medium | Arnav | `/refresh-captcha` already in API contract. UX hint: "CAPTCHA stale, click to refresh." |
| R6 | Parsing fails silently on some real-world case types (e.g. composite benches) | Medium | High | Arjun | Graceful failure: return raw_html_hash + source_url; frontend "couldn't read — open court site" link. parse_confidence telemetry. |
| R7 | User trust low because we're unofficial | Medium | Medium | Priya + Sara | Visible "Unofficial · Court page is authoritative" badge in every viewport. Every result links to court source. |
| R8 | Single-node SQLite can't handle pilot traffic | Low | Low (pilot <100 users) | Rohit | Migration path to Postgres documented in [ADR-002](decisions/ADR-002.md). |
| R9 | SSRF / open-proxy exploitation via crafted case numbers | High | Low | Sneha + Arjun | Hostname allowlist hardcoded in config. Outbound URL validated before every request. |
| R10 | XSS via parsed court HTML being innerHTML'd into our UI | High | Low | Sneha + Sara | Frontend NEVER renders raw HTML. Only structured ParsedCase JSON. React's default escaping. |
| R11 | Logs leak raw CAPTCHA text or full court session cookies | Medium | Medium | Sneha + Arjun | Log redaction — first 8 chars + length for debugging only. |
| R12 | CAPTCHA-solving feature creep — someone proposes OCR to "help" | Medium | Medium | Owner | [ADR-003](decisions/ADR-003.md) is a hard line. Reject any PR that adds a solver. |

---

## 6. Open questions for the owner (deduplicated across the team)

These block decisions, not implementation:

1. **DPDPA sign-off** — get qualified Indian counsel to write a one-paragraph opinion on whether case data published by the Court under the open-court principle counts as personal data we process as a Data Fiduciary. *(R1, G3 — Sneha)*
2. **ToS + robots.txt review** — manual review of `delhihighcourt.nic.in` ToS and `robots.txt` content. Snapshot, archive, and recommend pass/fail. *(R3, G2 — Sneha)*
3. **Historical court-site changes** — how often (rough cadence) has the Delhi HC site changed its HTML or CAPTCHA scheme in the last 24 months? Drives R2 risk weight and parser-maintenance budget. *(Priya)*
4. **Pilot testers lined up?** — owner needs to confirm 5-10 friendly-lawyer pilot users by end of Phase 0, else the week-4 success metrics aren't achievable. *(G5 — Priya)*
5. **Admin-auth boundary** — does the pilot ship with a shared-secret header on `/admin/*` (Sneha approved, MVP-only), or do we need OIDC/SAML before any non-localhost deploy? *(Arnav + Sneha)*
6. **Hosting venue** — single VM (₹600-1500/month) is fine for pilot. Which provider, and who owns the DNS + TLS cert? *(Owner)*
7. **Take-down contact** — single email address published in the disclaimer so the court can reach the owner in 24 hrs if they object. Owner needs to commit a real address. *(Sneha)*

---

## 7. Technical spike plan — what we do in week 1

Per Arnav's recommendation, the spike is a strict 2-day, single-workstation effort. Outputs land in `docs/architecture/SPIKE-REPORT.md` (to be written during Phase 0).

**Day 1 — Mapping**
- Manual walk through the court's case-status form in a browser; capture (a) every cookie set, (b) every CSRF/state hidden field, (c) every form parameter on submit, (d) the CAPTCHA image URL pattern, (e) timing of CAPTCHA refresh, (f) HTTP status codes for each step.
- Repeat with `httpx` from a Python script, replicating the cookie jar manually.
- Compare browser-derived behaviour vs script-derived behaviour. Document differences.

**Day 2 — Stress & samples**
- Pace outbound search requests from 0.5 → 2 req/s. Watch for 429s, 403s, soft-rate-limit responses (interstitials), latency degradation.
- Capture 20 representative result-page HTMLs across pending/disposed/multi-petitioner/no-orders/edge-case states.
- Manually anonymise PII in the fixtures.
- Probe CAPTCHA TTL: hold a session for 30/60/90/180 seconds, then submit. Document the boundary at which it expires upstream.

**Output:** `docs/architecture/SPIKE-REPORT.md` + 20 golden HTML fixtures in `parsers/fixtures/sample_responses/`. The architecture diagrams' three "TO BE VERIFIED IN SPIKE" markers are resolved. Sprint 1 can begin.

If the spike reveals the court uses JS-issued CAPTCHA URLs or session-bound (not image-bound) CAPTCHAs, the architecture changes meaningfully. **Do not start Sprint 1 until the spike report is reviewed and the architecture is updated.**

---

## 8. Folder structure (top-level recap)

```
D:\Projects\AI Delhi High Court\
├── .env.example                       ← every env var documented
├── .gitignore                         ← secrets, node_modules, .venv, *.db
├── README.md                          ← orientation
├── backend/                           ← FastAPI app + Alembic migrations
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_initial_schema.py
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/routes/{health,search,admin}.py
│   │   ├── clients/court_client.py
│   │   ├── models/{search_request,parsed_case,case_party,...}.py
│   │   ├── parsers/case_parser.py
│   │   ├── sessions/store.py
│   │   └── workers/, schemas/, middleware/, utils/, services/
│   ├── tests/{unit,integration,fixtures}/
│   └── requirements.txt
├── frontend/                          ← Next.js (App Router)
│   ├── package.json, tsconfig.json, next.config.js
│   └── src/
│       ├── app/{layout,page}.tsx + globals.css
│       └── components/forms/SearchFlow.tsx
├── parsers/
│   ├── html/                          ← parser implementations
│   └── fixtures/sample_responses/     ← golden HTML fixtures (post-spike)
├── workers/                           ← empty in MVP — future background jobs
├── infrastructure/
│   ├── docker-compose.yml
│   ├── docker/{Dockerfile.backend,Dockerfile.frontend}
│   ├── nginx/                         ← reverse-proxy + TLS config (Phase 1 deploy)
│   └── terraform/                     ← IaC (Phase 2+)
├── scripts/
│   ├── dev/{setup.ps1,setup.sh}
│   └── db/
├── config/{development,staging,production}/
├── logs/{backend,workers}/
├── tests/{e2e,smoke,load}/
├── docs/                              ← ALL the deliverables (see §3)
└── .github/workflows/ci.yml
```

Empty subdirectories are intentional — they're claims about where the relevant code will land, so the structure is self-documenting from day one.

---

## 9. Recommended environment variables (canonical list)

Full source: [.env.example](../.env.example). Highlights:

| Var | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | dev / staging / production |
| `DATABASE_URL` | `sqlite+aiosqlite:///./backend/data/dhc.db` | SQLite for MVP; swap to `postgresql+asyncpg://...` for v2 |
| `SESSION_BACKEND` | `memory` | `memory` or `redis`; production uses Redis |
| `SESSION_TTL_SECONDS` | `600` | server-side session lifetime |
| `DHC_BASE_URL` | `https://delhihighcourt.nic.in` | verify exact host in spike |
| `DHC_OUTBOUND_RATE_LIMIT_PER_SEC` | `0.33` | polite client: ≤ 1 search per 3s |
| `DHC_RESPECT_ROBOTS_TXT` | `true` | refuse disallowed paths |
| `DHC_HOSTNAME_ALLOWLIST` | `delhihighcourt.nic.in` | SSRF guard — pinned host |
| `OUTBOUND_FETCH_ENABLED` | `true` | **Sneha's kill switch** — flip to `false` to halt all outbound calls in <5 min |
| `PARSED_CASE_CACHE_TTL_SECONDS` | `86400` | 24h cache on parsed results |
| `ADMIN_SHARED_SECRET` | `change-me-before-deploy` | gate on `/admin/*` |
| `SENTRY_DSN` | `""` | optional error tracking |

---

## 10. Local development setup

1. **Install prerequisites**: Python 3.11+, Node 20+, Docker (optional but recommended).
2. **Clone + setup**: `./scripts/dev/setup.sh` (Unix) or `.\scripts\dev\setup.ps1` (Windows). This creates `.venv`, installs Python + npm deps, copies `.env.example` → `.env`, and runs Alembic to create the SQLite DB.
3. **Run** (two terminals, or `docker compose` as in the README):
   - Backend: `backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend`
   - Frontend: `cd frontend && npm run dev`
4. **Visit**: http://localhost:3000 (frontend) · http://localhost:8000/api/v1/openapi.json (backend OpenAPI)

---

## 11. Success criteria — when do we declare MVP success?

Per Priya's PRD (verbatim, owner-approved): the MVP is successful if all three hold for **7 consecutive days** by the end of week 4:

1. ≥**70%** of pilot searches return a parsed result on the **first CAPTCHA attempt**.
2. **Median time** from "Search" click to result rendered ≤ **12 seconds**.
3. ≥**50 weekly-active-users** drawn from the 5-10 friendly lawyers and their para-legals.

Plus the qualitative gate: at least 3 of the pilot lawyers say, unprompted, that the tool reduced their client-call burden in the past week.

Below threshold on any of the three → Phase 2 does not unlock. We iterate on whichever metric is closest to its target.

---

*End of synthesis. Drill into any single document in the table at §3 for full detail.*
