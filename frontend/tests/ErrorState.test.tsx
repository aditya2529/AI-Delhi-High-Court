// @vitest-environment jsdom
/**
 * Tests for `ErrorState` — production-mode rendering must stay identical
 * to today's behaviour, and dev-mode must surface the machine-readable
 * envelope fields the founder needs to grep the backend log.
 *
 * Maps to: docs/DEMO-FEEDBACK.md (the founder spent 20+ min debugging a
 * real 500 with zero useful info in the UI). Pins the "no leakage in
 * production" guarantee so a future tweak can't accidentally regress it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ErrorState } from "@/components/results/ErrorState";
import { STRINGS } from "@/lib/strings";

const ORIGINAL_NODE_ENV = process.env.NODE_ENV;

function setNodeEnv(value: "development" | "production" | "test" | undefined) {
  // Plain assignment — `process.env` rejects non-data descriptors so
  // `Object.defineProperty` is not an option, but direct assignment works
  // (process.env is a Proxy that coerces to string under Node).
  if (value === undefined) {
    delete (process.env as Record<string, string | undefined>).NODE_ENV;
  } else {
    (process.env as Record<string, string | undefined>).NODE_ENV = value;
  }
}

function devProps() {
  return {
    variant: "network" as const,
    onStartOver: vi.fn(),
    onRetry: vi.fn(),
    requestId: "req-abc-123-def-456",
    devErrorCode: "court_error",
    devHint: "Upstream timed out; try again in a minute.",
    devRawMessage: "Read timed out after 12000ms talking to delhihighcourt.nic.in",
    devHttpStatus: 503,
    devRawBody: {
      error: {
        code: "court_error",
        message: "Read timed out after 12000ms talking to delhihighcourt.nic.in",
        retryable: true,
        hint: "Upstream timed out; try again in a minute.",
        request_id: "req-abc-123-def-456",
      },
    },
  };
}

describe("ErrorState — production-mode rendering (no internals leak)", () => {
  beforeEach(() => {
    setNodeEnv("production");
  });
  afterEach(() => {
    cleanup();
    setNodeEnv(
      ORIGINAL_NODE_ENV as "development" | "production" | "test" | undefined,
    );
    vi.clearAllMocks();
  });

  it("renders the user-friendly title + body and nothing else from the dev panel", () => {
    render(<ErrorState {...devProps()} />);

    // User-friendly copy still present.
    expect(screen.getByText(STRINGS.error.networkTitle)).toBeInTheDocument();
    expect(screen.getByText(STRINGS.error.networkBody)).toBeInTheDocument();

    // The dev panel itself must not exist in the DOM.
    expect(screen.queryByTestId("error-state-dev-panel")).toBeNull();

    // None of the dev-only labels should leak.
    expect(screen.queryByText(STRINGS.error.devOnlyCaption)).toBeNull();
    expect(screen.queryByText(/court_error/)).toBeNull();
    expect(screen.queryByText(/Read timed out/)).toBeNull();
    expect(screen.queryByText(/503/)).toBeNull();
  });
});

describe("ErrorState — dev-mode rendering (founder debugging surface)", () => {
  beforeEach(() => {
    setNodeEnv("development");
  });
  afterEach(() => {
    cleanup();
    setNodeEnv(
      ORIGINAL_NODE_ENV as "development" | "production" | "test" | undefined,
    );
    vi.clearAllMocks();
  });

  it("renders code, hint, request_id, raw message, http status and the raw body", () => {
    render(<ErrorState {...devProps()} />);

    expect(screen.getByTestId("error-state-dev-panel")).toBeInTheDocument();
    expect(screen.getByText(STRINGS.error.devOnlyCaption)).toBeInTheDocument();

    // Code pill.
    expect(screen.getByText("court_error")).toBeInTheDocument();
    // Hint.
    expect(
      screen.getByText("Upstream timed out; try again in a minute."),
    ).toBeInTheDocument();
    // Request id pill (the founder's grep target).
    expect(screen.getByTestId("error-state-dev-request-id")).toHaveTextContent(
      "req-abc-123-def-456",
    );
    // Raw technical message.
    expect(
      screen.getByText(
        "Read timed out after 12000ms talking to delhihighcourt.nic.in",
      ),
    ).toBeInTheDocument();
    // HTTP status.
    expect(screen.getByText("503")).toBeInTheDocument();

    // Raw body present inside the collapsible <details> as pretty-printed JSON.
    const details = screen.getByTestId("error-state-dev-details");
    expect(details).toBeInTheDocument();
    expect(details.textContent).toMatch(/"code": "court_error"/);
    expect(details.textContent).toMatch(/"retryable": true/);
  });

  it("renders the Details section closed by default", () => {
    render(<ErrorState {...devProps()} />);
    const details = screen.getByTestId("error-state-dev-details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
  });

  it("copies the request_id to the clipboard when Copy is clicked", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<ErrorState {...devProps()} />);
    const copyBtn = screen.getByRole("button", {
      name: STRINGS.error.devCopyRequestIdAria,
    });
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("req-abc-123-def-456");
    });
    // After a successful write the button label flips to "Copied".
    await waitFor(() => {
      expect(copyBtn).toHaveTextContent(STRINGS.error.devCopied);
    });
  });

  it("renders without crashing when hint and request_id are missing", () => {
    render(
      <ErrorState
        variant="unknown"
        onStartOver={vi.fn()}
        devErrorCode="internal_error"
        devRawMessage="boom"
        devHttpStatus={500}
        devRawBody={{ error: { code: "internal_error", message: "boom" } }}
        // intentionally no requestId, no devHint
      />,
    );

    expect(screen.getByTestId("error-state-dev-panel")).toBeInTheDocument();
    expect(screen.getByText("internal_error")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    // No request_id pill should render.
    expect(screen.queryByTestId("error-state-dev-request-id")).toBeNull();
    // No "hint:" label without a hint value.
    expect(screen.queryByText(`${STRINGS.error.devHintLabel}:`)).toBeNull();
  });

  it("renders a non-JSON raw body verbatim inside <pre>", () => {
    render(
      <ErrorState
        variant="unknown"
        onStartOver={vi.fn()}
        devErrorCode="unknown"
        devRawMessage="Unexpected response (HTTP 500)."
        devHttpStatus={500}
        devRawBody={"<html><body>500 Internal Server Error</body></html>"}
      />,
    );

    const details = screen.getByTestId("error-state-dev-details");
    expect(details.textContent).toMatch(/500 Internal Server Error/);
  });
});
