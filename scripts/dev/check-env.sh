#!/usr/bin/env bash
# check-env.sh - diff .env files against their .env.example to spot drift.
#
# See the long-form rationale in scripts/dev/check-env.ps1; this is the
# POSIX equivalent. Behaviour is intentionally identical:
#
#   .env.example                  <-> .env                     (backend)
#   frontend/.env.example         <-> frontend/.env.local      (frontend)
#
# Exit codes:
#   0 = all good
#   1 = at least one missing key
#   2 = an .env.example was missing (configuration bug)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Parse a dotenv-style file and print declared keys, one per line.
extract_keys() {
  local path="$1"
  [ -f "$path" ] || return 0
  # - Strip CR (Windows line endings sneak in)
  # - Skip blank lines and comments
  # - Honour optional `export ` prefix
  # - Take only the part before the first `=`
  sed -e 's/\r$//' "$path" \
    | sed -e 's/^[[:space:]]*//' \
    | grep -v '^$' \
    | grep -v '^#' \
    | sed -e 's/^export //' \
    | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' \
    | cut -d= -f1
}

EXIT_CODE=0

check_pair() {
  local label="$1"
  local example="$2"
  local live="$3"

  echo
  echo "=== $label ==="
  echo "  example: $example"
  echo "  live   : $live"

  if [ ! -f "$example" ]; then
    echo "  ERROR: example file does not exist."
    EXIT_CODE=2
    return
  fi
  if [ ! -f "$live" ]; then
    echo "  ERROR: live file does not exist. Run setup.sh first to create it."
    EXIT_CODE=2
    return
  fi

  local expected actual missing extra
  expected="$(extract_keys "$example" | sort -u)"
  actual="$(extract_keys "$live" | sort -u)"

  missing="$(comm -23 <(echo "$expected") <(echo "$actual"))"
  extra="$(comm -13 <(echo "$expected") <(echo "$actual"))"

  local missing_count extra_count actual_count
  missing_count=$(echo -n "$missing" | grep -c . || true)
  extra_count=$(echo -n "$extra" | grep -c . || true)
  actual_count=$(echo -n "$actual" | grep -c . || true)

  if [ "$missing_count" -eq 0 ] && [ "$extra_count" -eq 0 ]; then
    echo "  OK: $actual_count keys, in sync with example."
    return
  fi

  if [ "$missing_count" -gt 0 ]; then
    echo "  MISSING ($missing_count) - in example but not in live file (defaults will apply):"
    echo "$missing" | sed 's/^/    - /'
    [ "$EXIT_CODE" -lt 1 ] && EXIT_CODE=1
  fi
  if [ "$extra_count" -gt 0 ]; then
    echo "  EXTRA ($extra_count) - in live file but not in example (obsolete or local override):"
    echo "$extra" | sed 's/^/    + /'
  fi
}

check_pair "Backend env (root)" \
  "$REPO_ROOT/.env.example" \
  "$REPO_ROOT/.env"

if [ -f "$REPO_ROOT/frontend/.env.example" ]; then
  check_pair "Frontend env (Next.js)" \
    "$REPO_ROOT/frontend/.env.example" \
    "$REPO_ROOT/frontend/.env.local"
else
  echo
  echo "=== Frontend env (Next.js) ==="
  echo "  skipped: frontend/.env.example not found in this clone."
  echo "  (After the env-layout split, this file should exist; re-pull main.)"
fi

echo
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "check-env: OK"
else
  echo "check-env: FAIL (exit $EXIT_CODE)"
  echo
  echo "To resolve missing keys:"
  echo "  Open the relevant .env / .env.local in an editor and add the missing"
  echo "  keys from the matching .env.example. Copy the example value as a"
  echo "  starting point, then edit for your environment."
fi
exit "$EXIT_CODE"
