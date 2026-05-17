import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * Vitest config for the frontend.
 *
 * We test PURE LOGIC (Zod schemas, reducer-ish helpers, date/status helpers)
 * here. Component-render tests are deferred — adding @testing-library/react
 * is a separate scoped change. Playwright owns the user-flow E2E story.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "node",
    // Pick up both the central `tests/` suite AND tests colocated next to
    // the module they cover under `src/`. Colocation is allowed for pure
    // logic tests (no rendering) — e.g. `src/lib/case-types.test.ts`.
    include: [
      "tests/**/*.test.{ts,tsx}",
      "src/**/*.test.{ts,tsx}",
    ],
  },
});
