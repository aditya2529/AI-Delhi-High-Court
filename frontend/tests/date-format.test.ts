import { describe, expect, it, vi, afterEach } from "vitest";

import {
  formatCountdown,
  formatDate,
  isPastDate,
  secondsUntil,
} from "@/lib/date-format";

afterEach(() => {
  vi.useRealTimers();
});

describe("formatDate", () => {
  it("formats a UTC date in the canonical Wed, 17 May 2026 form", () => {
    expect(formatDate("2026-05-17")).toBe("Sun, 17 May 2026");
  });

  it("returns null for empty / invalid input", () => {
    expect(formatDate(null)).toBeNull();
    expect(formatDate(undefined)).toBeNull();
    expect(formatDate("not-a-date")).toBeNull();
  });
});

describe("isPastDate", () => {
  it("treats yesterday as past", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-17T08:00:00Z"));
    expect(isPastDate("2026-05-16")).toBe(true);
    expect(isPastDate("2026-05-17")).toBe(false);
    expect(isPastDate("2026-05-18")).toBe(false);
  });

  it("returns false for nullish", () => {
    expect(isPastDate(null)).toBe(false);
    expect(isPastDate(undefined)).toBe(false);
  });
});

describe("secondsUntil / formatCountdown", () => {
  it("computes positive seconds and never goes negative", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-17T10:00:00Z"));
    expect(secondsUntil("2026-05-17T10:00:42Z")).toBe(42);
    expect(secondsUntil("2026-05-17T09:59:00Z")).toBe(0);
  });

  it("formats mm:ss with zero-padding", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(7)).toBe("0:07");
    expect(formatCountdown(95)).toBe("1:35");
  });
});
