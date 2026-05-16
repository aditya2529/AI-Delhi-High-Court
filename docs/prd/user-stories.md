# Delhi HC Case Tracker — User Stories (Ticket-Import Format)

**Source PRD:** `./PRD.md`
**Last updated:** 2026-05-17
**Owner:** Priya (Product)

> Use this file as the source of truth for ticket creation. Each row maps 1:1 to a Jira/Linear/GitHub Issue. Acceptance criteria live in the per-story sections below the table.

---

## Summary Table

| ID | Title | Persona | Priority | Points | Phase | Depends on |
|----|-------|---------|----------|--------|-------|-----------|
| US-01 | Case search by type/number/year | Vikram | P0 | 5 | 1 | — |
| US-02 | CAPTCHA display and entry | Anjali | P0 | 5 | 1 | US-01 |
| US-03 | Parsed result display | Vikram | P0 | 5 | 1 | US-02 |
| US-04 | Wrong CAPTCHA error handling | Anjali | P0 | 3 | 1 | US-02 |
| US-05 | Session expired / network failure handling | Vikram | P0 | 5 | 1 | US-02 |
| US-06 | Case not found / no results | Anjali | P0 | 3 | 1 | US-03 |
| US-07 | Site-down / structural-change fallback | Vikram | P0 | 5 | 1 | US-03 |
| US-08 | Admin log view (internal) | Owner | P1 | 3 | 1 | US-03, US-07 |
| US-09 | Retry on transient failure | Anjali | P1 | 2 | 1 | US-05, US-07 |
| US-10 | Mobile responsiveness | Vikram | P0 | 3 | 1 | US-01, US-02, US-03 |
| US-11 | Accessibility (WCAG AA baseline) | Any | P0 | 3 | 1 | US-01, US-02, US-03 |

**Total Phase 1 points:** 42

---

## US-01 — Case search by type/number/year
**Story:** As Vikram (Solo Lawyer), I want to enter a case type, case number, and year so that I can fetch the latest status without navigating the court website.

**Acceptance Criteria**
1. Given I am on the home page, When I open the case-type dropdown, Then I see the full list of Delhi HC case types with plain labels and a tooltip showing the official abbreviation.
2. Given I have entered a valid case type, number, and year, When I click "Fetch Status", Then the system initiates a backend session and shows a loading indicator within 500ms.
3. Given any required field is empty or invalid, When I click "Fetch Status", Then the button stays disabled with inline validation messages.
4. Given I have submitted a search, When the backend prepares the CAPTCHA, Then I see a skeleton state with "Connecting to Delhi HC..." and an ETA.

---

## US-02 — CAPTCHA display and entry
**Story:** As Anjali (Paralegal), I want to see the court's CAPTCHA image and type the answer so that my request is submitted legitimately without bypassing the court's controls.

**Acceptance Criteria**
1. Given the backend has fetched a CAPTCHA, When the image is delivered, Then it renders at >=200x60px with a "Refresh CAPTCHA" button.
2. Given the CAPTCHA is displayed, When I submit my answer, Then the form is submitted within the same backend session that issued the CAPTCHA.
3. Given I click "Refresh CAPTCHA", When a new image is requested, Then the prior CAPTCHA is invalidated and a fresh image appears within 3s.
4. Given I have not typed anything, When I click Submit, Then Submit is disabled with helper text "Enter the CAPTCHA shown above."

---

## US-03 — Parsed result display
**Story:** As Vikram, I want the case status returned as a clean, structured summary so that I can read it to a client in plain language.

**Acceptance Criteria**
1. Given a successful submission, When the court returns a valid result page, Then the UI shows case title, parties, current status, next hearing, last order date, and order link.
2. Given any field is missing from the source HTML, When parsing completes, Then that field displays "Not available".
3. Given a hearing-date in the past, When rendered, Then it is de-emphasized and labeled "Past hearing".
4. Given the result is displayed, When I click "Copy summary", Then a plain-text version is copied to clipboard.
5. Given the result includes an order PDF link, When I click it, Then the PDF opens via the court's original URL.

---

## US-04 — Wrong CAPTCHA error handling
**Story:** As Anjali, I want a clear, kind error when I get the CAPTCHA wrong so that I can retry without losing my form inputs.

**Acceptance Criteria**
1. Given I submit an incorrect CAPTCHA, When the court flags a mismatch, Then the UI shows "CAPTCHA didn't match — try again" and auto-fetches a fresh CAPTCHA.
2. Given a retry is triggered, When the new CAPTCHA loads, Then my case inputs are preserved.
3. Given three consecutive CAPTCHA failures, When the third fails, Then I see "Having trouble? Refresh the page and start again" with a one-click reset.

---

## US-05 — Session expired / network failure handling
**Story:** As Vikram, I want the app to recover gracefully when the court session drops so that I don't see a cryptic error.

**Acceptance Criteria**
1. Given the backend session has expired, When I click Submit, Then the UI shows "Session expired — restarting" and silently re-initiates a new session + CAPTCHA within 5s.
2. Given the backend cannot reach the court site, When the failure is detected, Then I see "Delhi HC website is slow or unreachable right now. Try again in a minute." with Retry.
3. Given my own internet drops, When the request fails client-side, Then form state is preserved and an offline banner appears.
4. Given a retry succeeds, When the result returns, Then no duplicate session artifacts remain on the backend.

---

## US-06 — Case not found / no results
**Story:** As Anjali, I want to know clearly when a case number doesn't exist so that I can verify with the client.

**Acceptance Criteria**
1. Given the court returns "no records found", When parsing detects this, Then the UI shows "No case found for [type] [number]/[year] on Delhi HC. Please verify the case details."
2. Given the not-found state, When displayed, Then a tip suggests common mistakes (year, abbreviation, transposed digits).
3. Given multiple matches are returned, When parsing detects more than one record, Then the UI lists matches with party names and lets me pick one.

---

## US-07 — Site-down / structural-change fallback
**Story:** As Vikram, I want the app to fail safely when the court site is down or has changed its HTML so that I can fall back to the official site.

**Acceptance Criteria**
1. Given parsing throws unexpectedly, When required fields can't be extracted, Then the UI shows "We couldn't read the response from Delhi HC. Try the official site directly: [link]."
2. Given a parser failure occurs, When logged, Then the backend records raw HTML hash, timestamp, and case inputs (no extra PII).
3. Given parser failures exceed 5% over a rolling 1-hour window, When the threshold is crossed, Then an alert is triggered for on-call (mechanism owned by Arnav).

---

## US-08 — Admin log view (internal)
**Story:** As the product owner, I want a minimal admin page showing recent search attempts and outcomes so that I can monitor reliability.

**Acceptance Criteria**
1. Given I navigate to /admin/logs with the admin token, When the page loads, Then I see the last 200 searches with timestamp, case ref, outcome, duration.
2. Given I am not authenticated, When I hit /admin/logs, Then I get a 404 (not 401).
3. Given a failure row, When I click it, Then I see the stored raw-HTML hash and parser version.
4. Given any log line, When rendered, Then no client-identifying info beyond the case number is shown.

---

## US-09 — Retry on transient failure
**Story:** As Anjali, I want a one-click retry so that I don't lose 30s re-entering everything when the court site hiccups.

**Acceptance Criteria**
1. Given any non-terminal error state, When I click Retry, Then my inputs are reused and a fresh CAPTCHA is fetched.
2. Given two consecutive site-down failures with the same inputs, When the second fails, Then Retry is replaced with a link to the official Delhi HC site for that query.

---

## US-10 — Mobile responsiveness
**Story:** As Vikram on his Android phone, I want the app to work on a 5.5"–6.5" phone screen so that I can use it standing in court corridors.

**Acceptance Criteria**
1. Given a 375px viewport, When the page loads, Then all primary actions are usable without horizontal scroll.
2. Given the CAPTCHA on mobile, When rendered, Then the image is >=240px wide and the input auto-focuses with `inputmode="text"`, autocorrect off.
3. Given the result on mobile, When the summary card renders, Then "Copy summary" is reachable in the bottom 1/3 of screen.

---

## US-11 — Accessibility (WCAG AA baseline)
**Story:** As any user (including screen-reader or keyboard-only), I want the app to be navigable without a mouse so that the tool is usable for everyone.

**Acceptance Criteria**
1. Given I use Tab, When I move through the form, Then focus order is: case type -> number -> year -> Fetch -> CAPTCHA -> Submit.
2. Given a screen reader, When the CAPTCHA is shown, Then the image has descriptive alt text and the input has a programmatic label.
3. Given an error state, When rendered, Then it is announced via `role="alert"` and contrast meets WCAG AA (4.5:1).
4. Given `prefers-reduced-motion`, When loading animations would play, Then static states are used instead.

---

**Confidence: 7/10** — Story shape and ACs are firm. Two external unknowns (ToS posture and court-site stability) remain and are gated by the Phase 0 spike, per PRD Section 8.
