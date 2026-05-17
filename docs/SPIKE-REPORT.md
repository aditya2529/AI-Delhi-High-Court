# Phase-0 Reconnaissance Spike Report — Delhi HC Case Tracker

**Status:** Draft v0.1 (spike in-flight) · **Owner:** Arnav (Architecture) · **Date:** 2026-05-17
**Companion:** [`SPIKE-PROTOCOL.md`](./SPIKE-PROTOCOL.md) — the developer-with-browser playbook that closes the unknowns in Section B.
**Scope:** Resolve the three `TO BE VERIFIED IN SPIKE` markers in [`architecture/STRATEGIES.md`](./architecture/STRATEGIES.md), close gates **G1** and **G4** in [`EXECUTIVE-SUMMARY.md`](./EXECUTIVE-SUMMARY.md), and ship a tuned `parse_confidence` floor recommendation for `DHCParserV1`.
**Out of scope:** ToS legal verdict (Sneha, G2), DPDPA counsel opinion (G3), tester recruitment (G5), `DelhiHCClient` implementation (Arjun, post-spike).

---

## Section A — Observable surface (verified 2026-05-17 via WebFetch)

> Source: Claude orchestrator WebFetch session, 2026-05-17. **Limitation:** WebFetch is stateless — no cookie jar, no JS execution, no image bytes, no form-POST cycle. Everything below is HTML-render-time observable only. All session/wire/binary unknowns are deferred to Section B.

### A.1 Confirmed URLs

| Purpose | URL | Method observed |
|---|---|---|
| Homepage | `https://delhihighcourt.nic.in/` | GET 200 (text/html) |
| Case-status form | `https://delhihighcourt.nic.in/app/get-case-type-status` | GET 200 (form rendered) |
| Privacy policy | `https://delhihighcourt.nic.in/web/privacy-policy` | GET 200 |
| Copyright policy | `https://delhihighcourt.nic.in/web/copyright-policy` | GET 200 |
| Hyperlinking policy | `https://delhihighcourt.nic.in/web/hyperlinking-policy` | GET 200 (full text captured) |
| Accessibility statement | `https://delhihighcourt.nic.in/web/accessibility-statement` | GET 200 |
| Loading indicator asset | `https://delhihighcourt.nic.in/app/public/spin.gif` | inferred from markup |

**Implication for SSRF allowlist (`DHC_HOSTNAME_ALLOWLIST`):** a single host `delhihighcourt.nic.in` covers both the Drupal CMS (`/web/*`) and the case-status app (`/app/*`). No subdomain split observed at the surface layer. Keep the allowlist pinned to a single host until the protocol confirms there are no cross-host redirects (e.g. to a captcha-issuing subdomain).

### A.2 Tech stack inferred from markup

- **CMS layer:** Drupal — confirmed by `/web/themes/delhihighcourt/` asset paths in the rendered HTML.
- **Hosting:** NIC infrastructure (`.nic.in` TLD; consistent with other Indian government court sites on the same chassis).
- **App layer for `/app/*`:** likely PHP backed by the same Drupal install, but not confirmed. No ASP.NET viewstate fields, no Java `jsessionid` in URLs, no obvious framework fingerprint in headers (headers not seen — see B.1).
- **Frontend:** server-rendered HTML with vanilla JS shims (`playAudio()`, refresh button handler). No SPA framework observed.

**Implication:** No JS execution should be required to submit the form. The default tool is `httpx.AsyncClient` with manual cookie jar; Playwright/Selenium is a contingency only if the protocol finds a JS-issued CSRF or CAPTCHA URL (see B.3, B.4).

### A.3 Form structure — `/app/get-case-type-status`

| Field | HTML control | Confirmed values | Notes |
|---|---|---|---|
| Case Type | `<select>` | `ADMIN.REPORT`, `ARB.A.`, `BAIL APPLN.`, `CA`, `CRL.A.`, `W.P.(C)` (sample) — 100+ options total | Full enum must be captured byte-for-byte by the developer (see B.5). The synthetic parser already normalises via `re.sub(r"[^A-Z0-9]", "", ...)` ([`fake_court_client.py:57`](../backend/app/clients/fake_court_client.py)) so dot/paren punctuation is harmless to the parser. It is **not** harmless to the upstream POST — the value submitted must match the upstream `<option value="...">` exactly. |
| Case Number | `<input type="text">` | n/a | No validation pattern observed in markup; assume server-side validation only. |
| Year | `<select>` | 1952 → 2026 | 75-year range. Frontend should pre-filter to plausible years per case type if we later add UX polish; backend should accept the full range. |
| CAPTCHA | `<input type="text">` | placeholder seed `2049` seen in inspected HTML | Whether `2049` is a literal seed for that session or a placeholder example is unverified. See B.4. |
| Hidden/CSRF | **none visible in rendered HTML** | — | **This is the single highest-risk unknown for Arjun's `DelhiHCClient`.** Three plausible explanations: (1) the token is set as a Set-Cookie at GET time and the form simply re-sends it as `Cookie` on POST (no body field); (2) a client-side JS handler injects a hidden field at submit time (would require JS execution); (3) the token is added by an XHR before POST and the form is then submitted with it. The protocol must determine which. |
| Form action URL & method | **not declared in rendered markup** | — | The `<form>` element either had no `action`/`method` attribute (defaults to current URL + GET) or was constructed by JS. Almost certainly the real submit is POST. Must be verified in DevTools (B.2). |

### A.4 CAPTCHA — observable

- Image-based, with `<audio>` accessibility fallback (the `playAudio()` JS function is attached to the form). Honour this in our UI — surface the audio control too, not just the image, so the wrapper does not degrade accessibility relative to the source site.
- Has a refresh button (markup visible). Refresh endpoint URL is **not** visible in static HTML — discover in B.4.
- Numeric placeholder `2049` may be the literal CAPTCHA seed for the session WebFetch saw, OR a sample. If it is the seed, the CAPTCHA scheme is numeric-only (not alphanumeric), which would simplify both our placeholder UI and the synthetic `FakeCourtClient` generator.
- MIME, dimensions, byte length: **unknown** (binary; WebFetch cannot retrieve).

### A.5 User-facing disclaimer on the form page (verbatim)

> "The content of this site is only for information purpose. Users are advised not to depend on the information and use it for official purpose."

**Implication for us:** the Court itself disclaims authoritative-ness on its own published case-status output. Our "Unofficial — Court page is authoritative" badge (risk R7 in [`EXECUTIVE-SUMMARY.md`](./EXECUTIVE-SUMMARY.md)) is therefore not over-cautious; it is consistent with the source's own posture. Sara should mirror this language closely in the UI disclaimer.

### A.6 Hyperlinking policy — verbatim relevant clauses

- **Linking:** ALLOWED — *"We do not object to you linking directly to the information that is hosted on this website and no prior permission is required for the same."* Notification is requested but not mandatory.
- **Framing:** PROHIBITED — *"we do not permit our pages to be loaded into frames on your site. The pages belonging to this website must load into a newly opened browser window of the User."*
- **Programmatic access / scraping:** NOT MENTIONED in the hyperlinking policy.
- **Third-party proxy with user-typed CAPTCHA:** NOT MENTIONED.

See Section E for the engineering interpretation.

---

## Section B — Open unknowns (developer-with-browser must close)

Each row: the unknown, the smallest experiment, where the protocol step lives, and the **blocking severity** for Arjun's `DelhiHCClient`.

| # | Unknown | Smallest experiment | Protocol step | Blocks `DelhiHCClient`? |
|---|---|---|---|---|
| B.1 | Full HTTP cycle: cookies set on GET, response headers, redirect chain, content-type, content-length | Open form URL in Chrome DevTools → Network tab → preserve log → reload → export HAR | [Protocol §1](./SPIKE-PROTOCOL.md#1-capture-the-full-http-cycle) | **Yes — high.** Cookie names are session-store schema input. |
| B.2 | Form `action` URL, HTTP method, exact body parameter names/casing | DevTools Network → submit the form once with any data → inspect the request line + payload | [Protocol §2](./SPIKE-PROTOCOL.md#2-determine-real-form-action--method) | **Yes — high.** Without this, `submit_search` cannot be implemented. |
| B.3 | CSRF / state-token mechanism (cookie? hidden field injected by JS? XHR-fetched?) | Diff the GET-rendered HTML against the runtime DOM (`document.documentElement.outerHTML` in console); diff cookies before/after submit | [Protocol §3](./SPIKE-PROTOCOL.md#3-determine-csrfstate-token-mechanism) | **Yes — critical.** This is the make-or-break for whether the chosen `httpx`-only path is viable, or whether we must switch to a headless browser. |
| B.4 | CAPTCHA: refresh endpoint URL, image MIME, dimensions, byte length, whether numeric-only or alphanumeric, TTL before upstream rejects | DevTools → click refresh → observe the new GET; submit with deliberate delay (30s, 60s, 120s, 180s) to find expiry boundary | [Protocol §4](./SPIKE-PROTOCOL.md#4-determine-captcha-ttl--refresh-path) | **Yes — high.** `STRATEGIES.md §2` assumes 90s — must confirm or update. |
| B.5 | Full Case Type enum (byte-for-byte) | Right-click `<select>` → Inspect → copy outerHTML → save as `parsers/fixtures/real_responses/case_types.html` | [Protocol §5](./SPIKE-PROTOCOL.md#5-capture-the-case-type-enum) | **Yes — medium.** Without the full list we cannot validate input nor map user-facing labels. |
| B.6 | 20 representative result-page HTMLs (pending, disposed, multi-petitioner, no-orders, reserved, transferred, withdrawn, dismissed-in-limine, etc.) | Manual searches across known cases or sampled (number, year) tuples; save raw HTML + screenshot; anonymise PII | [Protocol §6](./SPIKE-PROTOCOL.md#6-capture-20-representative-result-pages) | **Indirectly — blocks G4 (parser quality gate), not the client surface.** |
| B.7 | Rate-limit behaviour: at what req/s does latency degrade, 4xx appear, or IP-ban trigger; recovery time from a soft block | Pace requests 0.33 → 1 → 2 req/s for 60s windows; stop at first sign of degradation | [Protocol §7](./SPIKE-PROTOCOL.md#7-probe-rate-limit-gently) | **Yes — medium.** Drives `DHC_OUTBOUND_RATE_LIMIT_PER_SEC` default and circuit-breaker tuning. |
| B.8 | `/robots.txt` content (verbatim) | `curl -sS https://delhihighcourt.nic.in/robots.txt` → save under `docs/legal/robots.txt.snapshot` | [Protocol §8](./SPIKE-PROTOCOL.md#8-snapshot-robotstxt-and-legal-pages) | **Yes — critical.** `is_path_allowed_by_robots` cannot be implemented without it; G2 (Sneha) cannot close without it. |
| B.9 | `/web/copyright-policy` and `/web/privacy-policy` verbatim content | `curl -sS` snapshots → save under `docs/legal/` | [Protocol §8](./SPIKE-PROTOCOL.md#8-snapshot-robotstxt-and-legal-pages) | **No for `DelhiHCClient`; Yes for G2/G3.** Hands off to Sneha. |
| B.10 | Does any redirect cross hosts (e.g. captcha-issuing subdomain, CDN)? | HAR file from B.1 contains the redirect chain | covered by [Protocol §1](./SPIKE-PROTOCOL.md#1-capture-the-full-http-cycle) | **Yes — medium.** Drives whether `DHC_HOSTNAME_ALLOWLIST` stays single-host. |

**→ Sneha trigger:** B.8 and B.9 must land in `docs/legal/` for her G2 review. Flagging here unprompted.

**→ Rohit trigger:** the cookie names from B.1 land in the `sessions.upstream_cookies` JSON field schema — Rohit needs to know the keys to write a useful index/lookup on them if observability ever needs to query by upstream session.

---

## Section C — Tuned parser confidence floor recommendation

### C.1 What the current floor logic does

`DHCParserV1._compute_confidence` ([`case_parser.py:310`](../backend/app/parsers/case_parser.py)) starts at **0.40** (parties + user-supplied identity present, which is the only thing guaranteed when extraction reaches it) and adds:

| Component | Δ | Cumulative if present |
|---|---|---|
| Base (parties + identity) | 0.40 | 0.40 |
| `status` | +0.10 | 0.50 |
| `last_hearing_date` | +0.05 | 0.55 |
| `next_hearing_date` | +0.05 | 0.60 |
| `court_no` | +0.05 | 0.65 |
| `judge_bench` | +0.05 | 0.70 |
| `orders` OR `judgments` present | +0.25 | 0.95 → clamped 1.0 with all bonuses |

The synthetic golden fixtures land at: `WPC_12345_2024.html` ≥ 0.95 (full case), `CRLMC_999_2023.html` ≥ 0.95 (disposed + judgment), `FAO_1_2025.html` around 0.55-0.60 (fresh case, no orders, has next-hearing).

### C.2 The recommendation — floor at `0.55`

**Set `MIN_DISPLAY_CONFIDENCE = 0.55` in the route layer.** Below that, the frontend renders the "couldn't read reliably — open court site" view; at or above it, render the structured `ParsedCase` plus the source-URL fallback link.

### C.3 Why 0.55 and not 0.70 (the strict band) or 0.40 (the base)

| Candidate floor | Pros | Cons |
|---|---|---|
| **0.40** (base = parties + identity only) | Maximum coverage — anything with parties displays | Misses the qualitative bar: a "case page" with literally only parties and no status/hearing/orders is not useful to the lawyer and erodes trust. Equivalent to "we showed you something we couldn't really read." |
| **0.55** ← recommended | Demands status OR (last+next-hearing) OR (status + one hearing date), which is the *minimum useful case page*. Lets fresh cases with `FAO_1_2025.html`-shaped data through. Honours the "≥70% first-attempt parse" success metric in [PRD](./prd/PRD.md) by not over-rejecting. | Lets through pages where orders/judgments couldn't be extracted but identity/status could — these will look thin in the UI. Mitigated by the source-URL link being mandatory on every render. |
| **0.70** (strict golden-fixture band) | Only displays high-quality parses. Looks great on the happy path. | Rejects fresh cases (no orders yet) — exactly the segment whose lawyers most need updates. Would tank the "70% first-attempt parse" metric. |

### C.4 Defence — the load-bearing assumption

The floor assumes the **synthetic fixtures are representative of the real distribution's *shape***, even though real-fixture *selectors* will need to be rewritten in `DHCParserV1` post-B.6. Specifically, the weight that `orders OR judgments` carries **0.25** of the total confidence assumes that real cases without orders are valid (fresh filings) and should not be penalised heavily on the "no orders" axis alone.

**Post-spike re-tune trigger:** if the 20 real fixtures from B.6 reveal that real cases routinely have a `parser_degraded=true` path because (e.g.) parties are present but split into nested tables our extractor doesn't reach, the **base 0.40** is wrong and we re-tune. Specifically, if more than 4/20 real fixtures produce a confidence < 0.55 because of structural mismatch (not field absence), bump the parser version, fix selectors, and re-run before changing the floor.

**Adjustment rule:** if real fixture confidences cluster bimodally — say 8 at ≥ 0.70 and 12 at ≤ 0.45 with nothing in between — the floor of 0.55 is dividing the dataset cleanly and we keep it. If they cluster around 0.50-0.65 (continuous), bump the floor to 0.60 to err on the side of trust.

### C.5 Telemetry the floor depends on

Add a counter `parse_confidence_bucket_total{bucket=...}` with buckets `[0-0.4, 0.4-0.55, 0.55-0.7, 0.7-1.0]` so we can see the live distribution and prove (or kill) this floor in the pilot. This is a Maya story, not a Sprint 1 blocker.

---

## Section D — Implementation implications for `DelhiHCClient`

What the real client needs that `FakeCourtClient` ([`fake_court_client.py`](../backend/app/clients/fake_court_client.py)) cleanly avoids today. Cross-references [`STRATEGIES.md §1, §2, §3`](./architecture/STRATEGIES.md).

### D.1 Cookie jar pinned to one host

- A single `httpx.AsyncClient(base_url=DHC_BASE_URL, cookies=cookies)` per `CourtSession` for the duration of `init_session` → `fetch_captcha` → `submit_search`.
- The cookie jar must be **scoped to `delhihighcourt.nic.in` only**. If B.10 reveals cross-host redirects, the jar must reject cookies from other hosts (`httpx` default behaviour) and the SSRF allowlist must accept the additional host explicitly.
- Cookies are stored in `sessions.upstream_cookies` as JSON, with key names discovered in B.1. **Never log them** (already a denylist in `STRATEGIES.md §1`).

### D.2 CAPTCHA refresh endpoint discovery

- `STRATEGIES.md §2` mandates that refresh is "only step 2" of the original fetch (re-GET the image URL only, do not re-init). This requires that the CAPTCHA image URL is stable across the session — i.e. the same URL returns a new image without re-establishing cookies. **Verify in B.4.** If the URL changes per refresh, the session must store the latest image URL on every refresh, not just on init.
- If B.4 reveals that the CAPTCHA is bound to a per-image token (e.g. URL `?token=<n>`), the refresh response body or response cookies must update that token in the session before the next submit.

### D.3 Retry budget per session

- 3 CAPTCHA-failed retries on the same session (already in `attempts_used` per `STRATEGIES.md §1`). After the third, the session is forcibly retired and the user starts over with a fresh `init`.
- The outbound rate limiter is **per-process**, not per-session. A user who refreshes the CAPTCHA 3 times in 10 seconds still counts as 3 outbound GETs against the global budget. At `DHC_OUTBOUND_RATE_LIMIT_PER_SEC=0.33` (1 per 3s), this means the third refresh of the same session waits ~6 seconds; surface that in the UI as a "please wait" hint.

### D.4 Per-session header pinning

- Real browsers send a stable `User-Agent`, `Accept`, `Accept-Language`, and `Referer` chain. The court site may key its rate-limit / WAF on UA stability. Pin a single canonical `User-Agent` per deployment (config var `DHC_USER_AGENT`, default to a recent Firefox UA; never randomise across requests in the same session — that pattern is itself a fingerprintable anomaly).
- `Referer` on the form POST should be the form GET URL — this is normal browser behaviour and may matter for CSRF acceptance even if the token is cookie-only.

### D.5 robots.txt is a kill switch, not a hint

`is_path_allowed_by_robots(path)` must:
- Fetch `/robots.txt` once per process startup (and on receipt of SIGHUP, when we add config reload).
- Parse with Python's stdlib `urllib.robotparser` (battle-tested; we do not need `reppy`).
- Cache the parsed result in-process; do not re-fetch on every request.
- Return `False` → caller raises `CourtBlockedError` → the route returns the `upstream_blocked` error code per [`API-CONTRACT.md`](./api/API-CONTRACT.md).

### D.6 Timeout budget

- Per-call timeouts: `connect=5s`, `read=10s` for HTML pages; `read=5s` for CAPTCHA image. Total request budget: 30s per outbound call. These are starting numbers and may be retuned after B.7.
- Across the search flow: `init_session` ≤ 8s p95, `submit_search` ≤ 10s p95. End-to-end UI budget is 12s median per [`EXECUTIVE-SUMMARY.md §11`](./EXECUTIVE-SUMMARY.md) — we have headroom only if upstream is responsive.

### D.7 Error mapping

| Upstream symptom | Raises | Route maps to (per [API-CONTRACT.md](./api/API-CONTRACT.md)) |
|---|---|---|
| Connection error, 5xx | `CourtClientError` | `503 court_error`, retryable |
| robots.txt deny OR allowlist reject OR take-down notice in body | `CourtBlockedError` | `503 upstream_blocked`, not retryable until `Retry-After` |
| Page contains "Invalid Captcha" | `CaptchaIncorrectError` (raised by parser sentinel, not transport) | `200 {status: "captcha_failed"}` |
| 429 from court | `CourtClientError` with `retry_after` | `429 rate_limited`, retryable after delay |
| Kill switch off | `OutboundDisabledError` | `503 upstream_blocked`, not retryable |

### D.8 What we explicitly do NOT do

- No CAPTCHA OCR (ADR-003, hard line).
- No request retry on the same CAPTCHA token — a failed CAPTCHA invalidates the token; the client must call `/refresh-captcha`.
- No client-side caching of cookies/CAPTCHA in the browser — server-side session only.
- No connection pooling across sessions — one `AsyncClient` per session, closed on session retirement, because shared pools blur upstream session boundaries.

---

## Section E — Legal posture (engineering interpretation)

**Status:** **Engineering interpretation — confirm with counsel** (Sneha pattern). This section informs but does not substitute for G2/G3 sign-off.

### E.1 What the policies say (Section A.6 above + Section A.5)

- Linking to the court site is explicitly permitted.
- Framing is prohibited.
- The court itself disclaims authoritativeness on its own published case-status output.
- Programmatic access (scraping, automated form-fill, third-party form proxies) is not mentioned in the hyperlinking policy. The robots.txt content has not been read yet (B.8).

### E.2 Engineering interpretation — what this implies for our build

| Question | Engineering answer | Confidence |
|---|---|---|
| Are we allowed to display a permalink to the court's case-status URL alongside our parsed result? | **Yes** — directly supported by the hyperlinking policy. This is already required by `STRATEGIES.md §3` (every parsed result carries `source_url`). | High |
| Are we allowed to embed the court page in an iframe? | **No.** The framing prohibition is explicit. Our UI is server-side-rendered and never frames the court page. Verify in Sara's UI review. | High |
| Are we allowed to programmatically fill the form on behalf of a user who solves the CAPTCHA themselves? | **Defensibly yes, contingent on G2 (Sneha + counsel).** Argument: (a) the user is the principal actor — they typed the case identifier and solved the CAPTCHA; we are a UI proxy, not an autonomous scraper; (b) we respect robots.txt as a kill switch; (c) we rate-limit ourselves below the rate a human-with-browser hits the site; (d) we publish a take-down email and a kill switch. **Counter:** if `/robots.txt` (B.8) disallows the `/app/get-case-type-status` path or any of its sibling endpoints, this interpretation collapses and the product is killed pre-launch. | **Medium — pending B.8 + counsel** |
| Are we allowed to cache the parsed result for 24h (`PARSED_CASE_CACHE_TTL_SECONDS=86400`)? | **Engineering-defensible**: we are caching a derivative work (structured extraction) of publicly disclaimed-as-non-authoritative content, attributed back to its source on every render. The court page itself updates infrequently for any single case (typically post-hearing-day), so 24h is a reasonable freshness boundary that materially reduces our footprint on the court's servers (a courtesy that *strengthens* our compliance posture). **Counter:** counsel may require an explicit "this snapshot is at most 24h old, refresh to verify" hint in the UI. Sara's job to surface if confirmed. | Medium |
| Are we allowed to log raw HTML for debugging? | **Yes, with PII discipline:** only on parser failure, sampled, with SHA-256 + ≤1KB head (already in [`STRATEGIES.md §4`](./architecture/STRATEGIES.md)). Cookies and CAPTCHA text are denylisted from logs. | High |

### E.3 What we do NOT claim

- We do not claim DPDPA Data-Fiduciary status is settled — that is G3, owner + counsel.
- We do not claim ToS compliance — that is G2, Sneha + counsel.
- We do not claim a copyright posture on the parsed case data or linked PDFs — that requires reading `/web/copyright-policy` (B.9) which is still gapped.

### E.4 Take-down preparedness

Independent of the legal verdict, we have already built:
- A global kill switch (`OUTBOUND_FETCH_ENABLED`) flippable in < 5 min (verified in `FakeCourtClient` already — see `_guard_outbound_enabled` at [`fake_court_client.py:222`](../backend/app/clients/fake_court_client.py)).
- A `CourtBlockedError` taxonomy distinct from generic upstream failures, so a take-down can be logged and surfaced as `upstream_blocked` to users without a code change.
- An SSRF hostname allowlist that prevents any accidental drift to other government hosts.
- A take-down email obligation in §6 open question #7 in [`EXECUTIVE-SUMMARY.md`](./EXECUTIVE-SUMMARY.md).

**This is the strongest defensive position we can engineer; the legal verdict is the load-bearing complement.**

---

## Section F — Spike completion criteria (gate G1 closes when…)

The spike is **complete** when all of the following are simultaneously true:

1. The 10 protocol steps in [`SPIKE-PROTOCOL.md`](./SPIKE-PROTOCOL.md) have evidence committed (HAR file, raw HTMLs, robots snapshot, rate-limit log).
2. The three `TO BE VERIFIED IN SPIKE` markers in [`STRATEGIES.md`](./architecture/STRATEGIES.md) are resolved with verbatim findings appended here as Section G (to be written by the developer at the end of day 2).
3. The 20 anonymised result HTMLs are committed to `parsers/fixtures/real_responses/`.
4. The Case Type enum is committed to `parsers/fixtures/real_responses/case_types.html`.
5. `DHCParserV1` has been re-pointed at one real fixture as a smoke test and the parse outcome is recorded (G4 only fully closes when ≥ 16/20 succeed, which is Arjun's post-spike work — not this report's bar).
6. Sneha has been pinged with `docs/legal/robots.txt.snapshot`, `docs/legal/copyright-policy.snapshot.html`, `docs/legal/privacy-policy.snapshot.html`.

---

## Section G — Findings appendix (to be written by developer at end of spike)

> Reserved. The developer executing `SPIKE-PROTOCOL.md` appends verbatim findings here, keyed back to each B-row. Format: one subsection per B-unknown, "What we expected" / "What we observed" / "Decision". After this section is filled, the spike report is re-circulated to Arjun, Sneha, Maya, and the owner for G1 close-out.

---

*End of report.*
