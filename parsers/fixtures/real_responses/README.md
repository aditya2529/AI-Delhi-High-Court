# Real-court response fixtures

> **EMPTY ON PURPOSE.** This directory is populated automatically when the
> founder runs `CLIENT_MODE=real` against `delhihighcourt.nic.in` with
> `DHC_CAPTURE_REAL_RESPONSES=true` (default). See
> `backend/app/clients/response_capture.py`.

## What lands here

Every successful real-client `submit_search` writes the redacted upstream
HTML body to `<safe-case-id>_<unix-int>.html` in this directory.

Example after a run against `W.P.(C) 2344/2024`:

```
WPC_2344_2024_1747497822.html
```

The filename pattern `<safe-case-id>_<unix-int>.html` lets multiple
captures of the same case naturally version by timestamp (latest mtime
wins for replay).

## What gets redacted before write

Per Sneha's privacy rules + the GREEN-ZONE rails (`docs/SPIKE-REPORT.md` §E):

| Redacted | Kept verbatim |
|---|---|
| IPv4 + IPv6 addresses (→ `0.0.0.0` / `::`) | Petitioner / respondent names (public court data) |
| `XSRF-TOKEN` cookie values (→ `REDACTED`) | Case numbers, hearing dates, order titles |
| `hc_application_session` cookie values | Bench composition, court no. |
| `X-XSRF-TOKEN` header values | Class names, IDs, structural markup |
| Laravel-encrypted `eyJ...` blobs (→ `REDACTED_TOKEN`) | The whole point — selectors must survive |

The Court's own page disclaimer (`SPIKE-REPORT.md` §A.5) confirms party
names + case data are public-facing.

## How fixtures here are used

1. `scripts/dev/parser_fixture_replay_harness.py <dir>` runs the parser
   against every `.html` in this directory and prints a per-fixture
   confidence + degraded table. Exits non-zero if any fixture comes back
   `parser_degraded=true` — so the next CI step can wire to it.
2. After enough real captures land (≥4 cases per the sprint DoD), the
   parser selectors in `backend/app/parsers/case_parser.py` get re-tuned
   to extract ≥80% of the target fields.
3. The synthetic fixtures in `../sample_responses/` then get regenerated
   to match the real structure (placeholder data, real shape).

## Manual cleanup

Delete fixtures older than ~90 days. They have no audit-trail value
once the parser has been re-tuned against them. The capture path will
recreate any case on the next real run.
