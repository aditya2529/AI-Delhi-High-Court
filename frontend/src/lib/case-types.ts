/**
 * Delhi HC case-type vocabulary.
 *
 * Source: the FULL 148-option `<select>` enum observed on the live court
 * site during the Phase-0 stateful spike (Arnav, 2026-05-17). Raw capture
 * lives in `scripts/dev/spike_recon_output.json` under
 * `steps.5_case_type_enum.options_full`. See `docs/SPIKE-REPORT.md` §G,
 * row B.5 for the verification trail.
 *
 * Both `value` (sent to the upstream POST) and `label` (shown in the
 * dropdown) are the COURT'S verbatim option strings. This is deliberate:
 *
 *   * The POST body must echo the upstream `<option value="...">` exactly
 *     — every space, dot, parenthesis, and (sigh) the double-space in
 *     `EFA(OS)  (COMM)`. If we humanise the label we risk losing the
 *     exact byte sequence and the form submission silently 4xx's.
 *   * Lawyers searching for cases already type in the court's
 *     abbreviations as they appear; a humanised label ("First Appeal
 *     from Original Side (Commercial)") would slow them down.
 *   * Synonyms / spellings inside the list are the court's, not ours.
 *     `TR.P.(C)` and `TR.P.(C.)` are distinct entries upstream — we
 *     preserve them.
 *
 * Sort order: alphabetical by label (case-insensitive), so `ARB. A. (COMM.)`
 * sits next to `ARB.A.` rather than landing in a separate "starts-with-space"
 * cluster. Default selected value is `W.P.(C)` (the highest-volume case
 * type for lawyer end-users — confirmed with Priya).
 *
 * If new options appear on the upstream site, re-run the spike script and
 * regenerate this array verbatim — do not hand-edit individual entries.
 */
export type CaseType = {
  /** Exact value sent to the backend; matches the court's official abbreviation. */
  readonly value: string;
  /** Human-readable label shown in the dropdown. Verbatim copy of `value`. */
  readonly label: string;
};

/**
 * Default selection for the case-type `<select>`. Matches the historical
 * default that lawyers most commonly start from (civil writ petitions).
 */
export const DEFAULT_CASE_TYPE_VALUE = "W.P.(C)" as const;

/**
 * The full 148-option enum, sorted alphabetically by label
 * (case-insensitive). DO NOT REORDER manually — the sort is by the
 * locale-independent lowercase of `label` so insertion of a new option
 * is deterministic.
 */
export const CASE_TYPES: ReadonlyArray<CaseType> = [
  { value: "ADMIN.REPORT", label: "ADMIN.REPORT" },
  { value: "ARB. A. (COMM.)", label: "ARB. A. (COMM.)" },
  { value: "ARB.A.", label: "ARB.A." },
  { value: "ARB.P.", label: "ARB.P." },
  { value: "BAIL APPLN.", label: "BAIL APPLN." },
  { value: "C.A.(COMM.IPD-GI)", label: "C.A.(COMM.IPD-GI)" },
  { value: "C.A.(COMM.IPD-PAT)", label: "C.A.(COMM.IPD-PAT)" },
  { value: "C.A.(COMM.IPD-PV)", label: "C.A.(COMM.IPD-PV)" },
  { value: "C.A.(COMM.IPD-TM)", label: "C.A.(COMM.IPD-TM)" },
  { value: "C.O.", label: "C.O." },
  { value: "C.O. (COMM.IPD-TM)", label: "C.O. (COMM.IPD-TM)" },
  { value: "C.O.(COMM.IPD-CR)", label: "C.O.(COMM.IPD-CR)" },
  { value: "C.O.(COMM.IPD-GI)", label: "C.O.(COMM.IPD-GI)" },
  { value: "C.O.(COMM.IPD-PAT)", label: "C.O.(COMM.IPD-PAT)" },
  { value: "C.R.P.", label: "C.R.P." },
  { value: "C.REF.(O)", label: "C.REF.(O)" },
  { value: "C.RULE", label: "C.RULE" },
  { value: "CA", label: "CA" },
  { value: "CA (COMM.IPD-CR)", label: "CA (COMM.IPD-CR)" },
  { value: "CAVEAT(CO.)", label: "CAVEAT(CO.)" },
  { value: "CC(ARB.)", label: "CC(ARB.)" },
  { value: "CCP(CO.)", label: "CCP(CO.)" },
  { value: "CCP(REF)", label: "CCP(REF)" },
  { value: "CEAC", label: "CEAC" },
  { value: "CEAR", label: "CEAR" },
  { value: "CHAT.A.C.", label: "CHAT.A.C." },
  { value: "CHAT.A.REF", label: "CHAT.A.REF" },
  { value: "CM(M)", label: "CM(M)" },
  { value: "CM(M)-IPD", label: "CM(M)-IPD" },
  { value: "CMI", label: "CMI" },
  { value: "CO.A(SB)", label: "CO.A(SB)" },
  { value: "CO.APP.", label: "CO.APP." },
  { value: "CO.APPL.(C)", label: "CO.APPL.(C)" },
  { value: "CO.APPL.(M)", label: "CO.APPL.(M)" },
  { value: "CO.EX.", label: "CO.EX." },
  { value: "CO.PET.", label: "CO.PET." },
  { value: "CONT.APP.(C)", label: "CONT.APP.(C)" },
  { value: "CONT.CAS(C)", label: "CONT.CAS(C)" },
  { value: "CONT.CAS.(CRL)", label: "CONT.CAS.(CRL)" },
  { value: "CRL.A.", label: "CRL.A." },
  { value: "CRL.L.P.", label: "CRL.L.P." },
  { value: "CRL.M.(CO.)", label: "CRL.M.(CO.)" },
  { value: "CRL.M.C.", label: "CRL.M.C." },
  { value: "CRL.M.I.", label: "CRL.M.I." },
  { value: "CRL.O.", label: "CRL.O." },
  { value: "CRL.O.(CO.)", label: "CRL.O.(CO.)" },
  { value: "CRL.REF.", label: "CRL.REF." },
  { value: "CRL.REV.P.", label: "CRL.REV.P." },
  { value: "CRL.REV.P.(MAT.)", label: "CRL.REV.P.(MAT.)" },
  { value: "CRL.REV.P.(NDPS)", label: "CRL.REV.P.(NDPS)" },
  { value: "CRL.REV.P.(NI)", label: "CRL.REV.P.(NI)" },
  { value: "CRP-IPD", label: "CRP-IPD" },
  { value: "CS(COMM)", label: "CS(COMM)" },
  { value: "CS(COMM) INFRA", label: "CS(COMM) INFRA" },
  { value: "CS(OS)", label: "CS(OS)" },
  { value: "CS(OS) GP", label: "CS(OS) GP" },
  { value: "CUS.A.C.", label: "CUS.A.C." },
  { value: "CUS.A.R.", label: "CUS.A.R." },
  { value: "CUSAA", label: "CUSAA" },
  { value: "CUSTOM A.", label: "CUSTOM A." },
  { value: "DEATH SENTENCE REF.", label: "DEATH SENTENCE REF." },
  { value: "DEMO", label: "DEMO" },
  { value: "EDC", label: "EDC" },
  { value: "EDR", label: "EDR" },
  { value: "EFA(COMM)", label: "EFA(COMM)" },
  { value: "EFA(OS)", label: "EFA(OS)" },
  // Yes, that's a literal double space — verbatim from upstream. Do not normalise.
  { value: "EFA(OS)  (COMM)", label: "EFA(OS)  (COMM)" },
  { value: "EFA(OS)(IPD)", label: "EFA(OS)(IPD)" },
  { value: "EL.PET.", label: "EL.PET." },
  { value: "ETR", label: "ETR" },
  { value: "EX.F.A.", label: "EX.F.A." },
  { value: "EX.P.", label: "EX.P." },
  { value: "EX.S.A.", label: "EX.S.A." },
  { value: "FAO", label: "FAO" },
  { value: "FAO (COMM)", label: "FAO (COMM)" },
  { value: "FAO(OS)", label: "FAO(OS)" },
  { value: "FAO(OS) (COMM)", label: "FAO(OS) (COMM)" },
  { value: "FAO(OS)(IPD)", label: "FAO(OS)(IPD)" },
  { value: "FAO-IPD", label: "FAO-IPD" },
  { value: "GCAC", label: "GCAC" },
  { value: "GCAR", label: "GCAR" },
  { value: "GTA", label: "GTA" },
  { value: "GTC", label: "GTC" },
  { value: "GTR", label: "GTR" },
  { value: "I.A.", label: "I.A." },
  { value: "I.P.A.", label: "I.P.A." },
  { value: "ITA", label: "ITA" },
  { value: "ITC", label: "ITC" },
  { value: "ITR", label: "ITR" },
  { value: "ITSA", label: "ITSA" },
  { value: "LA.APP.", label: "LA.APP." },
  { value: "LPA", label: "LPA" },
  { value: "MAC.APP.", label: "MAC.APP." },
  { value: "MAT.", label: "MAT." },
  { value: "MAT.APP.", label: "MAT.APP." },
  { value: "MAT.APP.(F.C.)", label: "MAT.APP.(F.C.)" },
  { value: "MAT.CASE", label: "MAT.CASE" },
  { value: "MAT.REF.", label: "MAT.REF." },
  { value: "MISC. APPEAL (FEMA)", label: "MISC. APPEAL (FEMA)" },
  { value: "MISC. APPEAL(PMLA)", label: "MISC. APPEAL(PMLA)" },
  { value: "O.M.P.", label: "O.M.P." },
  { value: "O.M.P. (COMM)", label: "O.M.P. (COMM)" },
  { value: "O.M.P. (E)", label: "O.M.P. (E)" },
  { value: "O.M.P. (E) (COMM.)", label: "O.M.P. (E) (COMM.)" },
  { value: "O.M.P. (ENF.)", label: "O.M.P. (ENF.)" },
  { value: "O.M.P. (J) (COMM.)", label: "O.M.P. (J) (COMM.)" },
  { value: "O.M.P. (MISC.)", label: "O.M.P. (MISC.)" },
  { value: "O.M.P. (T) (COMM.)", label: "O.M.P. (T) (COMM.)" },
  { value: "O.M.P.(EFA)(COMM.)", label: "O.M.P.(EFA)(COMM.)" },
  { value: "O.M.P.(I)", label: "O.M.P.(I)" },
  { value: "O.M.P.(I) (COMM.)", label: "O.M.P.(I) (COMM.)" },
  { value: "O.M.P.(MISC.)(COMM.)", label: "O.M.P.(MISC.)(COMM.)" },
  { value: "O.M.P.(T)", label: "O.M.P.(T)" },
  { value: "O.REF.", label: "O.REF." },
  { value: "OA", label: "OA" },
  { value: "OCJA", label: "OCJA" },
  { value: "OMP (CONT.)", label: "OMP (CONT.)" },
  { value: "OMP (ENF.) (COMM.)", label: "OMP (ENF.) (COMM.)" },
  { value: "RC.REV.", label: "RC.REV." },
  { value: "RC.S.A.", label: "RC.S.A." },
  { value: "RERA APPEAL", label: "RERA APPEAL" },
  { value: "REVIEW PET.", label: "REVIEW PET." },
  { value: "RFA", label: "RFA" },
  { value: "RFA(COMM)", label: "RFA(COMM)" },
  { value: "RFA(OS)", label: "RFA(OS)" },
  { value: "RFA(OS)(COMM)", label: "RFA(OS)(COMM)" },
  { value: "RFA(OS)(IPD)", label: "RFA(OS)(IPD)" },
  { value: "RFA-IPD", label: "RFA-IPD" },
  { value: "RSA", label: "RSA" },
  { value: "SCA", label: "SCA" },
  { value: "SDR", label: "SDR" },
  { value: "SERTA", label: "SERTA" },
  { value: "ST.APPL.", label: "ST.APPL." },
  { value: "ST.REF.", label: "ST.REF." },
  { value: "STC", label: "STC" },
  { value: "SUR.T.REF.", label: "SUR.T.REF." },
  { value: "TEST.CAS.", label: "TEST.CAS." },
  // Yes — `TR.P.(C)` and `TR.P.(C.)` are BOTH distinct upstream entries.
  // The trailing-period difference is the court's, not a typo on our end.
  { value: "TR.P.(C)", label: "TR.P.(C)" },
  { value: "TR.P.(C.)", label: "TR.P.(C.)" },
  { value: "TR.P.(CRL.)", label: "TR.P.(CRL.)" },
  { value: "VAT APPEAL", label: "VAT APPEAL" },
  { value: "W.P.(C)", label: "W.P.(C)" },
  { value: "W.P.(C)-IPD", label: "W.P.(C)-IPD" },
  { value: "W.P.(CRL)", label: "W.P.(CRL)" },
  // Sibling to W.P.(C)-IPD with a different canonicalisation — upstream
  // keeps both, so we do too.
  { value: "WP(C)(IPD)", label: "WP(C)(IPD)" },
  { value: "WTA", label: "WTA" },
  { value: "WTC", label: "WTC" },
  { value: "WTR", label: "WTR" },
] as const;

/** Allowed values, used as the basis for runtime validation. */
export const CASE_TYPE_VALUES: readonly string[] = CASE_TYPES.map(
  (c) => c.value,
);

/**
 * O(1) membership check for runtime validation. Built once at module load.
 * The Zod schema in `SearchForm` keys its `refine()` on this; with 148
 * entries, a Set is meaningfully faster than `.includes()` on every keypress.
 */
const CASE_TYPE_VALUE_SET: ReadonlySet<string> = new Set(CASE_TYPE_VALUES);

/** True if the value is in our local vocabulary. */
export function isKnownCaseType(value: string): boolean {
  return CASE_TYPE_VALUE_SET.has(value);
}
