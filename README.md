# Delhi HC Case Tracker — MVP

> **A workflow-simplification wrapper over the public Delhi High Court case-status search.**
> Not a court-operated site. The court's own page is authoritative. We never bypass CAPTCHA.

This repository contains a feasibility MVP that proves a single hypothesis: a lawyer or paralegal can retrieve Delhi High Court case status faster and more reliably through this app than through the court's own website — *without* circumventing any court security control. The user solves the CAPTCHA. We do everything else.

---

## 🚧 DO NOT DEPLOY PUBLICLY

> 🚧 **DO NOT DEPLOY PUBLICLY** — this is a GREEN-ZONE private alpha.
>
> Until all Phase-0 gates close and counsel signs off, this app must run
> on localhost or behind HTTP basic auth on a private URL only.
>
> Phase-0 gate checklist:
> - [ ] G1 — Spike: session + CAPTCHA mechanics mapped (Arnav)
> - [ ] G2 — Terms of Use + robots.txt review (Sneha + counsel)
> - [ ] G3 — DPDPA classification opinion from counsel
> - [ ] G4 — Parser ≥80% on 20 real anonymised result pages
> - [ ] G5 — 5-10 friendly-lawyer testers committed to pilot
>
> See docs/EXECUTIVE-SUMMARY.md §2 for the verdict structure.

The frontend ships with three reinforcing rails to keep this build out of public reach:

1. `<meta name="robots" content="noindex, nofollow">` on every page (App Router metadata).
2. `frontend/public/robots.txt` with `Disallow: /` for crawlers that skip meta tags.
3. A sticky "PRIVATE ALPHA — DO NOT SHARE" banner that renders whenever
   `NEXT_PUBLIC_CLIENT_MODE=real`. Pair with the backend's `CLIENT_MODE=real`.

---

## What's in this repo

```
.
├── docs/                              ← Read these first.
│   ├── EXECUTIVE-SUMMARY.md           ← Start here. One-page overview + verdict.
│   ├── prd/                           ← Priya — PRD + user stories
│   ├── architecture/                  ← Arnav — system design, sequences, strategies, data model
│   ├── decisions/                     ← Architecture Decision Records
│   ├── api/                           ← API-CONTRACT.md (OpenAPI-style)
│   ├── legal/                         ← Sneha — IT Act, DPDPA, privacy notice, security checklist
│   └── runbooks/                      ← (TBD post-MVP — on-call playbooks)
├── backend/                           ← FastAPI service
│   ├── app/                           ← FastAPI app, routes, models, parsers, clients
│   ├── alembic/                       ← DB migrations
│   ├── tests/                         ← unit + integration
│   └── requirements.txt
├── frontend/                          ← Next.js (App Router, TypeScript)
│   ├── src/app/                       ← pages + layout
│   ├── src/components/                ← forms, results, layout, ui
│   └── package.json
├── parsers/                           ← Court HTML parsers + golden fixtures
├── workers/                           ← (Future) background jobs — empty in MVP
├── infrastructure/                    ← docker-compose, Dockerfiles, nginx, terraform
├── scripts/                           ← dev setup + DB helpers
├── config/                            ← per-env config overlays
├── logs/                              ← runtime logs (gitignored)
├── tests/                             ← e2e + smoke + load tests
└── .github/workflows/                 ← CI
```

A complete file index is in [docs/EXECUTIVE-SUMMARY.md](docs/EXECUTIVE-SUMMARY.md).

---

## Quick start (local development)

**Windows:**
```powershell
.\scripts\dev\setup.ps1
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
# In a second terminal:
cd frontend; npm run dev
```

**Unix:**
```bash
./scripts/dev/setup.sh
backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend
# In a second terminal:
cd frontend && npm run dev
```

**Docker:**
```bash
docker compose -f infrastructure/docker-compose.yml up --build
```

Backend serves on http://localhost:8000 (OpenAPI at `/api/v1/openapi.json`). Frontend on http://localhost:3000 (or the next free port in 3000-3010; the dev launcher falls back automatically).

> After pulling new commits, run `scripts/dev/check-env.ps1` (Windows) or `scripts/dev/check-env.sh` (Unix) to spot new env vars that need to be added to your local `.env` / `frontend/.env.local`.

> Before deploying anywhere, complete the **Phase-0 spike** in [docs/EXECUTIVE-SUMMARY.md](docs/EXECUTIVE-SUMMARY.md). The court site's exact session / CAPTCHA / CSRF mechanics are unknown and gate every downstream task.

### Environment files (two files, on purpose)

Next.js does NOT read the repo-root `.env`. To keep the split clean and avoid drift, the repo uses two example files:

| File | Read by | Contains |
| ---- | ------- | -------- |
| `.env.example` -> `.env` | FastAPI backend (Pydantic settings) | Backend-only vars (DB, sessions, outbound HTTP, kill-switch, `CLIENT_MODE`) |
| `frontend/.env.example` -> `frontend/.env.local` | Next.js (build + dev server) | `NEXT_PUBLIC_*` vars only, including `NEXT_PUBLIC_CLIENT_MODE` |

`setup.ps1` and `setup.sh` copy both. `scripts/dev/check-env.ps1` / `.sh` diff both against their example and exit non-zero if any key is missing.

**Important:** `CLIENT_MODE` (backend) and `NEXT_PUBLIC_CLIENT_MODE` (frontend) MUST match. The "PRIVATE ALPHA - DO NOT SHARE" banner renders only when the frontend mirror is set to `real`. If you change one, change both, and restart `npm run dev` so Next.js re-inlines the value.

### Common Windows issues

- **`npm run dev` says `EADDRINUSE: address already in use :::3000`** — A stale Node process is holding port 3000. The dev launcher (`scripts/dev/dev-frontend.mjs`) now auto-falls-back to the next free port in 3000-3010, so this should be rare. If you want 3000 back:
  ```powershell
  netstat -ano | findstr :3000
  Stop-Process -Id <pid>
  ```
- **`setup.ps1` fails with `string is missing the terminator` or `missing closing }`** — A contributor slipped a non-ASCII character (em-dash, smart quote) into a `.ps1` file and bypassed CI. Run `powershell -File scripts\dev\check-windows-scripts.ps1` to locate it. The script enforces UTF-8 BOM, CRLF, and ASCII-only on every `.ps1`/`.bat`/`.cmd` in the repo.
- **PRIVATE ALPHA banner not rendering even though `CLIENT_MODE=real`** — Make sure `NEXT_PUBLIC_CLIENT_MODE=real` is set in `frontend/.env.local` (not the root `.env` — Next.js ignores that file). Restart `npm run dev` after changing it.

---

## The non-negotiables

1. **We do NOT bypass CAPTCHA.** The human user solves it. No OCR. No solver model. This is an [ADR-003](docs/decisions/ADR-003.md) commitment.
2. **We respect `robots.txt`.** Any disallowed path triggers a structured error to the user, never a covert fetch.
3. **We rate-limit ourselves.** Default ≤ 1 outbound search every 3 seconds, global.
4. **The court's page is authoritative.** Every result links back to the court source.
5. **No PII storage.** User IPs are hashed. Search inputs anonymised at 90 days. Outbound logs purged at 30 days.
6. **Kill switch.** `OUTBOUND_FETCH_ENABLED=false` halts the entire pipeline globally in <5 minutes. See [docs/legal/LEGAL-COMPLIANCE.md](docs/legal/LEGAL-COMPLIANCE.md).

---

## Status

**Phase 0 — feasibility spike** (week 1, current). No production deploy until the spike report lands and Sneha clears ToS/robots.txt.

See [docs/EXECUTIVE-SUMMARY.md](docs/EXECUTIVE-SUMMARY.md) for the consolidated roadmap, engineering backlog, risk register, and the feasibility verdict.
