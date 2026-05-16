# Application Security Considerations — Delhi HC Case Tracker (MVP)

**Owner:** Sneha (Security & Compliance reviewer, draft author)
**Status:** Draft for owner / human security architect review.
**Scope:** application-security checklist only. The legal/regulatory analysis lives in `LEGAL-COMPLIANCE.md`; the user-facing privacy text lives in `PRIVACY-NOTICE.md`.
**Date:** 2026-05-17

---

## 1. Threat model in one paragraph

Our backend is a thin proxy between an anonymous public user and the Delhi High Court's public case-status search. We do not store cases. Our most realistic threats are: (a) an attacker uses our service to amplify or attribute abusive traffic to the Court ("we are the path of attack"); (b) malicious or crafted HTML from the upstream (compromise of the court site, or attacker-controlled fields like case-number echoed in the response) injects XSS into our users; (c) SSRF or open-redirect via our outbound fetcher reaches internal infrastructure; (d) admin-side compromise flips the kill switch or rate limits. The rest of this document maps controls to those threats.

---

## 2. Session design (server-side, opaque token)

- **No JWT in the browser.** Sessions are server-side state, identified by a random opaque token (256-bit, CSPRNG).
- **Cookie flags (all of them, no exceptions):**
  - `HttpOnly` — JavaScript cannot read the session cookie.
  - `Secure` — TLS only; never sent on HTTP.
  - `SameSite=Strict` — the cookie does not ride cross-site navigations. Strict (not Lax) is correct here because nothing in our flow is initiated from another origin.
  - `Path=/`, no `Domain` attribute — keep the cookie scoped to the app origin only.
- **Lifetime:** 15 minutes idle, 1 hour absolute. On expiry the server discards the upstream session and the user must re-search.
- **Storage:** session state lives in a server-side store (Redis or equivalent), keyed by the opaque token. On logout / tab close / expiry, the record is hard-deleted.
- **Binding:** session record stores the upstream court-session cookies, the CAPTCHA fetch timestamp, and a hash of the user-agent for sanity-checking. The upstream cookies **never** leave the server.
- **Rotation:** issue a fresh session token after the CAPTCHA is submitted (defends against session fixation).

## 3. CSRF protection on our own POST endpoints

- Every state-changing endpoint (`POST /search`, `POST /captcha/submit`, `POST /admin/*`) requires a double-submit CSRF token:
  - A non-`HttpOnly` cookie carries a random CSRF value.
  - A request header `X-CSRF-Token` must match the cookie value, validated server-side in constant time.
- `SameSite=Strict` on the session cookie is the first line of defence; the CSRF token is belt-and-braces.
- `Origin` and `Referer` headers are validated on every state-changing request; mismatches return `403`.
- GET endpoints have **no side effects**. Search results are returned only via POST so the CSRF token applies.

## 4. XSS hardening — the parsed court HTML is hostile input

**The single largest XSS risk in this MVP is mishandling the upstream HTML.** Two things to internalise:

1. The Delhi HC website could be compromised at any time; we must not assume its output is safe.
2. Some fields (case number, party name) are attacker-influenced — a user could submit `<script>...</script>` as a case number and see it echoed back inside an error string.

Rules — non-negotiable:

- **Never** `innerHTML`, `document.write`, or `dangerouslySetInnerHTML` the upstream HTML. Not even "just a fragment." Not even a `<td>`.
- The backend parses the upstream HTML on the server (e.g. BeautifulSoup / lxml), extracts a fixed set of named string fields (`case_number`, `parties[]`, `next_hearing`, `status`, `bench`, `court_url`), and returns **JSON**. The HTML never reaches the browser.
- The frontend renders those fields via React/Vue text bindings (`{field}`), which auto-escape. No `v-html`, no `dangerouslySetInnerHTML`.
- **CSP** (Content-Security-Policy header) set strictly:
  - `default-src 'self'`
  - `script-src 'self'` (no `'unsafe-inline'`, no `'unsafe-eval'`)
  - `style-src 'self'`
  - `img-src 'self' data:` — `data:` only because the CAPTCHA image is delivered as a data URL from our backend (we fetch the binary, re-serve it; we do not pass through the upstream image URL).
  - `connect-src 'self'`
  - `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`
  - `object-src 'none'`
- Set `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy: interest-cohort=()` and the like, on every response.
- **Output-length caps** on every parsed field (e.g. 500 chars for party names, 2000 for status). Anything longer is truncated and flagged as a parse anomaly. This prevents adversarial blow-up via a compromised upstream.

## 5. Outbound HTTP — SSRF, allowlist, no open redirects

- **Hostname allowlist (hard, not soft).** The outbound fetcher accepts requests only to a configured list of fully qualified hostnames. Anything else throws before the socket opens.
  - **OPEN ITEM:** confirm the canonical hostname(s) of the Delhi High Court case-status endpoint. Provisional pin: `delhihighcourt.nic.in` and any single subdomain we identify (e.g. `services.delhihighcourt.nic.in` — to be verified). No wildcards in production until verified.
- **Scheme allowlist:** HTTPS only. HTTP refused.
- **DNS rebinding defence:** resolve the hostname, validate the resolved IP is **not** in any of: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16` (link-local / cloud metadata), `::1`, `fc00::/7`, `fe80::/10`. Pin the connection to that IP for the duration of the request.
- **No user-supplied URLs ever reach the fetcher.** The user supplies case type / number / year — three short, schema-validated strings. The URL is constructed server-side from the allowlisted base.
- **No open-redirect proxy.** We do not have an endpoint that takes a `url=` parameter and follows it. Outbound URL construction is closed.
- **Redirect handling:** follow at most 3 redirects, and re-apply the hostname allowlist to *every* hop. A redirect to a non-allowlisted host returns a structured error to the frontend.
- **Timeouts:** connect 5 s, read 15 s, total 20 s. No infinite waits.
- **User-Agent:** identifiable, with contact URL (see `LEGAL-COMPLIANCE.md` §4).

## 6. Secrets management

- All secrets in `.env`, never committed. `.env` is in `.gitignore`; ship a `.env.example` with placeholder names only.
- Required secrets at MVP: `SESSION_SIGNING_KEY`, `CSRF_KEY`, `ADMIN_SHARED_SECRET`, `IP_HASH_PEPPER`.
- Rotation policy:
  - Application secrets rotate every 90 days, or immediately on suspected compromise.
  - `IP_HASH_PEPPER` rotates only when we're prepared to invalidate existing hashed IPs (we keep prior peppers in a versioned slot for the 90-day retention window).
- **Pre-commit hook** scans for committed secrets (e.g. `gitleaks` or `detect-secrets`). CI runs the same scanner on every PR; PR is blocked on detection.
- No secret is ever logged. Application logs that need to reference a secret reference its name (`secret=SESSION_SIGNING_KEY`), never its value.

## 7. Log hygiene

- **Never log:** raw CAPTCHA text (image or solution), the full upstream court-session cookie, raw IP addresses, or full case-result payloads.
- **Court session cookies in logs:** first 8 characters + length only, e.g. `court_session=ab12cd34… (len=64)`. This is enough to correlate a session for debugging without leaking the credential.
- **User IPs in logs:** never raw. Log the `sha256(pepper || ip)` hash truncated to 12 hex chars. The pepper is rotated as part of secret rotation.
- **Case search inputs in logs:** redacted by default (`case_query=<redacted>`). A separate, access-controlled audit table holds the search input for the 90-day retention window described in `PRIVACY-NOTICE.md`. Application logs do not duplicate that.
- **Error messages to the user:** generic ("Could not fetch case status. Please try again."). Internal stack traces, hostnames, query parameters, and upstream HTTP bodies stay server-side.
- **Log retention** aligns with the privacy notice: application logs 30 days, then deleted.

## 8. Admin endpoint protection

The admin surface is intentionally tiny: kill switch, rate-limit override, log access. Even so:

- **Shared secret in `Authorization: Bearer <admin-token>`**, validated **in constant time** (`hmac.compare_digest` / `crypto.timingSafeEqual`). Never `==`.
- **IP allowlist** on top of the shared secret. Admin endpoints accept connections only from a small list of source IPs (operator workstation, ops VPN egress). Allowlist lives in config, not code.
- **Aggressive rate-limit**: 10 attempts per IP per hour, regardless of success. Three failed auths in 5 minutes triggers a 24-hour block and an alert.
- **Audit log**: every admin call (success or failure) writes an immutable record with timestamp, source IP, endpoint, and outcome. The audit log is the **one** place where source IP is stored unhashed, for the security purpose of investigating admin compromise. This is documented in the privacy notice as a security-purpose exception.
- **No admin GUI in MVP.** Admin is curl + a runbook. Less attack surface.

## 9. Dependency hygiene

- **CI runs on every PR:**
  - `pip-audit` (Python) — fails the build on any known-vulnerable dependency at High or Critical severity.
  - `npm audit --audit-level=high` (JavaScript) — same bar.
  - License check (no AGPL or unknown-license dependencies in production code).
- **Lockfiles committed.** `requirements.txt` pinned to exact versions, or use a real resolver (`uv pip compile` / `pip-tools`). For Node, commit `package-lock.json` and run `npm ci` (not `npm install`) in CI and prod.
- **Dependabot or equivalent** enabled on the repo. Security updates auto-PR.
- **Supply-chain hardening:** do not pull from unscoped registries; configure the package registry URL explicitly in CI; pin direct dependencies, allow transitive to float within lockfile constraints only.
- **Container base images:** distroless or Alpine, scanned weekly with `trivy` or equivalent. No `latest` tags in production manifests.

## 10. Defence-in-depth: things that are not strictly required but cheap

- **HSTS** header with `max-age=63072000; includeSubDomains; preload` once we are confident in TLS posture.
- **Subresource Integrity (SRI)** on any third-party JS — we should not have any in MVP, but if a CDN font sneaks in, SRI it.
- **Health endpoint** (`GET /healthz`) returns only `{"ok":true}`. No version strings, no build hashes, no environment names. Information disclosure on health endpoints is the most common cheap leak.
- **404 vs 403 vs 401**: consistent, terse responses. Don't reveal which case numbers "exist" via differential error timing or status codes; the case-status search endpoint already enforces that for us, but we should not undo it in our own error layer.

---

## 11. Checklist — pre-launch gate

- [ ] **OPEN ITEM** Hostname allowlist verified against the live court endpoint(s).
- [ ] CSP header verified end-to-end with a real upstream response in staging.
- [ ] Session cookie flags verified in production config (HttpOnly, Secure, SameSite=Strict).
- [ ] CSRF double-submit verified by an automated test that fails when the header is stripped.
- [ ] No raw IPs in any log path (sample 24 hours of staging logs and grep).
- [ ] No CAPTCHA payload in any log path (same sampling).
- [ ] `pip-audit` / `npm audit` clean at High+.
- [ ] Kill switch verified by drill: from "decision" to "all outbound stopped" under 5 minutes.
- [ ] Human security architect sign-off recorded.

**Note (mandatory):** auth-touching and admin-surface changes require human security architect sign-off. This document is a draft until that review.
