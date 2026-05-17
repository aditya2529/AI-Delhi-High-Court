"use client";

/**
 * CaseResult — renders a successfully-parsed case.
 *
 * Trust markers (per PRD R3, R7 and the SearchFlow brief):
 *   - Every result links back to the upstream court page via `source_url`.
 *   - When the backend sets `parser_degraded: true` on the submit response,
 *     we surface a degraded warning that directs the user to the official
 *     source. (The legacy `parse_confidence` field was removed from the UI
 *     contract — Bucket 2 drift #1. `parser_degraded` is now the sole
 *     authoritative signal.)
 *   - The footer carries the "unofficial wrapper" disclaimer.
 *
 * Security (per Sneha):
 *   - We render ONLY structured JSON. Every string passes through React,
 *     which escapes by default. There is no `dangerouslySetInnerHTML`
 *     anywhere in this tree, ever.
 */

import type { OrderOrJudgment, ParsedCase } from "@/types/api";
import { formatDate, isPastDate } from "@/lib/date-format";
import { statusToChip } from "@/lib/status-color";
import { STRINGS } from "@/lib/strings";
import { Button } from "@/components/ui/Button";

export type CaseResultProps = {
  readonly data: ParsedCase;
  /**
   * Authoritative backend hint that the parsed fields are partial. This is
   * the ONLY input that drives the degraded-warning UI; we no longer derive
   * it from a client-side confidence threshold.
   */
  readonly parserDegraded?: boolean;
  /** Parent resets to the form. */
  readonly onSearchAgain: () => void;
};

export function CaseResult({ data, parserDegraded, onSearchAgain }: CaseResultProps) {
  const chip = statusToChip(data.status);
  const showDegraded = parserDegraded === true;

  const nextHearing = formatDate(data.next_hearing_date);
  const lastHearing = formatDate(data.last_hearing_date);
  const nextHearingPast = isPastDate(data.next_hearing_date);

  return (
    <article className="space-y-5 rounded-md border border-gray-200 bg-white p-4 sm:p-6">
      <header className="space-y-2">
        <h2 className="break-words text-xl font-semibold text-fg sm:text-2xl">
          {data.case_type} {data.case_number}/{data.year}
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${chip.classes}`}
            aria-label={`${STRINGS.result.statusLabel}: ${data.status ?? STRINGS.result.notAvailable}`}
          >
            {STRINGS.result.statusLabel}: {data.status ?? STRINGS.result.notAvailable}
          </span>
        </div>
      </header>

      {showDegraded ? (
        <div
          role="alert"
          className="space-y-1 rounded-md border border-amber-300 bg-amber-50 px-3 py-3 text-sm text-amber-900"
        >
          <p className="font-medium">
            {STRINGS.result.parserDegradedTitle}
          </p>
          <p>{STRINGS.result.parserDegradedBody}</p>
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block font-medium text-accent underline decoration-accent/40 hover:decoration-accent"
          >
            {STRINGS.result.sourceLink} &rarr;
          </a>
        </div>
      ) : null}

      {/* Hearings */}
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label={STRINGS.result.nextHearing}>
          {nextHearing ? (
            <span
              className={nextHearingPast ? "text-fg-muted line-through" : "text-fg"}
            >
              {nextHearing}
              {nextHearingPast ? (
                <span className="ml-2 text-xs uppercase tracking-wide text-fg-muted">
                  {STRINGS.result.pastHearingTag}
                </span>
              ) : null}
            </span>
          ) : (
            <NotAvailable />
          )}
        </Field>

        <Field label={STRINGS.result.lastHearing}>
          {lastHearing ? <span className="text-fg">{lastHearing}</span> : <NotAvailable />}
        </Field>

        <Field label={STRINGS.result.benchLabel}>
          {data.judge_bench || data.court_no ? (
            <span className="text-fg">
              {data.court_no ? (
                <span className="block text-sm text-fg-muted">
                  {STRINGS.result.courtNoLabel}: {data.court_no}
                </span>
              ) : null}
              {data.judge_bench ? <span className="block">{data.judge_bench}</span> : null}
            </span>
          ) : (
            <NotAvailable />
          )}
        </Field>
      </dl>

      {/* Parties */}
      <section aria-label="Parties" className="space-y-3">
        <PartyList
          role={STRINGS.result.petitionerLabel}
          names={data.parties.petitioner}
          tone="bg-blue-50 text-blue-900 border-blue-200"
        />
        <PartyList
          role={STRINGS.result.respondentLabel}
          names={data.parties.respondent}
          tone="bg-purple-50 text-purple-900 border-purple-200"
        />
      </section>

      {/* Orders + Judgments */}
      <DocList
        title={STRINGS.result.ordersLabel}
        emptyText={STRINGS.result.noOrders}
        items={data.orders}
      />
      <DocList
        title={STRINGS.result.judgmentsLabel}
        emptyText={STRINGS.result.noJudgments}
        items={data.judgments}
      />

      {/* Source attribution — non-negotiable trust marker */}
      <footer className="space-y-3 border-t border-gray-200 pt-4">
        <a
          href={data.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block font-medium text-accent underline decoration-accent/40 hover:decoration-accent"
        >
          {STRINGS.result.sourceLink} &rarr;
        </a>
        <p className="text-xs text-fg-muted">{STRINGS.result.sourceAttribution}</p>
        <Button variant="secondary" fullWidth onClick={onSearchAgain}>
          {STRINGS.result.searchAgain}
        </Button>
      </footer>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function Field({
  label,
  children,
}: {
  readonly label: string;
  readonly children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-fg-muted">
        {label}
      </dt>
      <dd className="mt-1 text-sm">{children}</dd>
    </div>
  );
}

function NotAvailable() {
  return <span className="text-fg-muted italic">{STRINGS.result.notAvailable}</span>;
}

function PartyList({
  role,
  names,
  tone,
}: {
  readonly role: string;
  readonly names: readonly string[];
  readonly tone: string;
}) {
  if (!names || names.length === 0) {
    return (
      <div>
        <h3 className="text-xs font-medium uppercase tracking-wide text-fg-muted">
          {role}
        </h3>
        <p className="mt-1 text-sm">
          <NotAvailable />
        </p>
      </div>
    );
  }
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-fg-muted">
        {role}
      </h3>
      <ul className="mt-1 flex flex-wrap gap-1.5">
        {names.map((n, i) => (
          <li
            key={`${role}-${i}`}
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${tone}`}
          >
            {n}
          </li>
        ))}
      </ul>
    </div>
  );
}

function DocList({
  title,
  emptyText,
  items,
}: {
  readonly title: string;
  readonly emptyText: string;
  readonly items: readonly OrderOrJudgment[];
}) {
  return (
    <section aria-label={title}>
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-fg-muted italic">{emptyText}</p>
      ) : (
        <ul className="mt-2 divide-y divide-gray-200 border border-gray-200 rounded-md">
          {items.map((item, idx) => {
            const dateLabel = formatDate(item.date ?? null);
            return (
              <li key={`${title}-${idx}`} className="p-3 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium text-fg">{item.title}</span>
                  {dateLabel ? (
                    <span className="text-xs text-fg-muted">{dateLabel}</span>
                  ) : null}
                </div>
                {item.url ? (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-1 inline-block text-xs text-accent underline decoration-accent/40 hover:decoration-accent"
                  >
                    Open document &rarr;
                  </a>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
