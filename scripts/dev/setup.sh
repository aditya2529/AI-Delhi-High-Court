#!/usr/bin/env bash
# Delhi HC Case Tracker -- Unix dev setup.
#
# Usage:   ./scripts/dev/setup.sh
#
# Idempotent. Creates .venv, installs deps, copies BOTH env-example files
# (root .env for backend, frontend/.env.local for Next.js), initialises
# SQLite, then validates env layout and warns if dev ports are busy.

set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"
SCRIPT_DIR="$REPO_ROOT/scripts/dev"

echo "==> Checking Python 3.11+"
python3 --version

echo "==> Creating backend virtualenv at backend/.venv"
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements.txt

echo "==> Copying root .env.example to .env (backend vars)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    Created .env -- edit it before running anything in production."
else
  echo "    .env already exists; not overwriting. Run check-env.sh to spot drift."
fi

echo "==> Copying frontend/.env.example to frontend/.env.local (NEXT_PUBLIC_* vars)"
if [ -f frontend/.env.example ]; then
  if [ ! -f frontend/.env.local ]; then
    cp frontend/.env.example frontend/.env.local
    echo "    Created frontend/.env.local."
    echo "    Remember: NEXT_PUBLIC_CLIENT_MODE must match CLIENT_MODE in root .env."
  else
    echo "    frontend/.env.local already exists; not overwriting."
  fi
else
  echo "    frontend/.env.example missing; skipping frontend env copy."
fi

echo "==> Initialising SQLite + applying Alembic migrations"
mkdir -p backend/data
(cd backend && .venv/bin/alembic upgrade head)

echo "==> Installing frontend npm deps"
(cd frontend && [ -d node_modules ] || ([ -f package-lock.json ] && npm ci || npm install))

# --- Post-install validation -------------------------------------------------
# Advisory: env-drift exits non-zero but we don't propagate that here -- setup
# itself succeeded, the operator just needs to edit two files.

echo "==> Validating env files (root .env + frontend/.env.local)"
if ! bash "$SCRIPT_DIR/check-env.sh"; then
  echo "    check-env reported issues. Fix above, then re-run."
fi

echo "==> Checking dev ports (3000, 8000)"
if command -v node >/dev/null 2>&1; then
  node "$SCRIPT_DIR/check-ports.mjs" || true
else
  echo "    node not on PATH; skipping port check (install Node 20+)."
fi

echo ""
echo "Setup complete."
echo "Next:"
echo "  Backend:  backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend"
echo "  Frontend: cd frontend && npm run dev"
echo "  Or both:  docker compose -f infrastructure/docker-compose.yml up --build"
echo ""
echo "After pulling new commits: re-run scripts/dev/check-env.sh to spot new env vars."
