# Sample response fixtures

These are **synthetic** HTML samples, hand-authored to mimic the shape of a
hypothetical Delhi HC case-status result page. They exist so the parser, the
`FakeCourtClient`, and the test suite can all develop end-to-end before the
Phase-0 spike captures real fixtures from the live court site.

**Do NOT confuse these with real court output.** Once the spike clears (see
`docs/EXECUTIVE-SUMMARY.md` G1 + G4), this directory is repopulated with 20
real, anonymised HTMLs and the parser is re-validated.

## Naming convention (used by `FakeCourtClient`)

| File | Maps to | Scenario |
|---|---|---|
| `WPC_12345_2024.html` | `W.P.(C)`, `12345`, `2024` | Pending case, 1 petitioner, 3 respondents, 2 orders |
| `CRLMC_999_2023.html` | `CRL.M.C.`, `999`, `2023` | Disposed, 1 petitioner, 1 respondent, 3 orders + 1 judgment |
| `FAO_1_2025.html` | `FAO`, `1`, `2025` | Fresh case, no orders yet |
| `NOTFOUND.html` | any unmapped tuple | Court returned "no record" |
| `COURT_ERROR.html` | `case_number == "COURT_ERROR"` (any case_type / year) | Simulates court 500 page. Previously keyed on `year == 1900`; explicit sentinel is cleaner (selector not coupled to in-band data). |

All names use case-type without dots/parentheses to be filesystem-friendly.
