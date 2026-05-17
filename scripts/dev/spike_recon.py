"""Phase-0 spike — stateful httpx recon against delhihighcourt.nic.in.

Runs the WebFetch-impossible parts of docs/SPIKE-PROTOCOL.md:
  * §1 — cookies + headers + redirects (cookie jar persisted across calls)
  * §2 — form action URL + method + hidden inputs
  * §3 — CSRF/state-token mechanism (HTML + script-tag inspection)
  * §4 — CAPTCHA image URL pattern, size, MIME, refresh path
  * §5 — full Case-Type enum
  * §8 — light rate-limit probe on the form page (NOT the submit endpoint;
          we cannot submit without a CAPTCHA solve)

Hard rules:
  * Honest User-Agent (no spoofing)
  * 1 request per 3 seconds (global cap; honors brief)
  * GET-only — NEVER submits the form (would require a CAPTCHA solve we
    can't generate and would store PII for the case_number we'd guess)
  * Single workstation, single IP
  * Stops on any 4xx/5xx burst (early IP-ban detection)

Outputs:
  scripts/dev/spike_recon_output.json  — machine-readable findings
  scripts/dev/spike_recon_output.md    — human-readable summary appended
                                          to docs/SPIKE-REPORT.md by hand
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
HONEST_UA = (
    "DelhiHCCaseTracker-Spike/0.1 "
    "(private alpha reconnaissance, respecting robots.txt, "
    "no automated submission, see docs/SPIKE-PROTOCOL.md)"
)
DELAY_S = 3.1  # honest 1 req / 3 sec, +0.1 safety
TIMEOUT_S = 20.0

BASE = "https://delhihighcourt.nic.in"
FORM_PATH = "/app/get-case-type-status"

findings: dict[str, Any] = {
    "recon_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "honest_ua": HONEST_UA,
    "delay_seconds_between_requests": DELAY_S,
    "steps": {},
    "abort_reason": None,
}


def _pace() -> None:
    """Block for DELAY_S so we honor 1 req/3 sec."""
    time.sleep(DELAY_S)


def _bail(reason: str) -> None:
    findings["abort_reason"] = reason
    out_json = OUT_DIR / "spike_recon_output.json"
    out_json.write_text(json.dumps(findings, indent=2, default=str), encoding="utf-8")
    print(f"\n!! BAIL: {reason}", file=sys.stderr)
    print(f"   Partial findings saved to {out_json}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    print(f"==> recon @ {findings['recon_at_utc']}")
    print(f"==> UA = {HONEST_UA}")
    print(f"==> delay = {DELAY_S}s between requests; GET-only; no form submit\n")

    with httpx.Client(
        base_url=BASE,
        headers={"User-Agent": HONEST_UA, "Accept": "text/html,*/*"},
        timeout=TIMEOUT_S,
        follow_redirects=True,
    ) as client:

        # ── §1 — fetch the form page, capture redirect chain + cookies ──
        print("§1: GET form page (captures cookies + headers + redirects)")
        try:
            r = client.get(FORM_PATH)
        except Exception as e:
            _bail(f"first GET failed: {e}")

        findings["steps"]["1_initial_fetch"] = {
            "final_url": str(r.url),
            "status_code": r.status_code,
            "redirect_history": [
                {"status": h.status_code, "from": str(h.request.url), "location": h.headers.get("Location")}
                for h in r.history
            ],
            "response_headers": {k: v for k, v in r.headers.items()},
            "cookies_set": [
                {"name": c.name, "domain": c.domain, "path": c.path,
                 "secure": bool(c.secure),
                 "http_only": "HttpOnly" in (c._rest or {}),  # http.cookiejar quirk
                 "expires": c.expires}
                for c in client.cookies.jar
            ],
            "body_bytes": len(r.content),
        }
        print(f"   final URL = {r.url}")
        print(f"   status    = {r.status_code}")
        print(f"   cookies   = {len(list(client.cookies.jar))}")
        if r.status_code >= 400:
            _bail(f"form page returned {r.status_code} on first hit — possible IP block")

        soup = BeautifulSoup(r.text, "lxml")

        # ── §2 — form action URL + method + ALL inputs ──────────────────
        print("\n§2: parse form structure")
        forms = soup.find_all("form")
        forms_info = []
        for f in forms:
            forms_info.append({
                "action": f.get("action"),
                "method": (f.get("method") or "GET").upper(),
                "id": f.get("id"),
                "name": f.get("name"),
                "enctype": f.get("enctype"),
                "inputs": [
                    {
                        "tag": el.name,
                        "type": el.get("type"),
                        "name": el.get("name"),
                        "id": el.get("id"),
                        "value": (el.get("value") or "")[:80] if el.get("type") == "hidden" else None,
                        "required": el.has_attr("required"),
                    }
                    for el in f.find_all(["input", "select", "textarea", "button"])
                ],
            })
        findings["steps"]["2_form_structure"] = {"form_count": len(forms), "forms": forms_info}
        print(f"   forms found = {len(forms)}")
        for i, fi in enumerate(forms_info):
            print(f"   form[{i}]: action={fi['action']!r}  method={fi['method']}  id={fi['id']!r}  inputs={len(fi['inputs'])}")

        # ── §3 — CSRF / state token detection (HTML + script tags) ─────
        print("\n§3: CSRF/state-token mechanism")
        # 3a: hidden inputs across all forms
        hidden_inputs = []
        for fi in forms_info:
            for inp in fi["inputs"]:
                if inp.get("type") == "hidden":
                    hidden_inputs.append({
                        "name": inp.get("name"),
                        "id": inp.get("id"),
                        "value_prefix": (inp.get("value") or "")[:40],
                    })
        # 3b: meta tags that look CSRF-y
        meta_csrf = []
        for m in soup.find_all("meta"):
            n = (m.get("name") or "").lower()
            if any(t in n for t in ("csrf", "token", "xsrf", "antiforgery")):
                meta_csrf.append({"name": m.get("name"), "content_prefix": (m.get("content") or "")[:40]})
        # 3c: script tags — look for token-fetch endpoints
        script_clues = []
        for s in soup.find_all("script"):
            src = s.get("src") or ""
            text = (s.string or "")
            if any(t in src.lower() for t in ("csrf", "token", "captcha")):
                script_clues.append({"src": src, "kind": "src-suspect"})
            for pat in (r"csrf[_-]?token", r"x[-_]?csrf", r"fetch\([\"'][^\"']*token", r"captcha"):
                if re.search(pat, text, re.IGNORECASE):
                    script_clues.append({"src": src or "(inline)", "pattern": pat,
                                          "snippet": text[max(0, text.lower().find(re.search(pat, text, re.IGNORECASE).group().lower())-40):text.lower().find(re.search(pat, text, re.IGNORECASE).group().lower())+80] if re.search(pat, text, re.IGNORECASE) else ""})
                    break

        # 3d: heuristic verdict
        verdict = "UNKNOWN"
        if hidden_inputs:
            verdict = "HTML_HIDDEN_INPUT_PRESENT"
        elif meta_csrf:
            verdict = "META_TAG_PRESENT"
        elif any("inline" in str(c) for c in script_clues):
            verdict = "LIKELY_JS_INJECTED"
        elif script_clues:
            verdict = "EXTERNAL_SCRIPT_SUSPECTED"
        elif not hidden_inputs and not meta_csrf and not script_clues:
            verdict = "NONE_FOUND_IN_HTML  (cookie-only? or session-only?)"
        findings["steps"]["3_csrf_mechanism"] = {
            "verdict": verdict,
            "hidden_inputs": hidden_inputs,
            "meta_csrf": meta_csrf,
            "script_clues": script_clues[:6],
            "session_cookies_present": [c.name for c in client.cookies.jar],
        }
        print(f"   verdict     = {verdict}")
        print(f"   hidden inputs = {len(hidden_inputs)}  meta tags = {len(meta_csrf)}  script clues = {len(script_clues)}")

        # ── §4 — CAPTCHA URL pattern + image fetch ──────────────────────
        print("\n§4: CAPTCHA image URL + bytes")
        # Find <img> / <audio> elements that look CAPTCHA-y
        captcha_candidates = []
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            alt = (img.get("alt") or "").lower()
            if "captcha" in src.lower() or "captcha" in alt or "code" in alt:
                captcha_candidates.append({"tag": "img", "src": src, "alt": img.get("alt")})
        for a in soup.find_all("audio"):
            src = a.get("src") or ""
            if "captcha" in src.lower() or a.find("source"):
                captcha_candidates.append({"tag": "audio", "src": src or (a.find("source").get("src") if a.find("source") else "")})
        # Also scan for src attributes that look like a captcha endpoint
        for el in soup.find_all(src=True):
            src = el.get("src", "")
            if re.search(r"captcha|cap_code|captcha_image|securimage", src, re.IGNORECASE):
                if not any(c["src"] == src for c in captcha_candidates):
                    captcha_candidates.append({"tag": el.name, "src": src, "alt": el.get("alt")})

        findings["steps"]["4_captcha"] = {"candidates": captcha_candidates}
        print(f"   CAPTCHA URL candidates = {len(captcha_candidates)}")
        for c in captcha_candidates[:5]:
            print(f"   - {c['tag']}: {c['src']!r}")

        # Try fetching the first captcha image (one extra request)
        if captcha_candidates:
            _pace()
            cap_src = captcha_candidates[0]["src"]
            # Resolve relative URL
            cap_url = httpx.URL(cap_src) if cap_src.startswith(("http://", "https://")) else httpx.URL(BASE).join(cap_src)
            print(f"\n   fetching CAPTCHA: {cap_url}")
            try:
                cr = client.get(cap_url)
                findings["steps"]["4_captcha"]["first_image"] = {
                    "url": str(cap_url),
                    "status": cr.status_code,
                    "content_type": cr.headers.get("Content-Type"),
                    "cache_control": cr.headers.get("Cache-Control"),
                    "bytes": len(cr.content),
                    "set_cookie": cr.headers.get("Set-Cookie"),
                }
                print(f"   status={cr.status_code}  type={cr.headers.get('Content-Type')}  bytes={len(cr.content)}")
            except Exception as e:
                findings["steps"]["4_captcha"]["first_image_error"] = str(e)
                print(f"   captcha fetch failed: {e}")

        # ── §5 — Case Type enum (all options) ───────────────────────────
        print("\n§5: full Case-Type enum")
        case_type_select = None
        for sel in soup.find_all("select"):
            name = (sel.get("name") or "").lower()
            id_ = (sel.get("id") or "").lower()
            if "case" in name + id_ and ("type" in name + id_ or "type" in (sel.get("class") or [""])[0]):
                case_type_select = sel
                break
        # Fallback: pick the largest select on the page (likely the case-type)
        if case_type_select is None:
            selects = soup.find_all("select")
            if selects:
                case_type_select = max(selects, key=lambda s: len(s.find_all("option")))
        case_type_options: list[str] = []
        if case_type_select:
            for opt in case_type_select.find_all("option"):
                val = (opt.get("value") or "").strip()
                txt = opt.get_text(strip=True)
                if val and val.lower() not in ("", "--select--", "select"):
                    case_type_options.append(val)
        findings["steps"]["5_case_type_enum"] = {
            "select_name": case_type_select.get("name") if case_type_select else None,
            "select_id": case_type_select.get("id") if case_type_select else None,
            "options_count": len(case_type_options),
            "options_first_30": case_type_options[:30],
            "options_full": case_type_options,
        }
        print(f"   enum size = {len(case_type_options)}")
        print(f"   first 10  = {case_type_options[:10]}")

        # ── §8 — light rate-limit probe on the form page ───────────────
        # 3 sequential pages, 3s apart. NOT a load test — just a smoke check.
        print("\n§8: light rate-limit probe (3 sequential GETs of the form page, 3s apart)")
        probe_results = []
        for n in range(3):
            _pace()
            t0 = time.perf_counter()
            try:
                pr = client.get(FORM_PATH)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                probe_results.append({"i": n, "status": pr.status_code, "latency_ms": latency_ms})
                print(f"   probe[{n}]: {pr.status_code}  {latency_ms}ms")
                if pr.status_code >= 400:
                    print(f"   !! probe[{n}] returned {pr.status_code} — stopping probe")
                    break
            except Exception as e:
                probe_results.append({"i": n, "error": str(e)})
                print(f"   probe[{n}] error: {e}")
                break
        findings["steps"]["8_rate_limit_probe"] = {
            "scheme": "3 sequential GETs of form page, 3.1s apart",
            "results": probe_results,
        }

    out_json = OUT_DIR / "spike_recon_output.json"
    out_json.write_text(json.dumps(findings, indent=2, default=str), encoding="utf-8")
    print(f"\n==> findings saved to {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
