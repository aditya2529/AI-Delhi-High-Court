/**
 * Heuristic mapping of upstream "Status" strings to a colour-coded chip.
 *
 * The court's status vocabulary is not formally enumerated — we get a free-text
 * string. The chips here are a best-effort visual hint; the underlying text is
 * always rendered verbatim alongside the colour, so a wrong guess degrades to
 * "looks neutral, reads correctly". Never the other way around.
 */
export type StatusTone = "green" | "amber" | "red" | "neutral";

export type StatusChipColors = {
  readonly tone: StatusTone;
  /** Tailwind classes for background + border + text, AA contrast safe. */
  readonly classes: string;
};

const TONE_CLASSES: Record<StatusTone, string> = {
  green: "bg-green-50 text-green-800 border-green-300",
  amber: "bg-amber-50 text-amber-900 border-amber-300",
  red: "bg-red-50 text-red-800 border-red-300",
  neutral: "bg-gray-100 text-gray-800 border-gray-300",
};

/** Lower-case substrings that indicate a "case is over" state. */
const GREEN_TOKENS = ["disposed", "dismissed", "withdrawn", "decided", "allowed"];

/** Lower-case substrings that indicate "case is alive / scheduled". */
const AMBER_TOKENS = [
  "pending",
  "reserved",
  "for hearing",
  "for orders",
  "for judgment",
  "for judgement",
  "listed",
  "adjourned",
];

/** Lower-case substrings that flag an unusual / blocking state. */
const RED_TOKENS = ["stayed", "abated", "rejected"];

export function statusToChip(rawStatus: string | null | undefined): StatusChipColors {
  if (!rawStatus) return { tone: "neutral", classes: TONE_CLASSES.neutral };

  const s = rawStatus.toLowerCase();

  if (RED_TOKENS.some((t) => s.includes(t))) {
    return { tone: "red", classes: TONE_CLASSES.red };
  }
  if (GREEN_TOKENS.some((t) => s.includes(t))) {
    return { tone: "green", classes: TONE_CLASSES.green };
  }
  if (AMBER_TOKENS.some((t) => s.includes(t))) {
    return { tone: "amber", classes: TONE_CLASSES.amber };
  }
  return { tone: "neutral", classes: TONE_CLASSES.neutral };
}
