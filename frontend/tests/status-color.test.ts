import { describe, expect, it } from "vitest";

import { statusToChip } from "@/lib/status-color";

describe("statusToChip", () => {
  it("maps disposed / dismissed to green", () => {
    expect(statusToChip("Disposed").tone).toBe("green");
    expect(statusToChip("Dismissed in default").tone).toBe("green");
  });

  it("maps pending / reserved to amber", () => {
    expect(statusToChip("Pending").tone).toBe("amber");
    expect(statusToChip("Reserved for Judgment").tone).toBe("amber");
    expect(statusToChip("LISTED for hearing").tone).toBe("amber");
  });

  it("maps stayed / abated to red", () => {
    expect(statusToChip("Stayed").tone).toBe("red");
    expect(statusToChip("ABATED").tone).toBe("red");
  });

  it("falls back to neutral on unknown / nullish", () => {
    expect(statusToChip(null).tone).toBe("neutral");
    expect(statusToChip(undefined).tone).toBe("neutral");
    expect(statusToChip("something we've never seen").tone).toBe("neutral");
  });
});
