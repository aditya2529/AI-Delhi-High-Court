# Delhi HC Case Tracker — MVP

> **A workflow-simplification wrapper over the public Delhi High Court case-status search.**
> Not a court-operated site. The court's own page is authoritative. We never bypass CAPTCHA.

This repository contains a feasibility MVP that proves a single hypothesis: a lawyer or paralegal can retrieve Delhi High Court case status faster and more reliably through this app than through the court's own website — *without* circumventing any court security control. The user solves the CAPTCHA. We do everything else.

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

Backend serves on http://localhost:8000 (OpenAPI at `/api/v1/openapi.json`). Frontend on http://localhost:3000.

> Before deploying anywhere, complete the **Phase-0 spike** in [docs/EXECUTIVE-SUMMARY.md](docs/EXECUTIVE-SUMMARY.md). The court site's exact session / CAPTCHA / CSRF mechanics are unknown and gate every downstream task.

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
