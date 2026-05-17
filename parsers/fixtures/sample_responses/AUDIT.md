# Synthetic Fixture Audit vs Spike Findings

**Status:** Pre-B.6 placeholder audit · **Auditor:** Maya (QA) · **Date:** 2026-05-17
**Inputs:** `docs/SPIKE-REPORT.md` §C (stateful recon) + §G (per-unknown
resolution map), `scripts/dev/spike_recon_output.json`
**Goal:** rank each synthetic fixture for structural plausibility against
what Arnav observed on the live court site. This audit feeds the post-B.6
real-fixture replacement work — it does NOT itself rewrite the fixtures.

> The synthetic fixtures here are placeholder-quality by design. Until the
> 20 anonymised real HTMLs land under `parsers/fixtures/real_responses/`,
> the parser is being developed against this stylised schema. The audit
> below flags every assumption baked into the synthetics that the live
> site is known (post-spike) to contradict, so that when real fixtures
> arrive the parser-rewrite work has a head start.

## Severity legend

| Severity | Meaning |
|---|---|
| **BLOCKER** | The parser would mis-classify or crash on the real page; this fixture is actively misleading. |
| **NICE-TO-FIX** | Plausible enough to develop against; real-page shape differs in known ways but parser would still match on the load-bearing markers. |
| **OK** | Structurally close enough to the live site that no urgent action is needed. The fixture will still be replaced post-B.6 but the divergence is cosmetic. |

## Site-wide divergences (apply to every synthetic in this directory)

Pulled from SPIKE-REPORT §A + §G. These are known *true* of the live site
and known *false* of every fixture here, but they don't break the parser
contract by themselves — they're the wrapping layer the parser ignores.

| Divergence | Live site (per spike) | Every synthetic fixture | Parser impact |
|---|---|---|---|
| Server stack | Apache + Laravel | none declared | none (parser is HTML-shape-only) |
| Set-Cookie on GET | `XSRF-TOKEN` + `hc_application_session` | none | none (parser doesn't see cookies) |
| Security headers | `strict-transport-security`, `x-frame-options: SAMEORIGIN`, `x-content-type-options: nosniff`, `cache-control: no-cache, private` | none | none (parser doesn't see headers) |
| `<form>` element | **JS-rendered — 0 `<form>` tags in static HTML** | most fixtures have no form (correct by accident); none have JS | none for parser; matters for the future client |
| Drupal/theme assets | `/web/themes/delhihighcourt/...` on CMS pages | none referenced | none |
| Case-status app path | `/app/get-case-type-status` | source URLs in fixtures are stub `delhihighcourt.example/...` | none for parser (source_url is just echoed back) |
| CAPTCHA endpoint discovery | `/app/getCaptcha`, `/app/generate-captcha`, `/app/validateCaptcha` | none | none (parser sees the result page, not the CAPTCHA flow) |

**Headline:** the spike confirmed the parser-relevant shape (server-rendered HTML
result page emitted as the POST response) is structurally addressable; what
the synthetics ARE missing is wrapping infrastructure the parser does not
inspect. **No blanket BLOCKERs from these.**

## Per-fixture verdicts

### `WPC_12345_2024.html` — pending W.P.(C), 1 petitioner / 3 respondents / 2 orders

**Severity:** NICE-TO-FIX

- HTML shape plausible vs the parser contract documented in `case_parser.py`
  (class-named cells inside `<table.case-details>`, parties rows with
  `tr.party.petitioner|.respondent`, orders in `<table.orders>`).
- **Real-site assumptions NOT yet validated:**
  - Whether the live result page actually uses `<table>`-of-rows for case
    details or a key/value `<dl>` / div-grid. The spike captured the FORM
    page, not a result page (B.6 still pending).
  - The order-link `<a href>` points to a `delhihighcourt.example/...`
    stub. Real orders are PDFs served from court infrastructure
    (likely under `/app/...` or a CDN). Parser should already handle
    arbitrary href — verified in the orders-extraction test path.
  - `case-title` `<h2>` heading uses the format `W.P.(C) 12345/2024`.
    Whether the live page uses this exact format is unverified; the
    parser doesn't currently key on it, so this is decorative-only.
- No `<form>` element present — accidentally correct vs the JS-rendered
  live form, but it's also not the page the user would actually see
  (this is the *result* page, post-submit).
- **No BLOCKER** for parser development today.

### `CRLMC_999_2023.html` — disposed CRL.M.C., 3 orders + 1 judgment

**Severity:** NICE-TO-FIX (same shape as WPC_12345_2024)

- Same caveats as WPC fixture above — `<table>` shape assumption is the
  load-bearing unknown until B.6 lands.
- Disposed-state status text "DISPOSED" matches a plausible upstream
  enum but the live court's exact wording (`Disposed`, `DISPOSED OFF`,
  `Disposed of`, etc.) is unverified. The parser stores the raw string
  so any drift is data, not a structural break.
- `next-hearing-date` is empty — good test for "disposed cases have no
  next hearing" path.
- `<table.judgments>` with `tr.judgment` rows — sibling structure to
  orders. Whether the live site groups orders + judgments separately or
  in one combined table is unverified. **Flag for re-validation post-B.6.**

### `FAO_1_2025.html` — fresh case, no orders, no court_no/bench/last_hearing

**Severity:** OK

- This is the canonical at-floor fixture (post-spike floor 0.55 — see
  `PARSER_CONFIDENCE_FLOOR` in `case_parser.py`).
- "No orders passed yet." placeholder row with `td.no-orders` class —
  the parser ignores rows that don't match `tr.order`, so this is safe.
- Uses `<td class="role">Appellant</td>` — exercises the synonym path
  in `_infer_party_role` (appellant → petitioner). Good adversarial
  coverage of vocabulary normalisation.
- Empty `<td class="last-hearing-date"></td>` — proves the `_cell_text`
  empty-string-to-None normalisation path. Don't change this in the
  real-fixture replacement.
- No BLOCKER. **Treat as a regression anchor** when real fixtures land.

### `NOTFOUND.html` — sentinel: "No records found"

**Severity:** NICE-TO-FIX

- Uses `<div class="alert alert-info no-records-found">` — matches the
  parser's `_NOT_FOUND_SELECTORS` tuple precisely.
- **Risk:** the live court site might emit "No records found" as a plain
  `<p>`/`<h1>` without the `.no-records-found` class, OR use entirely
  different copy (`No Data Found`, `No matching cases`, etc.). The
  sentinel classifier ALSO requires the text "no records found" to
  appear inside the matched element, which is brittle.
- **Action post-B.6:** capture the real not-found page; verify the exact
  copy + class hooks. Update `_NOT_FOUND_SELECTORS` + the phrase check
  if either differs.
- No BLOCKER today — the synthetic is structured exactly the way the
  parser expects.

### `CAPTCHA_FAILED.html` — sentinel: "Invalid Captcha"

**Severity:** NICE-TO-FIX

- Uses the exact phrase "Invalid Captcha" which matches
  `_CAPTCHA_FAILED_PHRASE = "invalid captcha"` after the parser's
  lowercase normalisation.
- **Risk:** the live court likely uses different copy. Bootstrap-style
  alerts are common, but spike-discovered endpoint `/app/validateCaptcha`
  (per SPIKE-REPORT §G) is a *separate* POST. The CAPTCHA may be
  validated server-side BEFORE the result page is rendered — meaning a
  failed CAPTCHA might never produce a "result page" at all; it might
  return a JSON error or a redirect.
- **Open question for Arjun/dev-with-browser (B.4):** does a wrong
  CAPTCHA come back as (a) a result page with an "Invalid Captcha"
  banner, or (b) a non-200 from `/app/validateCaptcha` that the client
  short-circuits before ever invoking the parser? If (b), this fixture
  is testing a code path that doesn't exist in the live flow.
- **Severity stays NICE-TO-FIX** because the parser-side classification
  is still defensive belt-and-braces — if the upstream ever does serve
  an HTML banner, we want to catch it.

### `COURT_ERROR.html` — synthetic 500

**Severity:** NICE-TO-FIX

- Uses `<div class="error-page">` with `<h1>500</h1>` — matches the
  parser's `_COURT_ERROR_SELECTORS` + `_COURT_ERROR_HEADINGS` tuple.
- **Risk:** the live Apache error page (per `server: Apache` in
  SPIKE-REPORT §G) almost certainly does NOT carry `.error-page` — it
  would be a default Apache 500 page (`<h1>Internal Server Error</h1>`,
  no semantic classes) OR a Laravel error page (`<title>500 ...`).
- Apache's default 500 wouldn't match `.error-page` class but WOULD
  match the heading text via the fallback once we drop the class
  requirement. Today the parser requires the class first → it would
  miss a real Apache 500 and fall through to `_extract_case`, which
  would then raise `_ParserHardFailure` (no case-details table) → flips
  `parser_degraded=True`. **End result is similar** (user sees "couldn't
  read") but the body-level `status` would be `success` (degraded),
  not `court_error`. That's a behavioural drift worth fixing post-B.6.
- **Action post-B.6:** the real client should classify 5xx upstream
  responses at the **transport** layer (`CourtClientError`) before they
  ever reach the parser. Then this fixture is a belt-and-braces
  fallback for HTML-formatted error pages only.
- No BLOCKER today.

### `BROKEN.html` — totally malformed HTML

**Severity:** OK

- Intentionally malformed (unclosed tags, no case-details table, random
  prose). Exercises the `_ParserHardFailure` → `empty_parse` path.
- Real-site equivalent would be a truncated response (network mid-stream
  drop, gzip corruption, response-size limit). Parser must not crash on
  any of these and this fixture proves it.
- No action needed — keep this as a permanent adversarial fixture even
  after real fixtures land.

## Headline counts

| Severity | Count | Files |
|---|---|---|
| BLOCKER | 0 | — |
| NICE-TO-FIX | 5 | WPC_12345_2024.html, CRLMC_999_2023.html, NOTFOUND.html, CAPTCHA_FAILED.html, COURT_ERROR.html |
| OK | 2 | FAO_1_2025.html, BROKEN.html |

**Total fixtures audited:** 7

## What this audit does NOT do

- Does not change any fixture file. The replacement happens post-B.6.
- Does not assert pass/fail in CI — these are forward-looking notes,
  not test gates. The existing parser tests in
  `backend/tests/unit/test_parser.py` already gate parser regressions
  on these fixtures.
- Does not cover the 13 case-result page shapes the spike protocol
  flags as "representative" (pending, disposed, multi-petitioner,
  no-orders, reserved, transferred, withdrawn, dismissed-in-limine,
  etc.). Coverage of those shapes is the responsibility of the 20
  real fixtures captured in B.6 — see `docs/SPIKE-PROTOCOL.md` §6.

## Trigger list — actions on B.6 close

When the 20 anonymised real fixtures land under
`parsers/fixtures/real_responses/`:

1. Run `scripts/dev/parser_fixture_replay_harness.py` against each
   real fixture and capture the confidence + outcome distribution.
2. If ≥4/20 produce `parser_degraded=true` due to structural mismatch
   (not field absence), bump the parser version per SPIKE-REPORT
   §C.4 adjustment rule and rewrite selectors before re-tuning the
   confidence floor.
3. Re-verify sentinel classification (NOTFOUND, CAPTCHA_FAILED,
   COURT_ERROR) against the real equivalents — update phrase /
   selector tuples in `case_parser.py` accordingly.
4. Move the 7 synthetic fixtures here to
   `parsers/fixtures/sample_responses/_archived/` rather than
   deleting them — they retain value as a self-contained smoke
   suite the parser is known to pass.
