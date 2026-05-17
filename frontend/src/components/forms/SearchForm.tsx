"use client";

/**
 * SearchForm — collects (case_type, case_number, year) and emits a validated
 * payload to the parent SearchFlow.
 *
 * Validation is Zod-driven; the same schema underpins both the inline error
 * messages and the disabled-state of the Submit button. The backend will
 * re-validate (per API-CONTRACT §2) so we never trust the client-side check
 * alone.
 */

import { useId, useMemo, useState } from "react";
import { z } from "zod";

import {
  CASE_TYPES,
  DEFAULT_CASE_TYPE_VALUE,
  isKnownCaseType,
} from "@/lib/case-types";
import { STRINGS } from "@/lib/strings";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";

/** Year range — 1950 → current UTC year, descending so current year is first. */
function yearRangeDescending(): number[] {
  const current = new Date().getUTCFullYear();
  const years: number[] = [];
  for (let y = current; y >= 1950; y -= 1) years.push(y);
  return years;
}

export type SearchFormValues = {
  readonly caseType: string;
  readonly caseNumber: string;
  readonly year: number;
};

export type SearchFormProps = {
  /** Called with validated values; parent owns the network call. */
  readonly onSubmit: (values: SearchFormValues) => void | Promise<void>;
  /** True while parent is awaiting `/search/init`. */
  readonly submitting: boolean;
  /**
   * Optional initial values — used when the parent rebuilds the form after an
   * error and we want to preserve the user's inputs (US-04 AC-2, US-05 AC-3).
   */
  readonly initialValues?: Partial<SearchFormValues>;
  /**
   * Banner-level message from the parent (e.g. "CAPTCHA failed too many
   * times — please re-enter the case"). Optional.
   */
  readonly bannerMessage?: string;
};

// caseType is validated via a runtime membership check against the imported
// CASE_TYPES list (148 entries after the spike). Using `z.string().refine`
// instead of `z.enum` keeps the inferred type narrow (string) and avoids
// regenerating a 148-tuple-string TS type on every build — the runtime
// check is the same.
const FormSchema = z.object({
  caseType: z.string().refine(isKnownCaseType, {
    message: STRINGS.form.validationCaseType,
  }),
  caseNumber: z
    .string()
    .regex(/^\d{1,7}$/, STRINGS.form.validationCaseNumber),
  year: z
    .number({ invalid_type_error: STRINGS.form.validationYear })
    .int()
    .gte(1950, STRINGS.form.validationYear)
    .lte(new Date().getUTCFullYear(), STRINGS.form.validationYear),
});

type FieldErrors = {
  caseType?: string;
  caseNumber?: string;
  year?: string;
};

export function SearchForm({
  onSubmit,
  submitting,
  initialValues,
  bannerMessage,
}: SearchFormProps) {
  const years = useMemo(yearRangeDescending, []);
  const currentYear = years[0];

  const [caseType, setCaseType] = useState<string>(
    initialValues?.caseType ?? DEFAULT_CASE_TYPE_VALUE,
  );
  const [caseNumber, setCaseNumber] = useState<string>(
    initialValues?.caseNumber ?? "",
  );
  const [year, setYear] = useState<number>(initialValues?.year ?? currentYear);
  const [touched, setTouched] = useState<Record<keyof FieldErrors, boolean>>({
    caseType: false,
    caseNumber: false,
    year: false,
  });

  const caseTypeId = useId();
  const caseNumberId = useId();
  const yearId = useId();
  const caseTypeErrId = `${caseTypeId}-err`;
  const caseNumberErrId = `${caseNumberId}-err`;
  const yearErrId = `${yearId}-err`;

  const parseResult = FormSchema.safeParse({ caseType, caseNumber, year });
  const errors: FieldErrors = useMemo(() => {
    if (parseResult.success) return {};
    const out: FieldErrors = {};
    for (const issue of parseResult.error.issues) {
      const key = issue.path[0] as keyof FieldErrors | undefined;
      if (key && !out[key]) out[key] = issue.message;
    }
    return out;
  }, [parseResult]);

  const isValid = parseResult.success;

  function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    setTouched({ caseType: true, caseNumber: true, year: true });
    if (!parseResult.success || submitting) return;
    void onSubmit(parseResult.data);
  }

  return (
    <form
      className="space-y-5"
      onSubmit={handleSubmit}
      noValidate
      aria-busy={submitting}
    >
      {bannerMessage ? (
        <div
          role="alert"
          className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          {bannerMessage}
        </div>
      ) : null}

      <div>
        <label
          htmlFor={caseTypeId}
          className="block text-sm font-medium text-fg"
        >
          {STRINGS.form.caseTypeLabel}
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          {STRINGS.form.caseTypeHint}
        </p>
        <select
          id={caseTypeId}
          name="case_type"
          value={caseType}
          onChange={(e) => setCaseType(e.target.value)}
          onBlur={() => setTouched((t) => ({ ...t, caseType: true }))}
          aria-invalid={Boolean(touched.caseType && errors.caseType)}
          aria-describedby={
            touched.caseType && errors.caseType ? caseTypeErrId : undefined
          }
          disabled={submitting}
          className="mt-2 block w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent min-h-[44px]"
        >
          {/*
            No "— Select case type —" placeholder option: the form now
            defaults to DEFAULT_CASE_TYPE_VALUE (W.P.(C), per spike B.5)
            so the dropdown is always sat on a valid value out of the
            box. 148 options total, sorted alphabetically by label.
          */}
          {CASE_TYPES.map((ct) => (
            <option key={ct.value} value={ct.value}>
              {ct.label}
            </option>
          ))}
        </select>
        {touched.caseType && errors.caseType ? (
          <p id={caseTypeErrId} role="alert" className="mt-1 text-xs text-danger">
            {errors.caseType}
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor={caseNumberId}
          className="block text-sm font-medium text-fg"
        >
          {STRINGS.form.caseNumberLabel}
        </label>
        <p className="mt-1 text-xs text-fg-muted">
          {STRINGS.form.caseNumberHint}
        </p>
        <input
          id={caseNumberId}
          name="case_number"
          type="text"
          inputMode="numeric"
          autoComplete="off"
          pattern="\d*"
          maxLength={7}
          value={caseNumber}
          onChange={(e) =>
            setCaseNumber(e.target.value.replace(/\D/g, "").slice(0, 7))
          }
          onBlur={() => setTouched((t) => ({ ...t, caseNumber: true }))}
          aria-invalid={Boolean(touched.caseNumber && errors.caseNumber)}
          aria-describedby={
            touched.caseNumber && errors.caseNumber ? caseNumberErrId : undefined
          }
          disabled={submitting}
          className="mt-2 block w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent min-h-[44px]"
          placeholder="e.g. 1234"
        />
        {touched.caseNumber && errors.caseNumber ? (
          <p
            id={caseNumberErrId}
            role="alert"
            className="mt-1 text-xs text-danger"
          >
            {errors.caseNumber}
          </p>
        ) : null}
      </div>

      <div>
        <label htmlFor={yearId} className="block text-sm font-medium text-fg">
          {STRINGS.form.yearLabel}
        </label>
        <select
          id={yearId}
          name="year"
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          onBlur={() => setTouched((t) => ({ ...t, year: true }))}
          aria-invalid={Boolean(touched.year && errors.year)}
          aria-describedby={touched.year && errors.year ? yearErrId : undefined}
          disabled={submitting}
          className="mt-2 block w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 text-sm text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent min-h-[44px]"
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        {touched.year && errors.year ? (
          <p id={yearErrId} role="alert" className="mt-1 text-xs text-danger">
            {errors.year}
          </p>
        ) : null}
      </div>

      <Button
        type="submit"
        variant="primary"
        fullWidth
        disabled={!isValid || submitting}
        aria-label={STRINGS.form.submit}
      >
        {submitting ? (
          <>
            <Spinner size="sm" />
            <span>{STRINGS.form.submitting}</span>
          </>
        ) : (
          STRINGS.form.submit
        )}
      </Button>
    </form>
  );
}
