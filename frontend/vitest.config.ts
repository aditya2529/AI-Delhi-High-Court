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
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
