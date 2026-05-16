/**
 * Minimal button primitive. We deliberately do NOT introduce a design-system
 * library — the MVP has 3-4 buttons total. This component centralizes the
 * focus ring and disabled handling so we keep WCAG AA contrast everywhere.
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  readonly variant?: ButtonVariant;
  readonly fullWidth?: boolean;
  readonly children: ReactNode;
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium " +
  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 " +
  "focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50 min-h-[44px]";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-blue-700",
  secondary:
    "bg-white text-fg border border-gray-300 hover:bg-gray-50 disabled:bg-gray-100",
  ghost: "bg-transparent text-accent hover:bg-blue-50",
  danger: "bg-danger text-white hover:bg-red-700",
};

export function Button({
  variant = "primary",
  fullWidth = false,
  className = "",
  type,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      className={`${BASE} ${VARIANTS[variant]} ${fullWidth ? "w-full" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
