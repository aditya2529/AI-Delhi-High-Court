/**
 * Lightweight date helpers for rendering RFC3339 dates from the backend.
 *
 * We deliberately do NOT pull in date-fns / dayjs — the formatting need is tiny
 * (one canonical format) and Intl.DateTimeFormat is in every modern runtime.
 */

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

/**
 * Format an ISO-8601 date (with or without time) into the canonical
 * `Wed, 17 May 2026` form used across the UI per PRD §6 row 15 (date
 * normalization) and the result-card spec.
 *
 * Returns null on unparseable input; callers should render "Not available".
 */
export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  // Use UTC accessors — the backend ships date-only (or Z-suffixed) values;
  // local-tz drift can move dates by a day, which is the wrong default for
  // court calendars.
  const dow = WEEKDAYS[d.getUTCDay()];
  const day = d.getUTCDate();
  const mon = MONTHS[d.getUTCMonth()];
  const year = d.getUTCFullYear();
  return `${dow}, ${day} ${mon} ${year}`;
}

/**
 * True if the given ISO date is strictly before today's UTC date.
 * Used to dim past hearing dates per US-03 AC-3.
 */
export function isPastDate(iso: string | null | undefined): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  const todayUtc = new Date();
  const todayMid = Date.UTC(
    todayUtc.getUTCFullYear(),
    todayUtc.getUTCMonth(),
    todayUtc.getUTCDate(),
  );
  const dMid = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  return dMid < todayMid;
}

/**
 * mm:ss countdown from "now" to the given ISO instant. Returns "0:00" when
 * `iso` is in the past or unparseable, so the UI never shows NaN.
 */
export function secondsUntil(iso: string | null | undefined): number {
  if (!iso) return 0;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return 0;
  return Math.max(0, Math.floor((target - Date.now()) / 1000));
}

/** Pretty mm:ss representation of `secs` (e.g. 42 → `0:42`, 95 → `1:35`). */
export function formatCountdown(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}
