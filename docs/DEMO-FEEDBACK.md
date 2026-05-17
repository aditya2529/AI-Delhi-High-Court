# Demo Feedback — Founder First-Run Punch List

> Issues hit by the founder during the first manual demo on Windows 11.
> Each item is a real bug or DX gap the next sprint should close.
> Captured live during the session, not retrofitted.

**Environment:** Windows 11, Windows PowerShell 5.1 (default), fresh clone from GitHub.

---

## 🔴 Blocker — fixed live during demo, needs permanent fix in repo

### 1. `setup.ps1` had Unicode em-dashes (—) — broke PowerShell 5.1 parser
- **Symptom:** `setup.ps1` failed with `The string is missing the terminator: ".` and `Missing closing '}' in statement block`.
- **Root cause:** File contained UTF-8 em-dashes (`—`, bytes `0xe2 0x80 0x94`) in comments. Windows PowerShell 5.1 reads files without BOM as Windows-1252, which misinterprets multi-byte UTF-8 sequences and corrupts string parsing.
- **Fix applied live:** Replaced em-dashes with `--`, added UTF-8 BOM, converted to CRLF line endings.
- **Permanent fix needed:**
  - Sweep all `.ps1` files for em-dashes, en-dashes, smart quotes. Replace with ASCII equivalents.
  - Save all `.ps1` files with UTF-8 BOM (PowerShell 5.1 requirement).
  - Add `.gitattributes` rule: `*.ps1 text eol=crlf working-tree-encoding=UTF-8-BOM`
  - Add a pre-commit hook or CI check that fails if any `.ps1` file has non-ASCII chars or lacks BOM.

### 2. `setup.ps1` had Unix line endings (LF) on a Windows-only script
- **Symptom:** Even after the em-dash fix, PowerShell parsing was fragile.
- **Root cause:** Agents authored the file on Mac/Linux; no `.gitattributes` enforcing CRLF on `.ps1`.
- **Fix applied live:** Converted to CRLF.
- **Permanent fix:** Add `.gitattributes` (see above).

---

## 🔴 Real bug — Delhi HC uses MATH CAPTCHAs, frontend assumed text

### 6. CAPTCHA input field required min 3 characters; Delhi HC uses math CAPTCHAs with 1-3 digit answers
- **Symptom:** First-ever real test (W.P.(C) 2344/2024 in CLIENT_MODE=real). CAPTCHA loaded successfully showing `19 + 3 =`. User typed `22` (correct answer). Could not submit because HTML5 form validation required min 3 characters.
- **Root cause:** `CaptchaChallenge.tsx` line 308 had `minLength={3}` hardcoded. `strings.ts` line 33 had hint "Minimum 3 characters." Both assumed an alphanumeric text CAPTCHA, but Delhi HC actually serves arithmetic CAPTCHAs whose answers can be 1-3 digits (e.g., `5+2=7`, `19+3=22`, `99+1=100`).
- **Why this matters HUGE:** The agents specced and built the entire CAPTCHA flow around an assumption that was wrong. The Zod schema (min 1, max 10) and backend Pydantic (min_length=1, max_length=10) were correct; only the UI component was wrong. This is exactly the kind of spec assumption that ONLY breaks in production.
- **Fix applied live:** The "min 3 chars" assumption was hardcoded in THREE places — not just one:
  1. `minLength={3}` HTML attribute on the input (line 308)
  2. `if (text.trim().length < 3) return;` early-return in handleSubmit (line 140)
  3. `text.trim().length < 3` in submitDisabled computation (line 215)
  All three changed to `1`. Updated hint text to mention math CAPTCHAs.
- **Followup nit:** The agents duplicated the same validation rule across three places in one component instead of deriving it from a single constant or the Zod schema. Suggest extracting `MIN_CAPTCHA_LENGTH = 1` to a constant or pulling it from `SearchSubmitRequestSchema._def.shape.captcha_text._def.checks` so it can't drift again.
- **Permanent fix needed:**
  - The CAPTCHA assumption should have been resolved in Arnav's spike (B.4 / B.5 territory). Update SPIKE-REPORT.md Section C with: "Delhi HC serves MATH CAPTCHAs (arithmetic), not alphanumeric text. Sample observed: `19 + 3 =`. Answers are integers, 1-3 digits typical."
  - Update CaptchaChallenge component: consider rendering different hint text depending on if image is detected to be math vs text (could check image aspect ratio or just be generic).
  - Update tests in test_fake_court_client.py — `captcha_text="ABCDE"` and `captcha_text="X"` in tests don't reflect real-world math answers like "22". Add a math-CAPTCHA fixture.
  - Update FakeCourtClient to serve math CAPTCHAs in its synthetic flow — not text — so the dev-experience matches production. Right now fake mode trains the team to expect text CAPTCHAs, which is misleading.
- **Founder note:** This is the kind of bug that wastes 30 minutes of a 5-minute test session. Worth a sprint retro item on "how did we get to a fully-built CAPTCHA flow without anyone verifying the actual format the court uses."

---

## 🔴 Earlier bug — frontend Zod schema rejects backend session_id

### 4. `session_id` format contract drift between backend and frontend
- **Symptom:** Page loads OK, form renders OK, user submits, sees "Unexpected error / Something went wrong we don't have a label for yet." Backend logs show HTTP 200; backend works fine via curl.
- **Root cause:** Backend generates session IDs via `uuid.uuid4().hex` → produces 32-char dashless hex like `6f89d33bfaf848348959609e1a6dcabb`. Frontend Zod schema `SearchInitResponseSchema.session_id = z.string().uuid()` requires dashed UUID format like `6f89d33b-faf8-4834-8959-609e1a6dcabb`. Validation fails → request throws → no matching error code → falls through to `unknown` variant → UI shows the generic "Unexpected error" screen with no useful info.
- **Why this is bad:** This is exactly the contract-drift the team supposedly closed last sprint. The Pydantic schema on backend says `session_id: str = Field(..., min_length=8, max_length=64)` but the frontend says UUID format. Both should be authoritative for the same field but they disagree. The "unknown" fallback in ErrorState swallows the real error message — no one can debug this from the UI alone.
- **Fix applied live:** Changed `z.string().uuid()` → `z.string().min(8).max(64)` in `frontend/src/types/api.ts` at both `SearchInitResponseSchema.session_id` and `SearchSubmitRequestSchema.session_id` to match the backend's actual Pydantic shape.
- **Permanent fix needed (pick one — owner call):**
  1. **Backend conforms to UUID format:** Change `uuid.uuid4().hex` → `str(uuid.uuid4())` everywhere (search/init, refresh-captcha, etc.). Update backend Pydantic schema to `Field(..., pattern=r"^[0-9a-f]{8}-...$")`. Cleaner semantically — session IDs ARE UUIDs.
  2. **Frontend conforms to hex format:** Keep current relaxed schema. Less clean but the live fix.
- **Either way, lock it in API-CONTRACT.md §7.x as a normative format spec.** This is the second time a "shape lives in two places" drift has bitten us — see DRIFT-001 (parse_confidence vs parser_degraded) from last sprint. Suggest a code-generation step where Zod schemas are derived from the FastAPI OpenAPI output so this can't drift again.
- **Bonus DX gap:** When Zod validation fails inside `searchInit()`, the error message that bubbles up is something like `"session_id: Invalid uuid"` — but the UI throws away that detail and shows generic "unknown" text. Add a development-mode toggle that shows raw error.message on the ErrorState screen when `NODE_ENV !== "production"`. Would have saved 20 minutes of debugging.

---

## 🔴 Parser returns "Not available" against real HTML — BLOCKED on founder re-run

### 7. Parser was synthetic-fixture-trained; real Delhi HC HTML has a different shape
- **Symptom:** First-ever real-mode submission (W.P.(C) 2344/2024 and three connected aircraft-leasing cases) completed the full CAPTCHA round-trip but came back with `parser_degraded=true` and every field as "Not available".
- **Root cause:** `DHCParserV1` selectors target the synthetic schema in `parsers/fixtures/sample_responses/` (class-named cells inside `<table class="case-details">`). The live Delhi HC site's result-page HTML uses a different structure that none of those selectors hit. The placeholder audit at `parsers/fixtures/sample_responses/AUDIT.md` already flagged that the synthetic shape was unverified post-B.6.
- **Why we can't fix the parser yet:** No real HTML was captured. `logs/backend/app.log` and `logs/backend/outbound.log` were empty after the run because the response body was NOT being persisted by `DelhiHCClient.submit_search` — the bytes lived only in process memory and were discarded.
- **What landed THIS sprint (Maya, QA):**
  - New `backend/app/clients/response_capture.py` writes the redacted upstream HTML to `parsers/fixtures/real_responses/<safe-case-id>_<unix>.html` on every successful real-client submit. Redacts IPs, XSRF cookie values, Laravel session cookies, bearer-style blobs. Public court data (party names, dates) survives intact — Sneha's privacy rules + the Court's own public-data disclaimer (SPIKE-REPORT §A.5).
  - Wired into `DelhiHCClient.submit_search`. Failures swallowed (a capture error must NEVER break the user's search).
  - New env flag `DHC_CAPTURE_REAL_RESPONSES` (default `true` in dev, recommended `false` in prod) so it can be turned off without a code change.
  - Updated `scripts/dev/parser_fixture_replay_harness.py` — now accepts a directory, prints a per-fixture table (case_id | confidence | degraded | fields_extracted/fields_attempted), and exits non-zero on any `parser_degraded=true`. Wirable into CI as a quality gate.
  - 41 new tests: 36 for `response_capture` (happy path, redaction, edge cases, failure modes), 5 for the `DelhiHCClient` capture wiring, 15 for the directory-mode harness. Test count 95 → 136.
- **🔴 BLOCKED — founder action required:**
  - Re-run `CLIENT_MODE=real` against the same four case numbers (W.P.(C) 2344/2024, W.P.(C) 6569/2023, W.P.(C) 10327/2023, W.P.(C) 6626/2023). The capture will land real fixtures under `parsers/fixtures/real_responses/` automatically.
  - Once ≥4 fixtures exist, Maya re-points the parser selectors at the real shape, targets ≥80% extraction across the 8 fields (status, last_hearing_date, next_hearing_date, court_no, judge_bench, parties, orders, judgments), and then regenerates the synthetic fixtures in `sample_responses/` to match.
- **Why this isn't a hack:** the team's GREEN-ZONE rails forbid automated outbound calls and CAPTCHA bypass even though the Delhi HC CAPTCHA is math-solvable (per item #6). The human-solves-CAPTCHA contract holds — capture is purely passive instrumentation on a user-driven session.

---

## 🟡 DX gaps — not blockers but worth fixing

### 5. Stale `.env` files silently drift from `.env.example` over time
- **Symptom:** Founder couldn't find `CLIENT_MODE=fake` in their `.env`. Setup script copied `.env.example` to `.env` weeks ago; subsequent sprints added new env vars (CLIENT_MODE, NEXT_PUBLIC_CLIENT_MODE) to the example, but the founder's local `.env` was never updated.
- **Why this matters:** Every env var that defaults to a value will silently use the default, masking the staleness. When the user tries to flip CLIENT_MODE between fake/real, the line isn't there and they get confused. Worse: in production, missing env vars could cause silent misconfiguration with security implications (e.g. ADMIN_SHARED_SECRET defaulting to "change-me-before-deploy").
- **Suggested fix:**
  - Add a `scripts/dev/check-env.ps1` (and .sh) that diffs `.env` vs `.env.example` keys and prints which env vars are missing or unknown. Have `setup.ps1` call it at the end.
  - Or add a startup check in `app/main.py` that logs a WARNING for every env var present in `.env.example` but missing from runtime env.
  - Document a clear "after pulling new commits, run `scripts/dev/check-env.ps1` to spot new env vars" line in the README's Quick Start section.

### 3. No port-collision pre-flight check or auto-fallback
- **Symptom:** `npm run dev` failed with `EADDRINUSE: address already in use :::3000` because a leftover Node.js process from a previous session (different project, started yesterday) was still holding port 3000.
- **Why this matters:** Founder/lawyer-tester laptops will have all kinds of stuff running. Hard-coded port 3000 with no fallback is a common first-run fail.
- **Suggested fix:**
  - Update `frontend/package.json` `dev` script to use a port-finder: `next dev -p $PORT` with a small wrapper that auto-picks the next free port from 3000-3010.
  - OR add a pre-flight check to `setup.ps1` and `setup.sh` that warns if ports 3000/8000 are occupied before declaring "Setup complete."
  - OR add a short "Common issues" section to README covering `EADDRINUSE` with the one-liner fix (`netstat -ano | findstr :3000` then `Stop-Process -Id <pid>`).

---

## What this means

The agents built on Mac/Linux and never tested the setup script on a Windows machine. The founder is on Windows. Every new Windows developer (including all 5 lawyer-friend testers in any technical role) will hit this. Next sprint should add a "Windows smoke test" to CI — boot the setup script in a Windows runner and confirm it completes.

---

## Suggested next-sprint ticket

> **DX-001: Make Windows setup work first-try, every time**
>
> - [ ] Sweep all `.ps1` and `.bat` files: ASCII only, UTF-8 BOM, CRLF endings
> - [ ] Add `.gitattributes` enforcing CRLF + BOM on Windows scripts
> - [ ] Add GitHub Actions workflow that runs `setup.ps1` on `windows-latest` runner
> - [ ] Add a "Troubleshooting" section to README covering common Windows issues
> - [ ] Lint rule or pre-commit hook to catch em-dash / smart-quote regressions
