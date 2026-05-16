#!/usr/bin/env bash
# Delhi HC Case Tracker — Unix dev setup.
#
# Usage:   ./scripts/dev/setup.sh
#
# Idempotent. Creates .venv, installs deps, copies .env, initialises SQLite.

set -euo pipefail

cd "$(dirname "$0")/../.."

echo "==> Checking Python 3.11+"
python3 --version

echo "==> Creating backend virtualenv at backend/.venv"
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -r backend/requirements.txt

echo "==> Copying .env.example to .env (if missing)"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    Created .env — edit it before running anything in production."
fi

echo "==> Initialising SQLite + applying Alembic migrations"
mkdir -p backend/data
(cd backend && .venv/bin/alembic upgrade head)

echo "==> Installing frontend npm deps"
(cd frontend && [ -d node_modules ] || ([ -f package-lock.json ] && npm ci || npm install))

echo ""
echo "Setup complete."
echo "Next:"
echo "  Backend:  backend/.venv/bin/uvicorn app.main:app --reload --app-dir backend"
echo "  Frontend: cd frontend && npm run dev"
echo "  Or both:  docker compose -f infrastructure/docker-compose.yml up --build"
