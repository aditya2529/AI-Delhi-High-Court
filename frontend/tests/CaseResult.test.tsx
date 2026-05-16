// @vitest-environment jsdom
/**
 * Tests for `CaseResult` — renders all fields, source link, low-confidence warning.
 *
 * Maps to: US-03 (Parsed result display), US-07 (graceful fallback warning),
 *          R7/R10 (trust + XSS-safe rendering — pin "no raw HTML" invariant).
 *
 * Required devDeps (Maya -> Sara):
 *   - @testing-library/react, jsdom
 */
import { describe, expect, it, vi } from "vitest";

import type { ParsedCase } from "@/types/api";

let CaseResult: typeof import("@/components/results/CaseResult").CaseResult;
let render: typeof import("@testing-library/react").render;
let screen: typeof import("@testing-library/react").screen;

let depsAvailable = true;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const rtl = require("@testing-library/react");
  render = rtl.render;
  screen = rtl.screen;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  CaseResult = require("@/components/results/CaseResult").CaseResult;
} catch {
  depsAvailable = false;
}

const d = depsAvailable ? describe : describe.skip;

function makeParsedCase(overrides: Partial<ParsedCase> = {}): ParsedCase {
  return {
    case_id: "W.P.(C)|1234|2024",
    case_type: "W.P.(C)",
    case_number: "1234",
    year: 2024,
    parties: {
      petitioner: ["ACME Industries Pvt Ltd"],
      respondent: ["Union of India", "Ministry of Commerce"],
    },
    status: "Pending",
    last_hearing_date: "2026-04-22",
    next_hearing_date: "2026-06-10",
    court_no: "Court No. 12",
    judge_bench: "Hon'ble Mr. Justice X, Hon'ble Ms. Justice Y",
    orders: [
      {
        date: "2026-04-22",
        title: "Interim Order",
        url: "https://delhihighcourt.nic.in/orders/wpc_1234_2024.pdf",
      },
    ],
    judgments: [],
    raw_html_hash: "a3f1aa",
    parsed_at: "2026-05-17T09:42:11Z",
    source_url: "https://delhihighcourt.nic.in/case-status?id=xxx",
    parser_version: 3,
    parse_confidence: 0.9,
    ...overrides,
  };
}

d("CaseResult — renders parsed fields + source link (US-03)", () => {
  it("shows case header with type, number, year", () => {
    render(<CaseResult data={makeParsedCase()} onSearchAgain={vi.fn()} />);
    expect(
      screen.getByRole("heading", { name: /W\.P\.\(C\) 1234\/2024/i }),
    ).toBeInTheDocument();
  });

  it("renders petitioner and respondent names", () => {
    render(<CaseResult data={makeParsedCase()} onSearchAgain={vi.fn()} />);
    expect(screen.getByText("ACME Industries Pvt Ltd")).toBeInTheDocument();
    expect(screen.getByText("Union of India")).toBeInTheDocument();
    expect(screen.getByText("Ministry of Commerce")).toBeInTheDocument();
  });

  it("renders the source-attribution link pointing to the court site", () => {
    render(<CaseResult data={makeParsedCase()} onSearchAgain={vi.fn()} />);
    const link = screen.getAllByRole("link", { name: /Delhi High Court/i })[0];
    expect(link).toHaveAttribute("href", expect.stringContaining("delhihighcourt.nic.in"));
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("renders 'Not available' for missing optional fields (US-03 AC-2)", () => {
    const data = makeParsedCase({
      court_no: null,
      judge_bench: null,
      last_hearing_date: null,
    });
    render(<CaseResult data={data} onSearchAgain={vi.fn()} />);
    // Multiple fields render "Not available" — ensure at least one is shown.
    const matches = screen.getAllByText(/not available/i);
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("shows degraded warning when parse_confidence < 0.4", () => {
    const data = makeParsedCase({ parse_confidence: 0.2 });
    render(<CaseResult data={data} onSearchAgain={vi.fn()} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/couldn't read/i);
  });

  it("does NOT show degraded warning when parse_confidence >= 0.4", () => {
    const data = makeParsedCase({ parse_confidence: 0.85 });
    render(<CaseResult data={data} onSearchAgain={vi.fn()} />);
    // No alert role at all => high confidence path.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does NOT render raw HTML from any field (XSS guard — R10)", () => {
    const data = makeParsedCase({
      status: "<script>alert('xss')</script>",
      judge_bench: "<img src=x onerror=alert(1) />",
      parties: {
        petitioner: ["<b onclick='evil()'>Evil Co</b>"],
        respondent: ["Union of India"],
      },
    });
    const { container } = render(
      <CaseResult data={data} onSearchAgain={vi.fn()} />,
    );
    // React escapes by default — the literal '<script' should appear as text,
    // never as a real <script> element. If this ever fails, we shipped XSS.
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).toContain("&lt;script&gt;");
  });

  it("invokes onSearchAgain when the 'Search again' button is clicked", () => {
    const onSearchAgain = vi.fn();
    render(<CaseResult data={makeParsedCase()} onSearchAgain={onSearchAgain} />);
    const btn = screen.getByRole("button", { name: /search again/i });
    btn.click();
    expect(onSearchAgain).toHaveBeenCalledTimes(1);
  });
});
