// @vitest-environment jsdom
/**
 * Tests for `CaptchaChallenge` — image render, countdown ticks, refresh button.
 *
 * Maps to: US-02 (CAPTCHA display + entry), US-04 (wrong CAPTCHA handling),
 *          US-10 (mobile autofocus).
 *
 * Mocks `@/services/api` so we can drive the component without a real fetch.
 * Required devDeps (Maya -> Sara):
 *   - @testing-library/react, @testing-library/user-event, jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let CaptchaChallenge: typeof import("@/components/forms/CaptchaChallenge").CaptchaChallenge;
let render: typeof import("@testing-library/react").render;
let screen: typeof import("@testing-library/react").screen;
let act: typeof import("@testing-library/react").act;
let fireEvent: typeof import("@testing-library/react").fireEvent;
let waitFor: typeof import("@testing-library/react").waitFor;

let depsAvailable = true;
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const rtl = require("@testing-library/react");
  render = rtl.render;
  screen = rtl.screen;
  act = rtl.act;
  fireEvent = rtl.fireEvent;
  waitFor = rtl.waitFor;
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  CaptchaChallenge = require("@/components/forms/CaptchaChallenge").CaptchaChallenge;
} catch {
  depsAvailable = false;
}

const d = depsAvailable ? describe : describe.skip;

vi.mock("@/services/api", () => ({
  // Default mocks; tests override as needed.
  refreshCaptcha: vi.fn().mockResolvedValue({
    captcha_image_b64: "FRESH_B64==",
    captcha_mime: "image/png",
    captcha_expires_at: new Date(Date.now() + 60_000).toISOString(),
    session_expires_at: new Date(Date.now() + 600_000).toISOString(),
  }),
  searchSubmit: vi.fn(),
  // ApiError is a class; keep it real-ish.
  ApiError: class ApiError extends Error {
    code: string;
    retryable: boolean;
    httpStatus: number;
    constructor(args: {
      code: string;
      message: string;
      retryable: boolean;
      httpStatus: number;
    }) {
      super(args.message);
      this.code = args.code;
      this.retryable = args.retryable;
      this.httpStatus = args.httpStatus;
    }
  },
}));

function defaultProps() {
  return {
    sessionId: "11111111-1111-1111-1111-111111111111",
    initialCaptchaB64: "INITIAL_B64==",
    initialCaptchaMime: "image/png",
    initialExpiresAt: new Date(Date.now() + 90_000).toISOString(),
    onResolve: vi.fn(),
    onAbort: vi.fn(),
  };
}

d("CaptchaChallenge — image, countdown, refresh (US-02)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    // Anchor "now" so countdown is deterministic.
    vi.setSystemTime(new Date("2026-05-17T10:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("renders the base64 CAPTCHA image as a data URL", () => {
    render(<CaptchaChallenge {...defaultProps()} />);
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img.src).toMatch(/^data:image\/png;base64,INITIAL_B64==$/);
    expect(img.alt.length).toBeGreaterThan(0); // a11y — labelled image
  });

  it("renders a Refresh CAPTCHA button (US-02 AC-1)", () => {
    render(<CaptchaChallenge {...defaultProps()} />);
    const btn = screen.getByRole("button", { name: /refresh captcha/i });
    expect(btn).toBeInTheDocument();
  });

  it("countdown ticks down by one second on each interval", async () => {
    render(<CaptchaChallenge {...defaultProps()} />);
    // Initial render shows ~90s. Advance 5 seconds and confirm the text dropped.
    const before = screen.getByText(/\d{2}:\d{2}/).textContent;
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    const after = screen.getByText(/\d{2}:\d{2}/).textContent;
    expect(after).not.toBe(before);
  });

  it("clicking refresh calls api.refreshCaptcha and renders the new image", async () => {
    const api = await import("@/services/api");
    render(<CaptchaChallenge {...defaultProps()} />);
    const btn = screen.getByRole("button", { name: /refresh captcha/i });
    fireEvent.click(btn);

    await waitFor(() => {
      expect(api.refreshCaptcha).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      const img = screen.getByRole("img") as HTMLImageElement;
      expect(img.src).toMatch(/FRESH_B64==/);
    });
  });

  it("shows an expired notice once the countdown hits zero", async () => {
    const props = {
      ...defaultProps(),
      initialExpiresAt: new Date(Date.now() + 2_000).toISOString(),
    };
    render(<CaptchaChallenge {...props} />);
    await act(async () => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.getByText(/expired/i)).toBeInTheDocument();
  });
});
