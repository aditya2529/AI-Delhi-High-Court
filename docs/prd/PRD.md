# Delhi HC Case Tracker — Product Requirements Document (MVP)

**Document owner:** Priya (Product / BA)
**Status:** Draft v0.1 — pending owner review
**Last updated:** 2026-05-17
**Target launch:** MVP in 4 weeks from kickoff (Phase 1 exit ~2026-06-14)

---

## 1. Executive Summary

Delhi lawyers and paralegals waste hours every week answering repetitive client calls asking "any update on my case?" The Delhi High Court already publishes case status on its public website, but the UX is hostile to non-technical users: cryptic field labels, unclear case-type taxonomy, image CAPTCHA on every query, and result pages dense with legal shorthand. Clients cannot self-serve, so the lawyer becomes a manual proxy.

**What we are building:** A thin, fast web app that wraps the Delhi HC public case-search page. The user enters case type, number, and year; our backend opens a real session with the court site, fetches the CAPTCHA image, displays it to the user, the user solves it, we submit the form in the same session, parse the returned HTML, and render a clean, plain-English summary.

**Audience:** Solo practitioners and small-firm paralegals in Delhi NCR.

**Success in MVP:** >=70% of searches return a correctly parsed result on the first CAPTCHA attempt; median click-to-result under 12s; 50 weekly active users by end of Phase 1.

**Explicitly NOT doing:** AI legal advice, case-outcome prediction, multi-court integration, CRM, payments, user authentication, CAPTCHA bypass.

---

## 2. Personas and Jobs-To-Be-Done

### Persona 1 — Vikram, Solo Lawyer (small Delhi firm)
- **Profile:** 32, LLB, 5 years practice, 40–60 active matters at any time, Android phone primary device, laptop in chambers.
- **Pain:** 8–15 client calls/day, most asking the same "kya update hai?" question. He toggles between WhatsApp and the court site, re-enters CAPTCHAs all day.
- **JTBD:** "When a client asks for an update, I want to pull the latest case status in under 30 seconds so I can answer without losing billable time."

### Persona 2 — Anjali, Paralegal / Office Manager
- **Profile:** 28, runs the back office for a senior advocate with ~120 matters. Tracks hearing dates in a paper diary and Excel.
- **Pain:** Each morning she manually checks 10–20 cases for hearing-date changes and order uploads. Often mistypes case numbers, gets CAPTCHA wrong, restarts.
- **JTBD:** "When I start my day, I want to check the status of today's hearings quickly and accurately so I can brief the senior advocate before he reaches court."

---

## 3. User Stories and Acceptance Criteria

> Stories are also exported to `user-stories.md` for ticket import.

### US-01 — Case search by type/number/year
**As** Vikram (Solo Lawyer), **I want** to enter a case type, case number, and year **so that** I can fetch the latest status without navigating the court website.

**Acceptance Criteria**
1. **Given** I am on the home page **When** I open the case-type dropdown **Then** I see the full list of Delhi HC case types (W.P.(C), CRL.A., RFA, etc.) in plain labels with a tooltip showing the official abbreviation.
2. **Given** I have entered a valid case type, number, and year (e.g. 4-digit) **When** I click "Fetch Status" **Then** the system initiates a backend session and shows a loading indicator within 500ms.
3. **Given** any required field is empty or year is invalid **When** I click "Fetch Status" **Then** the button stays disabled and inline validation messages appear under each invalid field.
4. **Given** I have submitted a search **When** the backend is preparing the CAPTCHA **Then** I see a skeleton state with the text "Connecting to Delhi HC..." and an estimated wait.

**Story Points:** 5

---

### US-02 — CAPTCHA display and entry
**As** Anjali (Paralegal), **I want** to see the court's CAPTCHA image and type the answer **so that** my request is submitted legitimately without bypassing the court's controls.

**Acceptance Criteria**
1. **Given** the backend has fetched a CAPTCHA **When** the image is delivered to the browser **Then** it renders at >=200x60px, sharp, with a "Refresh CAPTCHA" button beside it.
2. **Given** the CAPTCHA is displayed **When** I type my answer and press Enter or click "Submit" **Then** the form is submitted within the same backend session that issued the CAPTCHA.
3. **Given** I click "Refresh CAPTCHA" **When** a new image is requested **Then** the prior CAPTCHA attempt is invalidated and a fresh image appears within 3s.
4. **Given** I have not typed anything **When** I click "Submit" **Then** Submit is disabled with helper text "Enter the CAPTCHA shown above."

**Story Points:** 5

---

### US-03 — Parsed result display
**As** Vikram, **I want** the case status returned as a clean, structured summary **so that** I can read it to a client in plain language.

**Acceptance Criteria**
1. **Given** a successful submission **When** the court returns a valid result page **Then** the UI shows: case title, parties, current status, next hearing date, last order date, and a link to download the latest order (if present).
2. **Given** any field is missing from the source HTML **When** parsing completes **Then** that field displays "Not available" rather than blank or error.
3. **Given** the result includes a hearing-date that is in the past **When** rendered **Then** it is visually de-emphasized and labeled "Past hearing."
4. **Given** the parsed result is displayed **When** I click "Copy summary" **Then** a plain-text version is copied to clipboard suitable for pasting into WhatsApp.
5. **Given** the result page contains an order PDF link **When** I click it **Then** the PDF opens in a new tab via the court's original URL (we do not re-host).

**Story Points:** 5

---

### US-04 — Wrong CAPTCHA error handling
**As** Anjali, **I want** a clear, kind error when I get the CAPTCHA wrong **so that** I can retry without losing my form inputs.

**Acceptance Criteria**
1. **Given** I submit an incorrect CAPTCHA **When** the court responds with a CAPTCHA-mismatch indicator **Then** the UI shows "CAPTCHA didn't match — try again" and auto-fetches a fresh CAPTCHA.
2. **Given** a retry is triggered **When** the new CAPTCHA loads **Then** my case type/number/year inputs are preserved.
3. **Given** three consecutive CAPTCHA failures in one session **When** the third fails **Then** I see "Having trouble? Refresh the page and start again" with a one-click reset.

**Story Points:** 3

---

### US-05 — Session expired / network failure handling
**As** Vikram, **I want** the app to recover gracefully when the court session drops **so that** I don't see a cryptic error.

**Acceptance Criteria**
1. **Given** the backend session with the court has expired before I submit the CAPTCHA **When** I click Submit **Then** the UI shows "Session expired — restarting" and silently re-initiates a new session + CAPTCHA within 5s.
2. **Given** the backend cannot reach the court site (timeout or 5xx) **When** the failure is detected **Then** I see "Delhi HC website is slow or unreachable right now. Try again in a minute." with a "Retry" button.
3. **Given** my own internet drops **When** the request fails client-side **Then** the form state is preserved in browser memory and a "You appear to be offline" banner appears.
4. **Given** a retry succeeds **When** the result returns **Then** no duplicate session artifacts remain on the backend (cleanup verified).

**Story Points:** 5

---

### US-06 — Case not found / no results
**As** Anjali, **I want** to know clearly when a case number doesn't exist **so that** I can double-check the number with the client rather than blame the tool.

**Acceptance Criteria**
1. **Given** the court returns a "no records found" page **When** parsing detects this **Then** the UI shows "No case found for [type] [number]/[year] on Delhi HC. Please verify the case details."
2. **Given** the not-found state **When** displayed **Then** a one-line tip suggests common mistakes (year mismatch, case-type abbreviation, transposed digits).
3. **Given** the court returns multiple matching cases **When** parsing detects more than one record **Then** the UI lists all matches with party names and lets me pick one.

**Story Points:** 3

---

### US-07 — Site-down / structural-change fallback
**As** Vikram, **I want** the app to fail safely when the court site is down or has changed its HTML **so that** I can fall back to the official site without confusion.

**Acceptance Criteria**
1. **Given** parsing throws an unexpected exception **When** the backend cannot extract required fields **Then** the UI shows "We couldn't read the response from Delhi HC. Try the official site directly: [link]."
2. **Given** a parser failure occurs **When** logged **Then** the backend records the raw HTML hash, timestamp, and case inputs for post-mortem (no PII beyond what the user typed).
3. **Given** parser failures exceed 5% of attempts over a rolling 1-hour window **When** the threshold is crossed **Then** an alert is triggered for the on-call engineer (mechanism out of PRD scope; flag to Arnav).

**Story Points:** 5

---

### US-08 — Admin log view (internal)
**As** the product owner, **I want** a minimal admin page showing recent search attempts and outcomes **so that** I can monitor reliability without SSH'ing into the server.

**Acceptance Criteria**
1. **Given** I navigate to `/admin/logs` with the shared admin token **When** the page loads **Then** I see the last 200 searches with columns: timestamp, case ref, outcome (success/captcha_fail/parse_fail/site_down/not_found), duration.
2. **Given** I am not authenticated **When** I hit `/admin/logs` **Then** I get a 404 (not 401 — do not advertise the page).
3. **Given** I want to investigate a failure **When** I click a row with outcome != success **Then** I see the stored raw-HTML hash and the parser version used.
4. **Given** any displayed log line **When** rendered **Then** no client-identifying information beyond the case number itself is shown.

**Story Points:** 3

---

### US-09 — Retry on transient failure
**As** Anjali, **I want** a one-click retry **so that** I don't lose 30s re-entering everything when the court site hiccups.

**Acceptance Criteria**
1. **Given** any non-terminal error state **When** I click "Retry" **Then** my case inputs are reused and a fresh CAPTCHA is fetched.
2. **Given** I have retried twice with the same inputs and both failed with site-down **When** the second failure occurs **Then** the Retry button is replaced with a link to the official Delhi HC site for that query.

**Story Points:** 2

---

### US-10 — Mobile responsiveness
**As** Vikram (on his Android phone between hearings), **I want** the app to work on a 5.5"–6.5" phone screen **so that** I can use it standing in court corridors.

**Acceptance Criteria**
1. **Given** I open the app on a 375px-wide viewport **When** the page loads **Then** all primary actions (case-type dropdown, number input, year, Fetch button) are usable without horizontal scroll.
2. **Given** the CAPTCHA is shown on mobile **When** rendered **Then** the image is at least 240px wide and the input field auto-focuses with `inputmode="text"` and autocorrect off.
3. **Given** the result is displayed on mobile **When** the summary card renders **Then** the "Copy summary" button is reachable with one thumb (bottom 1/3 of screen).

**Story Points:** 3

---

### US-11 — Accessibility (baseline)
**As** any user (including those using a screen reader or keyboard-only), **I want** the app to be navigable without a mouse **so that** the tool is usable for everyone.

**Acceptance Criteria**
1. **Given** I use Tab to navigate **When** I move through the form **Then** focus order is logical: case type -> number -> year -> Fetch -> CAPTCHA -> Submit.
2. **Given** I use a screen reader **When** the CAPTCHA image is shown **Then** the image has alt text "CAPTCHA from Delhi High Court — type the characters into the input below" and the input has a programmatic label.
3. **Given** error states appear **When** rendered **Then** they are announced via `role="alert"` and visible color contrast meets WCAG AA (4.5:1).
4. **Given** I prefer reduced motion **When** loading animations would play **Then** they are replaced with static states per `prefers-reduced-motion`.

**Story Points:** 3

---

## 4. MVP Scope Boundaries

### IN scope (Phase 1)
| Area | Included |
|---|---|
| Case search | Case type + number + year, single Delhi HC source |
| CAPTCHA | Fetched from court, displayed to user, user-solved |
| Result parsing | Title, parties, status, next hearing, last order date, order link |
| Errors | Wrong CAPTCHA, session expired, network failure, not found, site down |
| UX | Mobile responsive, WCAG AA baseline, copy-to-clipboard summary |
| Ops | Admin log view, structured logs, basic alerting hook |
| Stack | Next.js + FastAPI + SQLite, session/cookie persistence |

### OUT of scope (cut aggressively)
| Area | Excluded — why |
|---|---|
| User accounts / auth | Not needed; stateless tool. Defer to Phase 2. |
| Saved cases / watch list | Phase 2 — needs auth or device token. |
| Push notifications / email alerts | Phase 2 — requires identity + scheduler. |
| Multi-court (Bombay HC, SC, district) | Out — each court has different scraping shape. |
| CAPTCHA solving (OCR/ML) | Explicitly forbidden by owner. |
| Legal analysis, summarization by LLM | Not an AI product. Owner directive. |
| Payments / billing | None in v1. |
| Lawyer CRM / client database | Out — different product. |
| Mobile native app | Web only. PWA install acceptable as a stretch. |
| Hindi UI localization | Out for v1 — data may be Hindi, UI is English. |

---

## 5. Success Metrics

### Quantitative (measured weekly during Phase 1)
| Metric | Target | Measurement |
|---|---|---|
| First-CAPTCHA success rate | >=70% | Successful parsed result on first CAPTCHA attempt / total search attempts |
| Median time-to-result | <=12 seconds | From "Fetch Status" click to parsed-result render |
| P95 time-to-result | <=25 seconds | Same as above, 95th percentile |
| Parser failure rate | <=3% | parse_fail outcomes / submissions reaching court successfully |
| Court-site availability proxy | >=95% | (1 - site_down outcomes / total attempts) over rolling 24h |
| Weekly active users | >=50 by end of Phase 1 | Unique browser fingerprints with >=1 successful search/week |
| Retry abandonment | <=20% | Sessions that hit an error and never retry / total error sessions |

### Qualitative
- **Lawyer NPS proxy:** Post-search micro-survey (1 question, optional): "Did this save you a client call?" Target: >=60% "Yes" by week 4.
- **Word-of-mouth signal:** >=5 inbound asks per week from non-seeded users by end of Phase 1.
- **Owner gut check:** Owner uses the tool for his own practice daily without falling back to the court site.

---

## 6. Edge Cases (Ranked by Likelihood x Severity)

| # | Edge Case | Likelihood | Severity | Handling |
|---|---|---|---|---|
| 1 | CAPTCHA expires before user submits (slow typing, distraction) | High | Medium | Detect expiry on submit; auto-fetch new CAPTCHA; preserve form inputs |
| 2 | Wrong CAPTCHA entered | High | Low | Friendly error; new CAPTCHA; preserve inputs (US-04) |
| 3 | Case number doesn't exist | High | Low | Clear "no case found" + suggest verification (US-06) |
| 4 | Court site returns 500 / 502 / 504 | Medium | High | Retry once internally; if still failing, surface site-down message + link to official site (US-05, US-07) |
| 5 | Court site rotates session cookie mid-flow | Medium | High | Detect 302 to login/home; reinitiate session transparently; one retry |
| 6 | Court changes HTML structure (field rename, new wrapper div) | Medium | High | Parser fails gracefully; raw HTML hash logged; alert fires if parse_fail >5%/hr |
| 7 | CAPTCHA image fails to load (broken image bytes, 0-byte response) | Medium | Medium | Show "Couldn't load CAPTCHA — refresh" with auto-retry once |
| 8 | Multiple matching cases for same input | Medium | Medium | Show disambiguation list with party names (US-06 AC-3) |
| 9 | Mixed-script result fields (Hindi Devanagari + English) | Medium | Medium | Ensure UTF-8 end-to-end; test render in Inter or Noto Sans Devanagari fallback |
| 10 | Court site rate-limits our IP | Low (early) / High (at scale) | High | Honor 429s with exponential backoff; surface a queued state to user; OPEN QUESTION on rate-limit thresholds |
| 11 | User types CAPTCHA in wrong language/layout (Hindi keyboard active) | Low | Low | Input field forces Latin; warn if non-Latin chars detected |
| 12 | Case has hundreds of historical orders — payload bloats result | Low | Medium | Show only latest 5; "Show all" expands; never block render on full list |
| 13 | User refreshes the page mid-CAPTCHA | Medium | Low | Backend session orphaned but garbage-collected after 5 min idle |
| 14 | Two tabs open with two parallel searches from same user | Low | Medium | Each tab gets isolated session; document this isn't a bug |
| 15 | Date formats in result inconsistent (DD/MM/YYYY vs DD-MM-YYYY vs DD MMM YYYY) | Medium | Low | Normalize at parse layer; render canonical "DD MMM YYYY" |

---

## 7. Product-Side Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Court website changes layout/structure without notice | High | High | Build parser as a thin, versioned module; log raw HTML hash on parse fail; alert at 5%/hr threshold; budget 2 eng-days/month for parser maintenance |
| R2 | Court changes CAPTCHA scheme (e.g. adds reCAPTCHA v3) | Medium | Critical (kills product) | Monitor for image-type changes in Phase 0 spike; if reCAPTCHA appears, product is non-viable in current form — owner decision gate |
| R3 | Users distrust a third-party wrapper over an official site | Medium | Medium | Always show "Source: Delhi High Court" with timestamp and a direct link to the official result page; never appear to "be" the court |
| R4 | Legal/compliance perception that we are "scraping" the court | Medium | High | (Sneha owns full review.) Product implication: keep the UX explicit that the user is solving the CAPTCHA themselves and we are a UX layer, not an automation bot. Display a clear footer disclaimer. |
| R5 | Reliability vs. cost tradeoff — SQLite + single VM may not handle scale | Low (MVP) / High (post-MVP) | Medium | Postgres-ready schema; design stateless backend so horizontal scale is later choice; alerting on session-pool exhaustion |
| R6 | Owner-led product with no validated demand beyond owner's own firm | Medium | Medium | Seed Phase 1 with 5–10 friendly lawyers; gate Phase 2 investment on >=50 WAU and >=60% NPS-proxy yes |
| R7 | Court site adds Terms of Use forbidding automated access | Low | Critical | (Sneha owns ToS review.) Product implication: if ToS forbids, product cannot ship — block before Phase 1 launch |

---

## 8. Phased Roadmap

### Phase 0 — Feasibility Spike (Week 1)
**Goal:** De-risk the three things that can kill this product.

**Deliverables**
- Manual end-to-end walkthrough of Delhi HC case search, screenshotted, every field documented
- Proof-of-concept Python script that opens a session, fetches CAPTCHA bytes, submits a form, returns raw HTML — no UI
- Inventory of all case types and their abbreviations as the court uses them
- ToS / robots.txt review (handoff to Sneha) — written go/no-go
- Sample of 20 real result pages with varied shapes (1 hearing, many hearings, no orders, Hindi names, etc.)

**Success gate (must pass all 3 to enter Phase 1):**
1. Session-and-CAPTCHA round-trip works programmatically for >=90% of 50 test attempts
2. Sneha returns "no blocker" on ToS / robots.txt
3. Parser handles >=80% of the 20 sample result pages without manual fixup

**Exit criteria:** Owner sign-off + Sneha sign-off + spike report committed to repo.

---

### Phase 1 — MVP Launch (Weeks 2–4)
**Goal:** Ship the smallest thing that lets a real lawyer answer a real client question faster than the court website.

**Deliverables**
- All 11 user stories above, shipped behind a single public URL
- Admin log view (US-08)
- Structured logs + alerting hook on parser failure rate
- Mobile-responsive UI (US-10)
- WCAG AA baseline (US-11)
- Public landing page with clear "what this is / what this isn't" disclaimer
- 5–10 friendly lawyers onboarded as Phase 1 testers

**Success gate (week 4 review):**
- >=70% first-CAPTCHA success rate over the last 7 days
- Median time-to-result <=12s
- Parser failure rate <=3%
- >=50 weekly active users
- Zero P0 incidents in the final week

**Exit criteria:** All Phase 1 metrics met for 7 consecutive days. Owner decides Phase 2 go/no-go.

---

### Phase 2 — Post-MVP (after Phase 1 validates)
**Goal:** Move from "useful tool" to "indispensable workflow."

**Candidate deliverables (priority order, not commitments):**
1. Saved cases / watch list (requires lightweight identity — device token or phone-number OTP)
2. Daily auto-check digest: email or WhatsApp summary of hearing-date changes (still requires user-solved CAPTCHA on first add)
3. Search history per browser
4. Postgres migration from SQLite
5. PWA installability
6. Hindi UI localization
7. Add a second court (Bombay HC) as a scoping experiment

**Success gate:** Re-validated metrics + qualitative interviews with >=10 active users.

**Exit criteria:** Not defined yet — Phase 2 is gated on Phase 1 results.

---

## 9. Open Questions for the Owner

**OPEN QUESTION 1:** How often historically has the Delhi HC website changed its HTML structure or CAPTCHA scheme? (Affects R1, R2 risk weighting and parser maintenance budget.)

**OPEN QUESTION 2:** Does the Delhi HC `robots.txt` and Terms of Use permit programmatic session creation when the human still solves the CAPTCHA? (Hand to Sneha — but owner needs to confirm we will not ship without her green light.)

**OPEN QUESTION 3:** What is the acceptable rate-limit posture if the court starts throttling our backend IP? Single shared IP vs. per-user pass-through? (Affects scale ceiling.)

**OPEN QUESTION 4:** Who is the on-call human when the parser breaks at 2am? Is there a budget for paid monitoring (e.g. UptimeRobot, Better Stack) or do we rely on best-effort?

**OPEN QUESTION 5:** Should the MVP collect a phone number or email at all, even optionally? (Owner directive says no auth in v1, but a single optional email field unlocks Phase 2 alerts. Sneha must weigh in on PII implications.)

**OPEN QUESTION 6:** Is the 5–10 friendly-lawyer cohort already lined up, or does the owner need help recruiting? (Affects Phase 1 timeline.)

**OPEN QUESTION 7:** What is the budget ceiling for cloud hosting in Phase 1? (Affects whether we pick a $5/mo VPS or a managed platform.)

**OPEN QUESTION 8:** Does the owner want a public landing page indexed by Google in Phase 1, or stay invite-only? (Affects SEO work and abuse exposure.)

**OPEN QUESTION 9:** Are there specific case types (e.g. W.P.(C), CRL.M.C.) the owner's practice uses most often that we should prioritize parser coverage for in Phase 0?

---

## 10. Cross-Team Handoffs

- **Arnav (Architecture):** Owns session-pool design, parser versioning strategy, alerting threshold implementation. PRD flags US-07 AC-3 and R5 for his attention.
- **Rohit (Database):** Owns SQLite schema and Postgres migration path. PRD flags admin-log retention policy as input.
- **Sneha (Security/Legal):** Owns ToS review, robots.txt review, PII posture on admin logs, footer disclaimer copy. Blocking gate at Phase 0 exit.
- **Maya (QA):** Will derive a test plan from Sections 3 and 6. Phase 1 cannot exit without her sign-off on the edge-case matrix.
- **Sara (Frontend) and Arjun (Backend):** Implementation owners for Phase 1 stories.

---

## 11. Confidence

**Confidence: 7/10.** Product shape, scope, and metrics are well-defined and the JTBD is concrete. The 3-point deduction is for the two unresolved external dependencies that can kill the product outright: (a) ToS/robots.txt posture pending Sneha's review, and (b) court-site structural stability, which we cannot know without the Phase 0 spike. Both are addressed by gating Phase 1 on Phase 0 outcomes, but they remain genuine unknowns at draft time.
