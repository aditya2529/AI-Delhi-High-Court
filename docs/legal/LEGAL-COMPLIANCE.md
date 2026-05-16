# Legal & Compliance Posture — Delhi HC Case Tracker (MVP)

**Owner:** Sneha (Security & Compliance reviewer, draft author)
**Status:** Draft for owner review — not legal advice.
**Date:** 2026-05-17

> **Disclaimer:** This document is an *engineering interpretation* of the regulatory landscape, prepared by a software reviewer, not a lawyer. Every statement below labelled **Engineering interpretation — confirm with counsel** is a working hypothesis that must be validated with qualified Indian legal counsel before public launch. **OPEN ITEM** markers flag facts we have not verified yet and that block launch sign-off.

---

## 1. What the product does (recap, for the legal frame)

The Delhi HC Case Tracker is a thin, polite client over the **publicly accessible case-status search** offered by the Delhi High Court website. The user supplies case type, case number and year. Our backend opens a session against the court site, fetches the court's CAPTCHA image, **shows it to the human user**, the user types the answer themselves, our backend submits the form in that same session, parses the returned HTML into structured JSON, and returns it.

Key facts that drive the legal analysis:

- **No CAPTCHA bypass.** No OCR. No solver model. The human solves every CAPTCHA. The CAPTCHA is the court's access-control gate and we honour it.
- **No bulk scraping.** One search = one outbound request, triggered by an interactive user.
- **No content republishing at rest.** We do not store judgment PDFs, cause-list dumps, or court HTML beyond the transient session needed to render one response.
- **We link out, we don't mirror.** Hyperlinks back to the court's own URLs are the canonical source.
- **No user accounts in MVP.** Anonymous use.

This framing matters because each of the laws below has a sharply different risk surface for "polite, on-demand, user-driven client" vs. "bulk archival mirror."

---

## 2. Statutory landscape — India

### 2.1 Information Technology Act, 2000 (IT Act)

**§43 — Penalty for damage to computer/computer system, etc.**
§43 imposes civil liability on anyone who, without permission of the owner of a computer resource, *inter alia*, accesses, downloads, copies, introduces contaminants, causes denial of service, or disrupts the system.

- **Engineering interpretation — confirm with counsel:** Because the case-status page is *publicly accessible*, the user supplies the CAPTCHA themselves, and traffic is generated only on explicit user request at a low rate, our use falls within the "permitted" envelope contemplated by §43 — i.e., we are using the resource the way the resource invites the public to use it. The risk surface inside §43 grows sharply if we (a) bypass the CAPTCHA, (b) generate request volumes that approach denial-of-service in effect, or (c) extract data the site does not expose to the public UI. We do none of those.
- **Mitigation:** see Rate-limit ethics (§5) and robots.txt posture (§4).

**§66 — Computer-related offences (criminal)**
§66 criminalises §43 acts when done dishonestly or fraudulently.

- **Engineering interpretation — confirm with counsel:** No dishonest/fraudulent intent. Our product helps users access court information *the court has chosen to publish*, in the way the court has chosen to publish it. The mens rea element of §66 is not met for a polite, transparent, user-driven client.

**§66A — Status post-Shreya Singhal**
§66A was struck down as unconstitutional in *Shreya Singhal v. Union of India* (2015) and is **inoperative**. We list it only to note: any content moderation or "offensive message" framing built on §66A is unavailable to us and to anyone else. Where third parties cite §66A in takedown demands, the demand is facially invalid.

**§79 — Intermediary safe harbour**

- **Engineering interpretation — confirm with counsel:** We are *probably not* an "intermediary" in the §79 sense because we don't host user-generated content; we proxy a court search and parse the response. We should still operate as if §79 due-diligence (the Intermediary Rules 2021) applied — i.e., publish a privacy notice, name a grievance contact, comply with lawful takedowns within the statutory window. This is cheap to do and removes a class of disputes.

### 2.2 Digital Personal Data Protection Act, 2023 (DPDPA)

The DPDPA governs the processing of "digital personal data" of natural persons (Data Principals) by Data Fiduciaries and Data Processors.

**What role do we play?**

- The *case data we surface* (party names, advocate names, hearing dates) is **personal data of third parties** — the litigants and counsel. It is sourced from a public court record, but DPDPA does not have a blanket "public record" exemption the way some other regimes do; **§3(c)(ii)** exempts personal data "made publicly available by the Data Principal" or by any person under a legal duty, which arguably covers court-published cause lists, but the contours are unsettled.
- **Engineering interpretation — confirm with counsel:** For litigant/counsel data published by the court itself under the open-court principle, the §3(c)(ii) carve-out *likely* applies and we are not a Data Fiduciary for that data. **But this is the single most legally fragile assumption in this MVP** — flag for counsel.
- For the *user* of our site, we collect minimal data (case query, hashed IP, timestamp). For this data we **are a Data Fiduciary**. See PRIVACY-NOTICE.md.

**Consent (§6).** For the small footprint of user data we collect, we will rely on the "legitimate use" basis under §7 (specifically performance of the service the user requested) plus a clear notice. No granular consent flow required for MVP.

**Data minimisation (§8(3)).** We collect only what is needed: the search query (which the user typed themselves), a hashed IP (for abuse defence), a timestamp, and the outbound result. We do **not** collect name, email, phone, geolocation, or device fingerprint.

**Storage limitation (§8(7)).** Retention policy: `search_request` 90 days then anonymised; `outbound_request_log` 30 days; no judgments/PDFs at rest. Codified in PRIVACY-NOTICE.md.

**Breach reporting (§8(6)).** A personal data breach must be reported to the Data Protection Board "in such form and manner as may be prescribed." Rules are still settling.

- **Engineering interpretation — confirm with counsel:** Until the Rules crystallise, treat 72 hours from confirmed breach as our internal SLA for notification and document everything. This aligns with international norms and is defensible.

**Children's data (§9).** We do not knowingly target minors. The site contains no age-gated content and no profiling. No special handling required for MVP.

**Significant Data Fiduciary (§10).** Not us at MVP scale. Re-evaluate at >50k DAU.

### 2.3 The Copyright Act, 1957

**Court orders and judgments** are excluded from copyright under **§52(1)(q)** — "the reproduction or publication of (i) any matter which has been published in any Official Gazette ... (ii) the report of any committee ... (iii) any judgment or order of a court, tribunal or other judicial authority ... unless the reproduction or publication of such judgment or order is prohibited by the court."

- **Engineering interpretation — confirm with counsel:** The *content* of court orders is free to reproduce. So is the bare procedural metadata (case number, parties, next date). What is **not** clearly free is:
  - The court website's HTML/CSS/JavaScript — the *compilation* and *presentation* layer is plausibly copyrighted (§13(1)(a) literary works, §2(o)).
  - Original editorial choices in how the court presents data (column ordering, status labels).
- **What we re-publish:** parsed structured fields (case no, parties, next listing date, judges, status string). This is *facts about cases* — facts are not copyrightable. We do **not** copy HTML, CSS, the court's logo, branding, or styling.
- **What we link to:** the court's own URL. Linking is settled-low-risk.
- **Net posture:** low copyright risk. Re-evaluate immediately if the product roadmap ever proposes mirroring judgment PDFs or republishing the court's HTML verbatim — that would change the analysis.

### 2.4 Constitution of India — Article 19(1)(a) and the open-court principle

Article 19(1)(a) protects freedom of speech and expression, which the Supreme Court has read to include the **right to information** as a corollary (*S.P. Gupta v. Union of India*, *Union of India v. Association for Democratic Reforms*, etc.). Aggregating and re-presenting *public-record court data* is a protected activity, subject to the reasonable restrictions in 19(2).

The **open-court principle** — that judicial proceedings should be conducted in public — is foundational. The Supreme Court's e-courts judgments and the *Swapnil Tripathi v. Supreme Court of India* (2018) decision on live-streaming reinforce that public access to court proceedings is a constitutional value, not a privilege grudgingly granted.

- **Engineering interpretation — confirm with counsel:** Used carefully, this is *legitimacy framing*, not a legal shield. It tells the story of why a polite, attribution-respecting case tracker is consistent with how Indian courts have positioned themselves towards public access. It does **not** override the IT Act, DPDPA, or any specific direction issued by the Delhi HC itself.

---

## 3. Terms of service of the Delhi HC site

**OPEN ITEM — blocks launch.** We have not yet performed a manual review of the Delhi High Court website's terms of use, disclaimer, or "About this site" pages. Required actions before MVP launch:

1. Manual human read of every disclaimer/terms/copyright page on `delhihighcourt.nic.in` and any subdomain we will fetch from.
2. Capture a dated PDF snapshot of those pages and check it into `/docs/legal/snapshots/` for the audit trail.
3. Counsel reviews the captured text against this MVP's behaviour.
4. If the terms forbid scraping, automated access, or republication in any form, **the MVP cannot launch as designed.**

**Kill-switch design (if terms forbid our access pattern):**
- The backend exposes a single environment variable, `OUTBOUND_FETCH_ENABLED`, default `true`.
- A privileged admin endpoint (`POST /admin/kill-switch`) flips it to `false`. Requires the admin shared secret AND an IP-allowlisted source.
- When `false`, every outbound fetch returns immediately with a structured error to the frontend, which displays a static "service paused pending review" banner. No queueing, no retries, no degraded operation.
- Flip time from decision to global stop: under 5 minutes (single-region deploy assumed for MVP).
- The same switch is the response path for a take-down demand (see §7).

---

## 4. `robots.txt` posture

**Policy:** we read and respect `robots.txt` for `delhihighcourt.nic.in` (and any subdomain we touch) on every cold start and refresh it every 6 hours.

- We refuse to fetch any path that `robots.txt` disallows for `User-agent: *` (or any user-agent we identify as).
- If the user's search would route through a disallowed path, the API returns a structured `403 path_disallowed_by_robots_txt` error and the frontend tells the user we can't fetch that path. **Fail loudly, never silently route around.**
- Our user-agent string is identifiable and contains a contact URL: `DelhiHCCaseTrackerMVP/0.1 (+https://<our-domain>/contact)`. This makes us reachable by the court if they want us to stop.
- `robots.txt` is not legally binding *per se*, but ignoring it is the single clearest piece of evidence of bad-faith access. Compliance is non-negotiable.

**OPEN ITEM:** capture the current `robots.txt` content at the point of first deploy, snapshot it, and re-snapshot every change. This gives us a defensible record of what we believed the site permitted at any given time.

---

## 5. Rate-limit ethics — "polite client" behaviour

Even where law and `robots.txt` permit access, we self-throttle. The defence is reputational and operational: courts and their IT vendors will tolerate a polite client; they will block (and possibly escalate) an impolite one.

**Starting policy (codify in code, not just docs):**

- **Global outbound cap:** ≤ 1 outbound search per 3 seconds across the whole service. Tokens are shared across users; if 50 users queue at once, they queue.
- **Per-user-IP cap:** ≤ 10 searches per hour per source IP, sliding window. Hashed IPs only.
- **Backoff on errors:** on any 5xx or non-200 from the court site, exponential backoff starting at 30 s, capped at 10 min. Three consecutive failures opens a circuit breaker for that path.
- **Quiet hours (Indian Standard Time):** between 22:00 and 06:00 IST, hard-cap the global rate at 1 outbound per 10 seconds. This reduces the chance of our traffic being mistaken for an after-hours attack and is what a polite human would do.
- **No retries on CAPTCHA failures.** A CAPTCHA failure means the human got it wrong; we do not auto-retry. The user must re-initiate.

**Justification (not a legal claim):** "polite client" behaviour is what every reputable scraper, search engine, and integrator publishes as their operational norm. It is also what we would want done to our own service. Falling below this bar is the fastest way to convert a legal grey area into a hostile one.

---

## 6. User-facing disclaimer (banner copy)

Render this verbatim as a dismissible banner on first visit, with a permanent link in the footer ("About this service") that displays the same text.

> **About this service**
>
> This site is **not operated by the Delhi High Court** and has no affiliation with the Court, its Registrar, or any judicial officer. We are an independent tool that helps you query the Court's own publicly available case-status search and presents the result in a cleaner format.
>
> Results shown here are best-effort parses of what the Court's website returns at the moment you search. **The Delhi High Court's own page is the authoritative source.** Where we link to a court URL, that link is canonical. If our display and the Court's page disagree, the Court's page is correct.
>
> We do **not** bypass any security control of the Court's website. The CAPTCHA you solve is shown to you exactly as the Court's website sent it; we forward your answer unchanged.
>
> We do **not** store the contents of cases. We retain the minimum information needed to operate the service — see our [Privacy Notice](/privacy).
>
> If you are the Delhi High Court or its IT administrator and you would like us to pause or stop, contact **\<owner-email\>** and we will comply within 24 hours.

---

## 7. Take-down and incident process

**Single point of contact:** \<owner-email\> (**OPEN ITEM** — owner to assign a monitored mailbox before launch; suggest a role address like `legal@<our-domain>` rather than a personal one).

**SLA:** acknowledge within 4 hours of receipt during business hours IST; full compliance (including kill-switch activation if requested) within **24 hours**.

**Process on a take-down request from the Court or its counsel:**

1. Acknowledge receipt to sender from the role address.
2. Owner activates the kill switch (§3) immediately if the request asks us to stop fetching. Do this *before* legal review — we can always resume; we cannot un-fetch.
3. Owner sends the request to counsel for review within 4 business hours.
4. Document the request, our response, and the timeline in `/docs/legal/incidents/YYYY-MM-DD-<short-name>.md`. Snapshot all relevant pages.
5. If the request is from a third party (not the Court), evaluate under §79-style intermediary diligence: is the request specific, identifiable content? Is there a court order? Apply the same 24-hour window where the request is *facially valid*; push back politely where it is not.
6. Resume service only after counsel sign-off in writing.

**Security-incident process** (separate from legal take-downs) lives in SECURITY-CONSIDERATIONS.md.

---

## 8. Summary of OPEN ITEMS blocking launch

1. Manual review of `delhihighcourt.nic.in` terms / disclaimer pages, snapshotted and counsel-reviewed.
2. Capture and snapshot the live `robots.txt`.
3. Verify the canonical hostname(s) of the court's case-status endpoint and pin them in the outbound allowlist (see SECURITY-CONSIDERATIONS.md §4).
4. Assign and publish a monitored role address for take-down and privacy contact.
5. Counsel sign-off on the DPDPA §3(c)(ii) interpretation for litigant data surfaced via the court's own search.

Until these five are closed, the MVP should not accept public traffic.
