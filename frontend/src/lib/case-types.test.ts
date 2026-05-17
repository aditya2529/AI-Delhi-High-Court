/**
 * Round-trip unit tests for the Delhi HC case-type vocabulary.
 *
 * After the `z.enum() → z.string().refine()` switch in `SearchForm`,
 * exhaustiveness checking moved from compile-time (TypeScript narrowed
 * the enum) to runtime (the Zod refine() asks `isKnownCaseType`). Without
 * these tests, two regressions can slip past type-check:
 *
 *   1. `CASE_TYPES` and the `CASE_TYPE_VALUE_SET` membership check
 *      drift apart (someone re-sorts or filters one but not the other,
 *      and runtime validation silently accepts/rejects the wrong set).
 *   2. The 148-entry vocabulary is mutated by accident — a stray
 *      hand-edit during a merge — and the upstream form submission
 *      starts 4xx'ing on a previously valid case type.
 *
 * Pure logic test: no React, no jsdom, no fixtures.
 */
import { describe, expect, it } from "vitest";

import {
  CASE_TYPES,
  CASE_TYPE_VALUES,
  DEFAULT_CASE_TYPE_VALUE,
  isKnownCaseType,
} from "@/lib/case-types";

describe("CASE_TYPES vocabulary", () => {
  it("has exactly 148 entries (locked by upstream spike capture B.5)", () => {
    // Exact-count guard. If upstream adds/removes options, re-run the
    // spike script and regenerate the array verbatim — do NOT loosen
    // this assertion to `>=` or a range; the count IS the contract.
    expect(CASE_TYPES.length).toBe(148);
    // Belt-and-braces: the derived values array must mirror.
    expect(CASE_TYPE_VALUES.length).toBe(148);
  });

  it("round-trips every entry through isKnownCaseType (membership ↔ list)", () => {
    // The Set in case-types.ts is built from CASE_TYPE_VALUES at module
    // load. This test guarantees that if someone re-sorts or rewrites
    // the array without rebuilding the Set, the divergence shows up
    // here rather than as a silent 4xx in production.
    const missing: string[] = [];
    for (const entry of CASE_TYPES) {
      if (!isKnownCaseType(entry.value)) {
        missing.push(entry.value);
      }
    }
    expect(missing).toEqual([]);
  });

  it("default value is W.P.(C) (the lawyer-confirmed highest-volume type)", () => {
    expect(DEFAULT_CASE_TYPE_VALUE).toBe("W.P.(C)");
    // And — defence in depth — the default MUST itself be a member.
    // If someone changes the default to a value that isn't in the list,
    // the form would render but every submit would fail validation.
    expect(isKnownCaseType(DEFAULT_CASE_TYPE_VALUE)).toBe(true);
  });

  it("isKnownCaseType returns true for a known canonical value", () => {
    expect(isKnownCaseType("W.P.(C)")).toBe(true);
  });

  it("isKnownCaseType returns false for an unknown value", () => {
    expect(isKnownCaseType("NOT_A_REAL_CASE_TYPE")).toBe(false);
  });

  it("is sorted alphabetically by label (case-insensitive raw lex)", () => {
    // The doc comment in case-types.ts pins the sort order. The file
    // ships sorted by lowercased RAW codepoint order — not the locale-
    // aware `localeCompare` order, which would invert the
    // `TR.P.(C)` vs `TR.P.(C.)` pair (period vs close-paren rank
    // differs between raw codepoints and locale collation).
    //
    // This test pins the raw-lex contract that matches the file as
    // shipped. If the upstream regeneration script is ever changed to
    // emit `localeCompare` order, update the file AND this comparator
    // together — one PR, not two.
    const labels = CASE_TYPES.map((c) => c.label);
    const lex = (a: string, b: string) => {
      const al = a.toLowerCase();
      const bl = b.toLowerCase();
      if (al < bl) return -1;
      if (al > bl) return 1;
      return 0;
    };
    const expected = [...labels].sort(lex);
    expect(labels).toEqual(expected);
  });
});
