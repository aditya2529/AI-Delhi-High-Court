"use client";

import { useState } from "react";

/**
 * SearchFlow — top-level stateful component coordinating the three
 * sub-steps of the case-search flow:
 *
 *   1. SearchForm           — collect (case_type, case_number, year)
 *   2. CaptchaChallenge     — show the court CAPTCHA + collect user input
 *   3. CaseResult           — render the parsed result OR a graceful failure
 *
 * State is local to the page; we don't use any global store in MVP (one
 * search at a time, no cross-page navigation needed).
 *
 * This is a SKELETON — wire-level only. Real children land in Sara's sprint
 * per the engineering backlog.
 */
type FlowState =
  | { phase: "form" }
  | { phase: "captcha"; sessionId: string; captchaImageB64: string; expiresAt: string }
  | { phase: "loading" }
  | { phase: "result"; data: unknown }
  | { phase: "error"; code: string; message: string; retryable: boolean };

export function SearchFlow() {
  const [state, setState] = useState<FlowState>({ phase: "form" });

  switch (state.phase) {
    case "form":
      return <PlaceholderBlock label="SearchForm (Sara's sprint)" />;
    case "captcha":
      return <PlaceholderBlock label={`Captcha challenge — session ${state.sessionId.slice(0, 8)}…`} />;
    case "loading":
      return <PlaceholderBlock label="Loading parsed result…" />;
    case "result":
      return <PlaceholderBlock label="CaseResult (Sara's sprint)" />;
    case "error":
      return <PlaceholderBlock label={`Error: ${state.code} — ${state.message}`} />;
  }
}

function PlaceholderBlock({ label }: { label: string }) {
  return (
    <div
      style={{
        border: "1px dashed #c8ced8",
        borderRadius: 10,
        padding: 24,
        textAlign: "center",
        color: "#5b6675",
      }}
    >
      {label}
    </div>
  );
}
