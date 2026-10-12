import { describe, expect, it } from "vitest";
import { formatBytes, formatMoney, formatMs, highlight } from "./format";

describe("highlight", () => {
  it("marks a quote even when whitespace differs", () => {
    const parts = highlight("The term ends on\nJanuary 14, 2027 unless renewed.", "ends on January 14, 2027");
    expect(parts.filter((p) => p.match).map((p) => p.text)).toEqual(["ends on\nJanuary 14, 2027"]);
    expect(parts.map((p) => p.text).join("")).toBe("The term ends on\nJanuary 14, 2027 unless renewed.");
  });

  it("escapes regex characters and tolerates missing quotes", () => {
    expect(highlight("Fee: $48,000 (annual)", "$48,000 (annual)").some((p) => p.match)).toBe(true);
    expect(highlight("abc", "zzz")).toEqual([{ text: "abc", match: false }]);
    expect(highlight("abc", null)).toEqual([{ text: "abc", match: false }]);
  });
});

describe("formatters", () => {
  it("formats sizes, durations and money", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatMs(850)).toBe("850 ms");
    expect(formatMs(2300)).toBe("2.3 s");
    expect(formatMs(null)).toBe("-");
    expect(formatMoney(48000, "USD")).toContain("48,000");
    expect(formatMoney(10, "NOT_A_CODE")).toBe("10 NOT_A_CODE");
  });
});
