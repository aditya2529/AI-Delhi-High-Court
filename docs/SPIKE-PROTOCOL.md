# Phase-0 Reconnaissance Spike — Developer Execution Protocol

**Status:** Ready to execute · **Owner (architect):** Arnav · **Executor:** developer-with-browser (1 person, 2 days)
**Companion:** [`SPIKE-REPORT.md`](./SPIKE-REPORT.md) — context, observable surface already mapped, and the unknowns this protocol closes.
**Target site:** `https://delhihighcourt.nic.in` (form: `/app/get-case-type-status`)
**Hard rule:** **Read [`SPIKE-REPORT.md`](./SPIKE-REPORT.md) before starting.** Skip nothing in this protocol. If a step is impossible (e.g. site is down), document the blocker in Section G of the report and proceed to the next step where possible.

---

## Pre-flight (15 minutes)

| # | Action | Pass criterion |
|---|---|---|
| P.1 | Create the capture directory: `mkdir parsers/fixtures/real_responses && mkdir docs/legal/snapshots` (PowerShell: `New-Item -ItemType Directory parsers/fixtures/real_responses, docs/legal/snapshots`). | Both directories exist. |
| P.2 | Confirm `OUTBOUND_FETCH_ENABLED=false` in your local `.env` for the duration of the spike. The spike does **not** go through our backend — you hit the court site directly from your browser and CLI tools. The kill-switch is set so a stray dev request from the app doesn't pollute the rate-limit log. | `.env` has `OUTBOUND_FETCH_ENABLED=false`. |
| P.3 | Tools installed: Chrome (or Edge) with DevTools, `curl` ≥ 8 (Windows 11 ships this), `httpx` Python CLI (`pip install "httpx[cli]"` in `.venv`), a plain text editor. | `curl --version`, `httpx --help` both work. |
| P.4 | Mental model: you are a **lawyer who happens to read HTTP**. Move at human pace. Never exceed 1 request per 3 seconds on the court site during reconnaissance. Never run any automated loop in this protocol. | Self-affirmed. |
| P.5 | Open a scratch notebook (any markdown file) for verbatim observations. You will paste from it into `SPIKE-REPORT.md` Section G at the end. | Notebook open. |

---

## 1. Capture the full HTTP cycle

**Closes:** B.1, B.10 in `SPIKE-REPORT.md`.

| Step | Tool | Action |
|---|---|---|
| 1.1 | Chrome DevTools → Network tab | Open DevTools **before** navigating. Tick "Preserve log" and "Disable cache". |
| 1.2 | Browser | Navigate to `https://delhihighcourt.nic.in/app/get-case-type-status`. |
| 1.3 | DevTools → Network | Wait until the page is fully loaded (loader gif gone). Scroll the request list — find the `get-case-type-status` document request. |
| 1.4 | DevTools → Network → that request → Headers tab | Screenshot to `docs/legal/snapshots/get-form-headers.png`. Note: request method, status code, every response header (especially `Set-Cookie`, `Cache-Control`, `Content-Type`, `Server`, `X-*`), and the redirect chain (if any) shown at the top. |
| 1.5 | DevTools → Network → that request → Cookies tab | Screenshot to `docs/legal/snapshots/get-form-cookies.png`. Note every cookie name, domain, path, `HttpOnly`, `Secure`, `SameSite`, and approximate expiry. |
| 1.6 | DevTools → Network → right-click any request → Save all as HAR with content | Save to `docs/legal/snapshots/form-load.har`. This is the canonical evidence file. |
| 1.7 | DevTools → Application tab → Cookies → `https://delhihighcourt.nic.in` | Verify the cookies the browser is now holding match what 1.5 showed. If the browser is holding extras (set by JS post-load), note them. |
| 1.8 | Verify cross-host redirects | In the HAR file, search for any URL where `host != "delhihighcourt.nic.in"`. List them in the notebook. |

**Capture artifacts:** `form-load.har`, `get-form-headers.png`, `get-form-cookies.png`. All under `docs/legal/snapshots/`.

**Pass criterion:** HAR file saved, every cookie name documented, every response header documented, all cross-host hops (if any) listed.
**Fail handling:** if the site is unreachable, document the time + your IP location (no IP itself — just "Delhi residential ISP" or similar) and try again from a different network within the same day. If still unreachable, mark the spike blocked and escalate to Arnav.

---

## 2. Determine real form action + method

**Closes:** B.2.

| Step | Tool | Action |
|---|---|---|
| 2.1 | DevTools → Network tab still open with preserve log on | Stay on the form page. |
| 2.2 | Browser | Fill the form with a **known, real, public case**. Suggested: `W.P.(C)` / `12345` / `2024` (a common write-petition number — should yield either "not found" or a real result, both are useful). Solve the CAPTCHA yourself. Click submit. |
| 2.3 | DevTools → Network | Find the request fired by the submit. Note its **URL** (full, including query string), **method** (almost certainly POST), and the **`Content-Type`** of the request body. |
| 2.4 | DevTools → Network → that request → Payload tab | Screenshot to `docs/legal/snapshots/submit-payload.png`. List every body parameter name (case-sensitive), its value, and whether it appeared to be `application/x-www-form-urlencoded` or `multipart/form-data`. |
| 2.5 | DevTools → Network → that request → Headers → Request Headers | Note `Referer`, `Origin`, `Cookie`, `User-Agent`, `Accept`, `Accept-Language`. The full submit-time cookie jar is the union the real client will need. |
| 2.6 | Save the request as cURL | Right-click the request → Copy → Copy as cURL (bash). Paste into `docs/legal/snapshots/submit.curl.txt`. Sanitise: replace the CAPTCHA value with `[REDACTED]`, the case number with `12345` (it is the same), nothing else. |

**Capture artifacts:** `submit-payload.png`, `submit.curl.txt`.

**Pass criterion:** `submit.curl.txt` runs successfully when replayed from the same machine within the CAPTCHA TTL window — this proves we can drive the form from outside the browser. Save the response HTML as `parsers/fixtures/real_responses/_smoke_submit.html` (do **not** count this toward the 20-fixture target — it is a smoke test).
**Fail handling:** if the replayed cURL returns a different page (e.g. "session expired") even within seconds, the form is bound to something more than cookies — most likely B.3 (CSRF in a hidden field set by JS at submit time). Flag it and proceed to §3.

---

## 3. Determine CSRF/state token mechanism

**Closes:** B.3 (critical).

| Step | Tool | Action |
|---|---|---|
| 3.1 | DevTools → Sources tab → Snippets | Reload the form page. **Before** typing anything, paste this into a snippet and run: `copy(document.querySelector('form').outerHTML)`. The form HTML at runtime is now on your clipboard. Paste it into `docs/legal/snapshots/form-runtime.html`. |
| 3.2 | Compare | Diff `form-runtime.html` against the static markup (you can get the static markup with `curl -sS -c /tmp/jar.txt https://delhihighcourt.nic.in/app/get-case-type-status -o docs/legal/snapshots/form-static.html`). Use any diff tool (VSCode built-in diff is fine). |
| 3.3 | Classify the mechanism | Look for hidden fields in the **runtime** HTML that are absent from the **static** HTML. Possible findings: (a) `<input type="hidden" name="_token" value="...">` — Drupal/Laravel-style CSRF token, **present in static only after first POST attempt or always present**; (b) `<input type="hidden" name="captcha_id" value="...">` — CAPTCHA pairing token; (c) nothing extra — token is cookie-only. |
| 3.4 | Submit the form again from another tab without DevTools | Note: does the submit succeed? If yes and there is no body-level token, the mechanism is **cookie-only** — that is the easiest path for `DelhiHCClient`. |
| 3.5 | Diff cookies before vs after submit | DevTools → Application → Cookies. Note any cookie whose value changed between form-GET and submit-response. Document the cookie name and the change pattern (rotates per request? sticky for the session?). |

**Decision matrix to record in the notebook:**

| Finding | Implication for `DelhiHCClient` |
|---|---|
| Body-level hidden token, value stable per GET | Capture on GET, echo on POST. `httpx`-only path is viable. |
| Body-level hidden token, value injected by JS at submit | We need Playwright OR we reverse-engineer the JS. Flag to Arnav before committing to a path. |
| No body token; cookie rotates per request | Easy — cookie jar handles it automatically. |
| No body token; cookie stable across session | Easy — set once, reuse. |
| Cookie set only by an XHR (not by the main GET) | Must replay that XHR in `init_session`. |

**Capture artifacts:** `form-runtime.html`, `form-static.html`, notebook entry with the decision-matrix row that applies.

**Pass criterion:** the developer can state in one sentence what the CSRF mechanism is. If they cannot, the spike pauses and Arnav re-scopes — this is the make-or-break unknown.

---

## 4. Determine CAPTCHA TTL + refresh path

**Closes:** B.4.

| Step | Tool | Action |
|---|---|---|
| 4.1 | DevTools → Network with preserve log | Reload the form. Find the CAPTCHA image request — it is the only `image/*` response on the form-load HAR. Note its URL, status code, and `Content-Type`. |
| 4.2 | Click the refresh button on the CAPTCHA widget | Watch the Network tab. Note the URL of the new request. Is it the same URL with a different query string? A totally different path? Does it set a new cookie? |
| 4.3 | Record image MIME, dimensions, byte length | Right-click the image preview in DevTools → "Open in new tab", then save it (`Ctrl+S`) into `docs/legal/snapshots/captcha-sample-01.<ext>`. Repeat once more after a refresh as `captcha-sample-02.<ext>`. |
| 4.4 | Classify the CAPTCHA character set | Inspect both samples by eye. Numeric-only (digits)? Alphanumeric (upper, lower, digits)? Mixed-case? Any confusable glyphs (O/0, I/1, l)? Note the apparent length. |
| 4.5 | Probe TTL | Open four browser tabs, load the form in each. In each tab, wait a different duration before submitting (with a deliberately-wrong CAPTCHA so we don't waste real attempts): Tab A: submit immediately. Tab B: wait 60s, submit. Tab C: wait 120s, submit. Tab D: wait 240s, submit. **Pace this — these are 4 outbound submits, separated by minutes, well under any rate limit.** |
| 4.6 | Record the boundary | The first tab whose submit returns a CAPTCHA-token-related error (vs the standard "invalid captcha" content error) is past TTL. Record the boundary as a range — e.g. "TTL is between 120s and 240s; safest assumption 90s remains, retighten to 60s if any reproducer shows < 120s." |

**Capture artifacts:** `captcha-sample-01.*`, `captcha-sample-02.*`, notebook entries for §4.1, §4.2, §4.4, §4.6.

**PII rule:** CAPTCHA images are not PII. Save as-is.

**Pass criterion:** the developer can fill in this row in the final report:

> *CAPTCHA: MIME = `<image/...>`, dimensions = `<WxH>` px, charset = `<numeric|alphanumeric|...>`, length = `<n>`, refresh endpoint = `<URL pattern>`, TTL = `<observed range>`, our assumption in STRATEGIES.md (90s) is `<confirmed | tightened to Ns | loosened to Ns>`.*

---

## 5. Capture the Case Type enum

**Closes:** B.5.

| Step | Tool | Action |
|---|---|---|
| 5.1 | DevTools → Elements tab | Inspect the Case Type `<select>` element. Right-click → Copy → Copy outerHTML. |
| 5.2 | Paste | Save as `parsers/fixtures/real_responses/case_types.html`. Wrap in a minimal `<html><body>` if the editor complains; the file is purely a fixture for enum extraction, not a renderable page. |
| 5.3 | Sanity check | Open the file. Count `<option>` lines. Confirm 100+ entries. Confirm `W.P.(C)` and `CRL.A.` are present (these are the two highest-volume case types). |
| 5.4 | Note encoding | Confirm the file is UTF-8 with no BOM (PowerShell default Out-File is UTF-16 with BOM — use `Set-Content -Encoding utf8` or just paste in VSCode). |

**Capture artifact:** `parsers/fixtures/real_responses/case_types.html`.

**Pass criterion:** the file contains every `<option value="...">label</option>` exactly as the upstream `<select>` declares them.

---

## 6. Capture 20 representative result pages

**Closes:** B.6 (and is the load-bearing input to G4).

Aim for **distribution coverage, not volume**. We want one fixture per failure-mode-class, so the parser is forced to handle each. Suggested matrix (substitute real numbers/years per case type the lawyer-developer is most familiar with — using your own publicly-disposed cases is ideal because anonymisation is trivial):

| Fixture filename | Case shape | Why it matters |
|---|---|---|
| `wpc_pending_multipart.html` | W.P.(C), pending, multiple petitioners + respondents | Tests party table extraction at scale |
| `wpc_pending_singleparty.html` | W.P.(C), pending, 1+1 parties | Most common simple case |
| `wpc_disposed_with_judgment.html` | W.P.(C), disposed, judgment PDF attached | Tests judgment table |
| `crla_pending_orders.html` | CRL.A., pending, 3+ orders | Tests orders table at scale |
| `crla_disposed.html` | CRL.A., disposed | |
| `fao_fresh_noorders.html` | FAO, just filed, no orders yet | Tests the no-orders code path; this is the fixture class that drove the 0.55 floor recommendation |
| `bail_appln_disposed.html` | BAIL APPLN., disposed | Tests a non-standard case type label (with space) |
| `arba_reserved.html` | ARB.A., judgment reserved | Tests "reserved" status |
| `crlmc_pending.html` | CRL.M.C., pending | |
| `ca_pending.html` | CA, pending | |
| `wpc_transferred.html` | W.P.(C), transferred to another bench | Tests bench/court-no edge case |
| `wpc_withdrawn.html` | W.P.(C), withdrawn | |
| `crla_dismissed_inlimine.html` | CRL.A., dismissed in limine | Status string variant |
| `wpc_pending_intervener.html` | W.P.(C), with intervener party | Tests party role beyond petitioner/respondent |
| `wpc_pending_amicus.html` | W.P.(C), with amicus curiae | Tests amicus role |
| `wpc_long_title.html` | Any case with a > 200 char party name | Tests text overflow |
| `admin_report_pending.html` | ADMIN.REPORT type | Tests an unusual case type |
| `wpc_no_next_hearing.html` | W.P.(C), no next-hearing date set | Tests null-field tolerance |
| `wpc_old_2002.html` | W.P.(C), year 2002 | Tests very old case rendering (HTML may differ for archival) |
| `notfound_response.html` | Any (case_type, number, year) deliberately invalid | Tests the not-found sentinel |

For each fixture:

| Step | Action |
|---|---|
| 6.1 | Submit the form for the chosen case (one at a time, pace ≥ 3s between submits). |
| 6.2 | Wait for the result page. **View Source** (`Ctrl+U`) — do not "Save Page As", that pulls in CSS/JS and rewrites paths. |
| 6.3 | Copy the full HTML. Paste into `parsers/fixtures/real_responses/<filename>` (UTF-8, LF line endings). |
| 6.4 | **Anonymise PII before saving:** replace every petitioner/respondent natural-person name with `[REDACTED]`. Replace advocate names with `[REDACTED]`. Replace any party address with `[REDACTED]`. Replace any phone number / email with `[REDACTED]`. **Do NOT redact:** case number, year, case type, status, hearing dates, court number, judge bench (bench is a public judicial identifier, not PII), order/judgment PDF URLs (they are court-published documents). |
| 6.5 | If a person is identifiable by combination of date + role + tiny party, replace the specific hearing date with the year + `XX-XX` (e.g. `2024-XX-XX`). Default: keep dates as-is. |
| 6.6 | Append a one-line comment at the top of each fixture: `<!-- captured 2026-05-17, case shape: <one-phrase>, PII anonymised per SPIKE-PROTOCOL §6 --> ` |

**Anonymisation rule summary (paste this onto your monitor):**
- Natural person names → `[REDACTED]`
- Addresses → `[REDACTED]`
- Phones / emails → `[REDACTED]`
- Case numbers, years, types, statuses, dates, court numbers, judges, PDF URLs → **keep**

**Pass criterion:** 20 files in `parsers/fixtures/real_responses/`, each opens in a browser as plausibly-real HTML, no natural-person name appears in any of them (run `grep -i "petitioner\|respondent" parsers/fixtures/real_responses/*.html` and eyeball every match).

**Fail handling:** if 20 distinct shapes are not reachable from the cases the developer knows, capture as many shapes as possible (minimum 12) and document the gap. G4 (≥16/20) can still close as long as the parser hits 16 of *whatever was captured*, but the more shapes, the better.

---

## 7. Probe rate limit gently

**Closes:** B.7.

**Hard rule:** never exceed 2 req/s. Stop at the first sign of degradation. We are mapping the floor of polite, not testing the ceiling of impolite.

| Step | Tool | Action |
|---|---|---|
| 7.1 | Open `httpx` in a Python REPL or write a `scripts/spike/ratelimit_probe.py` (untracked — do not commit to repo). | |
| 7.2 | Make 10 GETs to `https://delhihighcourt.nic.in/app/get-case-type-status` at **0.33 req/s** (one every 3 s). Record status code, latency (ms), response size for each. | This is our default rate (`DHC_OUTBOUND_RATE_LIMIT_PER_SEC=0.33`). It must succeed cleanly. |
| 7.3 | Wait 60 s. Make 20 GETs at **1 req/s**. Same recording. | First step up. |
| 7.4 | Wait 60 s. Make 20 GETs at **2 req/s**. Same recording. | This is the **maximum** any spike step ever does. Do not go higher. |
| 7.5 | Stop. Inspect: at what rate did p95 latency rise > 2x the 0.33 baseline? Did any request return 4xx, 5xx, or an HTML interstitial? Did any request return a non-form page (Cloudflare challenge, NIC WAF block)? | |
| 7.6 | Recovery probe (only if you saw any degradation): wait 5 min, retry at 0.33 req/s. Confirm normal latency returns. Record the recovery window. | |
| 7.7 | Note the time of day for the test (court site loads vary diurnally; morning Delhi time has heavier baseline traffic). | |

**Capture artifact:** a one-page log committed as `docs/legal/snapshots/ratelimit-probe-log.md` containing the request table + the recommendation:

> *Recommended `DHC_OUTBOUND_RATE_LIMIT_PER_SEC`: `<value>`. Tested floor: 0.33 req/s clean. Tested ceiling: `<observed degradation rate>`. Recovery window: `<observed>`.*

**Pass criterion:** the log exists; the developer can defend keeping the current 0.33 default OR proposing a different default with evidence.

**Fail handling:** if any probe returns a CAPTCHA challenge page (Cloudflare-style "are you human"), STOP IMMEDIATELY and document it. Do not retry from the same IP for 24 hours. This is the WAF telling us our default is too high already; tighten to 0.1 req/s and re-run after the cool-off.

---

## 8. Snapshot robots.txt and legal pages

**Closes:** B.8, B.9.

| Step | Tool | Action |
|---|---|---|
| 8.1 | `curl -sS https://delhihighcourt.nic.in/robots.txt -o docs/legal/robots.txt.snapshot` | Save the file verbatim. If 404, save a one-line note in its place: `2026-05-17: /robots.txt returned 404 — no disallow rules published.` This is itself a legally relevant finding. |
| 8.2 | `curl -sS https://delhihighcourt.nic.in/web/copyright-policy -o docs/legal/copyright-policy.snapshot.html` | Save verbatim HTML. |
| 8.3 | `curl -sS https://delhihighcourt.nic.in/web/privacy-policy -o docs/legal/privacy-policy.snapshot.html` | Save verbatim HTML. |
| 8.4 | `curl -sS https://delhihighcourt.nic.in/web/hyperlinking-policy -o docs/legal/hyperlinking-policy.snapshot.html` | Save (even though we already have the relevant clauses in the report; the verbatim snapshot is what Sneha will quote to counsel). |
| 8.5 | Ping Sneha | Drop a line in #sec channel: "Spike snapshots ready in `docs/legal/` — robots.txt, copyright, privacy, hyperlinking. G2 inputs in place." |

**Capture artifacts:** 4 files in `docs/legal/`.

**PII rule:** none — these are public policy pages.

**Pass criterion:** all 4 files exist, none is a CDN error page, hashes recorded in the notebook (so we can detect if the policy changes between today and Sneha's review).

---

## 9. End-of-day-2 wrap-up

| Step | Action |
|---|---|
| 9.1 | Open [`SPIKE-REPORT.md`](./SPIKE-REPORT.md) → scroll to Section G. Fill in a subsection per B-row (B.1 through B.10) using the notebook entries. Format: "What we expected / What we observed / Decision". |
| 9.2 | Update [`STRATEGIES.md`](./architecture/STRATEGIES.md) — search for `TO BE VERIFIED IN SPIKE` and replace each marker with the verbatim finding (CAPTCHA TTL, cookie/CSRF mechanism, image MIME). Commit. |
| 9.3 | Run `git status` — confirm the only new files are: `docs/SPIKE-REPORT.md` (updated by you with Section G), `docs/SPIKE-PROTOCOL.md` (unchanged), `parsers/fixtures/real_responses/*` (20 fixtures + `case_types.html`), `docs/legal/robots.txt.snapshot`, `docs/legal/{copyright,privacy,hyperlinking}-policy.snapshot.html`, `docs/legal/snapshots/*` (HAR, headers, payload, captcha samples, ratelimit log). Nothing else. |
| 9.4 | Open a PR titled `spike(phase-0): close G1 + G4 inputs`. Tag Arnav, Sneha, Arjun, Maya, Priya, owner. |
| 9.5 | Block on review: Arnav owns G1 close-out call; Sneha owns G2 (after legal review). Arjun cannot start `DelhiHCClient` until G1 closes. |

---

## 10. PII anonymisation reference card (keep open while doing §6)

| Token in source HTML | Action |
|---|---|
| Petitioner name (natural person) | `[REDACTED]` |
| Respondent name (natural person) | `[REDACTED]` |
| Respondent name (government body, e.g. "Union of India", "State of Delhi", "Delhi Municipal Corporation") | **Keep.** Not PII. |
| Respondent name (corporation, e.g. "ACME Ltd", "XYZ Bank") | **Keep.** Not personal data. |
| Advocate / counsel name | `[REDACTED]` |
| Party address | `[REDACTED]` (entire address block) |
| Phone number, email | `[REDACTED]` |
| Aadhaar / PAN / DL number (if ever rendered) | `[REDACTED]` — and flag urgently to Sneha; the court should not be publishing these |
| Case number | Keep |
| Year | Keep |
| Case type label | Keep |
| Hearing dates | Keep (default) — replace with `YYYY-XX-XX` only if a specific party is identifiable by name AND date AND the redaction of name alone is insufficient |
| Court number, bench name (judge) | Keep — public judicial identifier |
| Order / judgment titles | Keep |
| Order / judgment PDF URLs | Keep — court-published documents |

**When in doubt: redact and add a comment in the fixture.** Over-redaction is a parser-tuning cost; under-redaction is a privacy incident.

---

## Verification checklist (final, before declaring spike done)

- [ ] §1 — `form-load.har`, `get-form-headers.png`, `get-form-cookies.png` committed
- [ ] §2 — `submit-payload.png`, `submit.curl.txt`, `_smoke_submit.html` committed
- [ ] §3 — `form-runtime.html`, `form-static.html` committed; CSRF mechanism stated in one sentence in notebook
- [ ] §4 — `captcha-sample-01.*`, `captcha-sample-02.*` committed; TTL range recorded
- [ ] §5 — `case_types.html` committed with 100+ options
- [ ] §6 — ≥12 (target 20) real-response HTMLs in `parsers/fixtures/real_responses/`, all PII-scrubbed
- [ ] §7 — `ratelimit-probe-log.md` committed with recommended rate-limit value
- [ ] §8 — 4 legal snapshots committed; Sneha pinged
- [ ] §9 — `SPIKE-REPORT.md` Section G filled; `STRATEGIES.md` markers replaced
- [ ] PR opened; reviewers tagged; G1 close-out scheduled with Arnav

---

*End of protocol. If any step requires changing the protocol mid-execution, update this file in the same PR and call out the deviation in the PR description.*
