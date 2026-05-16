import type { Config } from "tailwindcss";

/**
 * Tailwind config for the Delhi HC Case Tracker frontend.
 *
 * Mobile-first by default. Brand tokens mirror the values that were already
 * inlined in `globals.css` so the disclaimer banner / header remain visually
 * unchanged after the migration to Tailwind.
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
        bg: "#f7f8fa",
        fg: "#1d2330",
        "fg-muted": "#5b6675",
        accent: "#1b6cb0",
        warn: "#b8860b",
        danger: "#b03a3a",
        success: "#1f7a4a",
      },
      borderRadius: {
        md: "10px",
      },
      maxWidth: {
        content: "640px",
      },
    },
  },
  plugins: [],
};

export default config;
