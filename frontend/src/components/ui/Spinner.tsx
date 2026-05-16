/**
 * Small spinner used in loading states. Respects `prefers-reduced-motion`
 * via the `.dhc-spin` class declared in globals.css (motion-reduce media
 * query disables the animation).
 */
import { STRINGS as _STRINGS } from "@/lib/strings";

export type SpinnerProps = {
  readonly label?: string;
  readonly size?: "sm" | "md" | "lg";
};

const SIZE_CLASSES: Record<NonNullable<SpinnerProps["size"]>, string> = {
  sm: "h-4 w-4 border-2",
  md: "h-6 w-6 border-2",
  lg: "h-10 w-10 border-4",
};

export function Spinner({ label, size = "md" }: SpinnerProps) {
  // `_STRINGS` import kept so the strings file is part of the dependency graph
  // and tree-shaken if unused — purely a hint for future i18n integration.
  void _STRINGS;
  return (
    <div role="status" className="inline-flex items-center gap-2 text-fg-muted">
      <span
        aria-hidden="true"
        className={`dhc-spin inline-block animate-spin rounded-full border-gray-300 border-t-accent ${SIZE_CLASSES[size]}`}
      />
      {label ? <span className="text-sm">{label}</span> : <span className="sr-only">Loading</span>}
    </div>
  );
}
