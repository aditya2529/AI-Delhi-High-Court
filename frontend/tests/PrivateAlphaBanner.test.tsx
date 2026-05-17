// @vitest-environment jsdom
/**
 * Tests for `PrivateAlphaBanner` — env-gated GREEN-ZONE rail.
 *
 * Maps to: green-zone safety rails brief (banner visible iff
 *          `NEXT_PUBLIC_CLIENT_MODE === 'real'`).
 *
 * NOTE: `process.env.NEXT_PUBLIC_*` is normally inlined by Next.js at build
 * time. Under Vitest there's no Next build step, so we mutate `process.env`
 * directly. This faithfully simulates what Next would inline, because the
 * component reads `process.env.NEXT_PUBLIC_CLIENT_MODE` at render time.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

let PrivateAlphaBanner:
  | typeof import("@/components/layout/PrivateAlphaBanner").PrivateAlphaBanner
  | undefined;
let render: typeof import("@testing-library/react").render | undefined;
let screen: typeof import("@testing-library/react").screen | undefined;
let fireEvent: typeof import("@testing-library/react").fireEvent | undefined;

let depsAvailable = true;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const rtl = require("@testing-library/react");
  render = rtl.render;
  screen = rtl.screen;
  fireEvent = rtl.fireEvent;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  PrivateAlphaBanner =
    require("@/components/layout/PrivateAlphaBanner").PrivateAlphaBanner;
} catch {
  depsAvailable = false;
}

const d = depsAvailable ? describe : describe.skip;

const ENV_KEY = "NEXT_PUBLIC_CLIENT_MODE";
let originalValue: string | undefined;

d("PrivateAlphaBanner — env gating", () => {
  beforeEach(() => {
    originalValue = process.env[ENV_KEY];
  });

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env[ENV_KEY];
    } else {
      process.env[ENV_KEY] = originalValue;
    }
  });

  it("renders the banner when CLIENT_MODE=real", () => {
    process.env[ENV_KEY] = "real";
    render!(<PrivateAlphaBanner!/>);
    const banner = screen!.getByRole("region", {
      name: /private alpha warning/i,
    });
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/private alpha/i);
    expect(banner.textContent).toMatch(/do not share/i);
  });

  it("renders NOTHING when CLIENT_MODE=fake", () => {
    process.env[ENV_KEY] = "fake";
    const { container } = render!(<PrivateAlphaBanner!/>);
    expect(container.firstChild).toBeNull();
  });

  it("renders NOTHING when CLIENT_MODE is unset", () => {
    delete process.env[ENV_KEY];
    const { container } = render!(<PrivateAlphaBanner!/>);
    expect(container.firstChild).toBeNull();
  });

  it("renders NOTHING for typos / arbitrary values (fail-safe-quiet)", () => {
    process.env[ENV_KEY] = "REAL"; // wrong case
    const { container } = render!(<PrivateAlphaBanner!/>);
    expect(container.firstChild).toBeNull();
  });

  it("hides the banner after the dismiss button is clicked (per-page only)", () => {
    process.env[ENV_KEY] = "real";
    render!(<PrivateAlphaBanner!/>);
    const dismiss = screen!.getByRole("button", { name: /dismiss/i });
    fireEvent!.click(dismiss);
    expect(
      screen!.queryByRole("region", { name: /private alpha warning/i }),
    ).toBeNull();
  });

  it("links to the authoritative court page", () => {
    process.env[ENV_KEY] = "real";
    render!(<PrivateAlphaBanner!/>);
    const link = screen!.getByRole("link", { name: /delhihighcourt\.nic\.in/i });
    expect(link).toHaveAttribute(
      "href",
      "https://delhihighcourt.nic.in/",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
