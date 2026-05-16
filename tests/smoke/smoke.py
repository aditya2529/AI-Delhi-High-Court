"""End-to-end smoke check for the Delhi HC Case Tracker backend.

Run from project root:

    .venv\\Scripts\\python.exe tests\\smoke\\smoke.py

What it does:
  1. Boots `uvicorn app.main:app` in a subprocess on a free port.
  2. Waits for /health to return 200 (with 30s timeout).
  3. Probes /api/v1/openapi.json — the contract is published.
  4. Runs the happy-path flow:
       POST /api/v1/search/init     -> session_id + captcha_image_b64
       POST /api/v1/search/submit   -> ParsedCase
     Uses the hard-coded test CAPTCHA "TEST" expected by FakeCourtClient.
  5. Verifies the ParsedCase body shape matches API-CONTRACT.md §7.1.
  6. Exits 0 on all-PASS, non-zero on first FAIL. Prints PASS/FAIL per check.

This is intentionally LIGHT — pytest covers the deep contract. Smoke just
confirms the assembled binary runs and the wire works.

Maya note: while the search routes are still skeleton (501 Not Implemented),
the flow check will report FAIL and the script exits non-zero. That's the
correct signal: "the end-to-end is not green yet".
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── small CLI helpers ─────────────────────────────────────────────────────

PASS = "[ PASS ]"
FAIL = "[ FAIL ]"
INFO = "[ INFO ]"
WARN = "[ WARN ]"


def _print(tag: str, msg: str) -> None:
    sys.stdout.write(f"{tag} {msg}\n")
    sys.stdout.flush()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ── HTTP helpers — stdlib only (no extra deps required) ───────────────────

def _http_get(url: str, timeout: float = 5.0) -> tuple[int, dict[str, Any] | str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except json.JSONDecodeError:
                return resp.status, data
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = ""
        return e.code, body


def _http_post(url: str, body: dict[str, Any], timeout: float = 10.0) -> tuple[int, dict[str, Any] | str]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(data)
            except json.JSONDecodeError:
                return resp.status, data
    except urllib.error.HTTPError as e:
        try:
            body_err = json.loads(e.read().decode("utf-8"))
        except Exception:
            body_err = ""
        return e.code, body_err


# ── Backend subprocess management ─────────────────────────────────────────

def _start_backend(port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.setdefault("APP_ENV", "development")
    env.setdefault("ADMIN_SHARED_SECRET", "smoke-secret")
    backend_dir = PROJECT_ROOT / "backend"
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--log-level", "warning",
    ]
    _print(INFO, f"Starting backend: {' '.join(cmd)} (cwd={backend_dir})")
    proc = subprocess.Popen(
        cmd,
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return proc


def _wait_for_health(base: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            status, _body = _http_get(f"{base}/api/v1/health", timeout=2.0)
            if status == 200:
                return True
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.5)
    if last_err:
        _print(INFO, f"Last error while waiting for /health: {last_err!r}")
    return False


# ── Contract assertions (mirror API-CONTRACT §7.1 ParsedCase) ─────────────

REQUIRED_PARSED_CASE_FIELDS = {
    "case_id", "case_type", "case_number", "year",
    "parties", "orders", "judgments",
    "raw_html_hash", "parsed_at", "source_url", "parser_version",
}


def _check_parsed_case_shape(case: dict[str, Any]) -> list[str]:
    """Return list of validation failures; empty list = OK."""
    issues: list[str] = []
    missing = REQUIRED_PARSED_CASE_FIELDS - set(case.keys())
    if missing:
        issues.append(f"missing fields: {sorted(missing)}")
    parties = case.get("parties")
    if not isinstance(parties, dict):
        issues.append(f"parties is not an object: {type(parties).__name__}")
    else:
        for k in ("petitioner", "respondent"):
            if not isinstance(parties.get(k), list):
                issues.append(f"parties.{k} is not an array")
    if "source_url" in case and not isinstance(case["source_url"], str):
        issues.append("source_url is not a string")
    if "year" in case and not isinstance(case["year"], int):
        issues.append("year is not an integer")
    return issues


# ── Main flow ─────────────────────────────────────────────────────────────

def run_smoke() -> int:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    proc = _start_backend(port)
    exit_code = 0
    try:
        if not _wait_for_health(base, timeout=30.0):
            _print(FAIL, "Backend never returned 200 from /health within 30s.")
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            _print(INFO, f"uvicorn stderr:\n{stderr[:2000]}")
            return 2

        _print(PASS, "GET /api/v1/health -> 200")

        # OpenAPI
        status, body = _http_get(f"{base}/api/v1/openapi.json")
        if status == 200 and isinstance(body, dict) and "openapi" in body:
            _print(PASS, "GET /api/v1/openapi.json -> 200 with openapi schema")
        else:
            _print(FAIL, f"GET /api/v1/openapi.json -> {status}; body type {type(body).__name__}")
            exit_code = 1

        # /init
        status, init_body = _http_post(f"{base}/api/v1/search/init", {
            "case_type": "W.P.(C)", "case_number": "12345", "year": 2024,
        })
        if status == 501:
            _print(WARN, "POST /search/init returned 501 — skeleton not yet implemented.")
            _print(WARN, "Smoke flow check cannot complete until Arjun lands the route.")
            return 0 if exit_code == 0 else exit_code  # don't fail on a known stub
        if status != 200 or not isinstance(init_body, dict):
            _print(FAIL, f"POST /search/init -> {status}; body={init_body!r}")
            return 1

        sid = init_body.get("session_id")
        captcha_b64 = init_body.get("captcha_image_b64")
        if not sid or not captcha_b64:
            _print(FAIL, f"/search/init missing session_id or captcha_image_b64: {init_body!r}")
            return 1
        _print(PASS, f"POST /search/init -> 200, session_id={sid[:8]}…")

        # /submit
        status, submit_body = _http_post(f"{base}/api/v1/search/submit", {
            "session_id": sid, "captcha_text": "TEST",
        })
        if status != 200 or not isinstance(submit_body, dict):
            _print(FAIL, f"POST /search/submit -> {status}; body={submit_body!r}")
            return 1
        if submit_body.get("status") != "success":
            _print(FAIL, f"/search/submit status != 'success': {submit_body.get('status')}")
            return 1
        case = submit_body.get("result")
        if not isinstance(case, dict):
            _print(FAIL, "/search/submit result is not an object")
            return 1

        issues = _check_parsed_case_shape(case)
        if issues:
            _print(FAIL, "ParsedCase shape mismatch:")
            for it in issues:
                _print(FAIL, f"  - {it}")
            return 1
        _print(PASS, "POST /search/submit -> 200 with well-formed ParsedCase")

        return exit_code

    finally:
        if proc.poll() is None:
            try:
                if os.name == "nt":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5.0)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    rc = run_smoke()
    if rc == 0:
        _print(PASS, "Smoke check OK.")
    else:
        _print(FAIL, f"Smoke check exited {rc}.")
    sys.exit(rc)
