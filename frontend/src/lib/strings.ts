/**
 * Central string constants for the search-flow UI.
 *
 * Acts as the "i18n keys" stand-in per the team's coding standards:
 *   "No hardcoded strings — use i18n keys or a constants file."
 *
 * If/when the MVP adds Hindi (Phase 2), this file is replaced with an i18n
 * library; callers stay the same.
 */

export const STRINGS = {
  // Form
  form: {
    title: "Track a Delhi High Court case",
    caseTypeLabel: "Case type",
    caseTypeHint: "Pick the official Delhi HC abbreviation.",
    caseNumberLabel: "Case number",
    caseNumberHint: "Digits only, no slash.",
    yearLabel: "Year",
    submit: "Fetch status",
    submitting: "Connecting to Delhi HC…",
    validationCaseType: "Please choose a case type.",
    validationCaseNumber: "Case number must be 1–7 digits.",
    validationYear: "Year must be between 1950 and the current year.",
  },

  // CAPTCHA
  captcha: {
    title: "Solve the court's CAPTCHA",
    description:
      "We don't bypass court security. Type the characters you see, exactly as shown.",
    inputLabel: "Type the answer or characters from the image",
    inputHint:
      "If the image shows a math question (e.g. 19 + 3 =), type the answer. Otherwise type the characters exactly as shown.",
    refresh: "Refresh CAPTCHA",
    submit: "Submit",
    submitting: "Submitting…",
    expiresIn: "Refreshes in",
    expired: "CAPTCHA expired — please type the new one",
    captchaMismatch: "That CAPTCHA didn't match. Refreshing…",
    altText: "CAPTCHA — type the characters you see",
    attemptsRemaining: "Attempts remaining",
    tooManyFailures:
      "Three CAPTCHA attempts failed. Please start a new search.",
    startOver: "Start a new search",
  },

  // Result
  result: {
    statusLabel: "Status",
    nextHearing: "Next hearing",
    lastHearing: "Last hearing",
    benchLabel: "Bench",
    courtNoLabel: "Court no.",
    petitionerLabel: "Petitioner",
    respondentLabel: "Respondent",
    ordersLabel: "Orders",
    judgmentsLabel: "Judgments",
    sourceLink: "View on Delhi High Court",
    searchAgain: "Search again",
    notAvailable: "Not available",
    pastHearingTag: "Past hearing",
    parserDegradedTitle:
      "We couldn't read the full court page. Open the official version",
    parserDegradedBody:
      "Some fields may be missing. The Delhi High Court page is authoritative.",
    sourceAttribution:
      "Source: Delhi High Court public case-status portal.",
    noOrders: "No orders published.",
    noJudgments: "No judgments published.",
  },

  // Errors
  error: {
    courtErrorTitle: "Delhi HC site is slow or unreachable right now",
    courtErrorBody:
      "We tried, but the court's server didn't respond. This usually clears in a minute or two.",
    notFoundTitle: "No case found",
    notFoundBody:
      "Check the case type, number, and year. Common mistakes: wrong year, transposed digits, or the wrong abbreviation.",
    networkTitle: "Something went wrong on our end",
    networkBody:
      "We couldn't complete this request. The error has been logged.",
    unknownTitle: "Unexpected error",
    unknownBody:
      "Something went wrong we don't have a label for yet. Please try again.",
    requestIdLabel: "Reference",
    retry: "Try again",
    startOver: "Start a new search",
    openCourt: "Open the official Delhi HC page",
    wrapperDisclaimer:
      "This is a third-party wrapper. The Delhi High Court's own site remains the authoritative source.",
    // Dev-mode-only debugging affordances. NEVER rendered in production builds
    // (see ErrorState — every dev field is gated on NODE_ENV !== "production").
    devOnlyCaption: "DEV ONLY — not shown in production",
    devCodeLabel: "code",
    devHintLabel: "hint",
    devRequestIdLabel: "request_id",
    devRawMessageLabel: "raw message",
    devHttpStatusLabel: "HTTP status",
    devDetailsSummary: "Details (raw response)",
    devCopy: "Copy",
    devCopied: "Copied",
    devCopyRequestIdAria: "Copy request_id to clipboard",
  },

  // Generic
  loading: {
    submittingTitle: "Submitting your search to Delhi HC…",
    submittingBody: "This usually takes 5–12 seconds.",
  },
} as const;
