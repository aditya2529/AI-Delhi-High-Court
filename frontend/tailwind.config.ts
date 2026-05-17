import type { Config } from "tailwindcss";

/**
 * Tailwind config — Apple-inspired dark theme.
 *
 * Semantic color tokens (bg/fg/fg-muted/accent/etc.) point at Apple's
 * dark-mode system palette. Components using these tokens auto-adopt
 * the new theme; hardcoded Tailwind classes (bg-white, bg-gray-*,
 * border-gray-*) are overridden in globals.css for the same effect.
 *
 * Typography: 17px base, SF Pro stack, generous line-height for
 * readability at high prescriptions.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Apple system dark palette
        bg: "#000000",
        surface: "#1c1c1e",
        "surface-elevated": "#2c2c2e",
        "surface-raised": "#3a3a3c",
        border: "#38383a",
        "border-subtle": "#2c2c2e",
        fg: "#f5f5f7",
        "fg-muted": "#c7c7cc",
        "fg-subtle": "#98989d",
        accent: "#0a84ff",
        "accent-hover": "#409cff",
        warn: "#ff9f0a",
        danger: "#ff453a",
        success: "#30d158",
      },
      borderRadius: {
        md: "12px",
        lg: "16px",
      },
      maxWidth: {
        content: "680px",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Text",
          "SF Pro Display",
          "Helvetica Neue",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      fontSize: {
        // Bumped one notch each — friendlier to high prescriptions
        xs: ["13px", { lineHeight: "1.45" }],
        sm: ["15px", { lineHeight: "1.5" }],
        base: ["17px", { lineHeight: "1.55" }],
        lg: ["19px", { lineHeight: "1.5" }],
        xl: ["22px", { lineHeight: "1.4" }],
        "2xl": ["28px", { lineHeight: "1.3", letterSpacing: "-0.022em" }],
        "3xl": ["34px", { lineHeight: "1.2", letterSpacing: "-0.022em" }],
      },
    },
  },
  plugins: [],
};

export default config;
