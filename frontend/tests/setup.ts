/**
 * Vitest global setup — runs once per test file before any test code.
 *
 * Wires up `@testing-library/jest-dom` so component tests can use the
 * extended DOM matchers (`toBeInTheDocument`, `toBeDisabled`, etc.).
 *
 * Pure-logic tests (`environment: "node"`) don't touch the DOM, so the
 * jest-dom side-effects are harmless there.
 */
import "@testing-library/jest-dom/vitest";
