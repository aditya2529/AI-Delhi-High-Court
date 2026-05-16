/**
 * Delhi HC case-type vocabulary.
 *
 * Source of truth on the backend will be the court's published list, validated
 * server-side. The frontend keeps a manual subset for the dropdown so we can
 * extend it without a backend deploy. Add new entries here; the backend will
 * reject unknown values with `invalid_request` and the form's Zod schema will
 * surface a friendly inline error.
 *
 * Per the brief (SearchForm spec):
 *   "case_type is a select with at minimum: W.P.(C), CRL.M.C., FAO,
 *    BAIL APPLN., LPA — store a list ... so we can extend later"
 */
export type CaseType = {
  /** Exact value sent to the backend; matches the court's official abbreviation. */
  readonly value: string;
  /** Human-readable label shown in the dropdown. */
  readonly label: string;
  /** Tooltip text (longer description). */
  readonly description: string;
};

export const CASE_TYPES: ReadonlyArray<CaseType> = [
  {
    value: "W.P.(C)",
    label: "W.P.(C) — Writ Petition (Civil)",
    description: "Writ petition under Article 226 in civil matters.",
  },
  {
    value: "CRL.M.C.",
    label: "CRL.M.C. — Criminal Miscellaneous (Main)",
    description: "Petition under S. 482 CrPC / inherent powers of the High Court.",
  },
  {
    value: "FAO",
    label: "FAO — First Appeal from Order",
    description: "First appeal from an order under CPC.",
  },
  {
    value: "BAIL APPLN.",
    label: "BAIL APPLN. — Bail Application",
    description: "Application for bail before the High Court.",
  },
  {
    value: "LPA",
    label: "LPA — Letters Patent Appeal",
    description: "Intra-court appeal from a single-judge order.",
  },
  {
    value: "CRL.A.",
    label: "CRL.A. — Criminal Appeal",
    description: "Appeal in criminal proceedings.",
  },
  {
    value: "RFA",
    label: "RFA — Regular First Appeal",
    description: "Regular first appeal under CPC.",
  },
] as const;

/** Allowed values, for the Zod enum. */
export const CASE_TYPE_VALUES: readonly string[] = CASE_TYPES.map((c) => c.value);

/** True if the value is in our local vocabulary. */
export function isKnownCaseType(value: string): boolean {
  return CASE_TYPE_VALUES.includes(value);
}
