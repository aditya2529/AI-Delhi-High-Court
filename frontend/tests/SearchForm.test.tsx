// @vitest-environment jsdom
/**
 * Tests for `SearchForm` — Zod validation, disabled state, submit payload shape.
 *
 * Maps to: US-01 (Case search by type/number/year), US-11 (a11y baseline).
 *
 * Required devDeps not yet in package.json — Maya is flagging back to Sara:
 *   - @testing-library/react
 *   - @testing-library/user-event
 *   - @testing-library/jest-dom (optional, for friendlier matchers)
 *   - jsdom
 *
 * Once those land, this file lights up. The current vitest config sets
 * `environment: "node"`, so we override per-file via the pragma above. We
 * also detect the missing deps and skip the suite with a clear message —
 * the file is collected but not failed.
 */
import { describe, expect, it, vi } from "vitest";

let SearchForm: typeof import("@/components/forms/SearchForm").SearchForm;
let render: typeof import("@testing-library/react").render;
let screen: typeof import("@testing-library/react").screen;
let fireEvent: typeof import("@testing-library/react").fireEvent;

let depsAvailable = true;
try {
  // Static imports would fail collection — keep them dynamic so the file is
  // collectable even before Sara adds @testing-library/react.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const rtl = require("@testing-library/react");
  render = rtl.render;
  screen = rtl.screen;
  fireEvent = rtl.fireEvent;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  SearchForm = require("@/components/forms/SearchForm").SearchForm;
} catch {
  depsAvailable = false;
}

const d = depsAvailable ? describe : describe.skip;

d("SearchForm — Zod validation + disabled state (US-01)", () => {
  it("disables submit when the form is invalid (empty case_number)", () => {
    const onSubmit = vi.fn();
    render(<SearchForm onSubmit={onSubmit} submitting={false} />);
    const submitBtn = screen.getByRole("button", { name: /fetch status/i });
    // No case_type selected + empty case_number => invalid.
    expect(submitBtn).toBeDisabled();
  });

  it("disables submit when case_number contains non-digits", () => {
    const onSubmit = vi.fn();
    render(
      <SearchForm
        onSubmit={onSubmit}
        submitting={false}
        initialValues={{ caseType: "W.P.(C)", caseNumber: "abc", year: 2024 }}
      />,
    );
    // The input strips non-digits on change; we set via initialValues to test
    // the schema rejection path. The submit must remain disabled.
    const submitBtn = screen.getByRole("button", { name: /fetch status/i });
    // The form sanitizes on user input — initialValues with "abc" should fail
    // the Zod regex => submit stays disabled.
    expect(submitBtn).toBeDisabled();
  });

  it("disables submit while submitting=true even when valid", () => {
    const onSubmit = vi.fn();
    render(
      <SearchForm
        onSubmit={onSubmit}
        submitting
        initialValues={{ caseType: "W.P.(C)", caseNumber: "1234", year: 2024 }}
      />,
    );
    const submitBtn = screen.getByRole("button", { name: /fetch status/i });
    expect(submitBtn).toBeDisabled();
  });

  it("calls onSubmit with the validated payload on click", () => {
    const onSubmit = vi.fn();
    render(
      <SearchForm
        onSubmit={onSubmit}
        submitting={false}
        initialValues={{ caseType: "W.P.(C)", caseNumber: "1234", year: 2024 }}
      />,
    );

    const submitBtn = screen.getByRole("button", { name: /fetch status/i });
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      caseType: "W.P.(C)",
      caseNumber: "1234",
      year: 2024,
    });
  });

  it("renders banner message when provided (role=alert)", () => {
    render(
      <SearchForm
        onSubmit={() => undefined}
        submitting={false}
        bannerMessage="CAPTCHA failed too many times — please re-enter the case"
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/CAPTCHA failed/i);
  });

  it("strips non-digits as the user types in case_number (adversarial)", () => {
    render(<SearchForm onSubmit={() => undefined} submitting={false} />);
    const input = screen.getByLabelText(/case number/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12a34'; DROP TABLE--56" } });
    // SQL-injection-shaped input gets sanitized to digits-only, capped at 7.
    expect(input.value).toBe("1234567");
  });
});
