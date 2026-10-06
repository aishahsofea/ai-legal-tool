import { describe, expect, it } from "vitest";
import { headerState, selectRange, toggleShown } from "./selection";

const shown = ["a", "b", "c", "d", "e"];

describe("selectRange", () => {
  it("checks a forward range, inclusive", () => {
    const next = selectRange(shown, new Set(), "b", "d", true);
    expect([...next].sort()).toEqual(["b", "c", "d"]);
  });

  it("checks a backward range, inclusive", () => {
    const next = selectRange(shown, new Set(), "d", "b", true);
    expect([...next].sort()).toEqual(["b", "c", "d"]);
  });

  it("unchecks the range when checked is false", () => {
    const next = selectRange(shown, new Set(shown), "b", "d", false);
    expect([...next].sort()).toEqual(["a", "e"]);
  });

  it("keeps selections outside the range", () => {
    const next = selectRange(shown, new Set(["a", "hidden"]), "c", "d", true);
    expect([...next].sort()).toEqual(["a", "c", "d", "hidden"]);
  });

  it("acts as a single toggle with no anchor", () => {
    const next = selectRange(shown, new Set(), null, "c", true);
    expect([...next]).toEqual(["c"]);
  });

  it("acts as a single toggle when the anchor is hidden by a filter", () => {
    const next = selectRange(shown, new Set(), "hidden", "c", true);
    expect([...next]).toEqual(["c"]);
  });

  it("unchecks a single id when there is no usable anchor", () => {
    const next = selectRange(shown, new Set(["c", "d"]), null, "c", false);
    expect([...next]).toEqual(["d"]);
  });

  it("does not mutate the input set", () => {
    const selected = new Set(["a"]);
    selectRange(shown, selected, "b", "c", true);
    expect([...selected]).toEqual(["a"]);
  });
});

describe("headerState", () => {
  it("is none when no shown id is selected", () => {
    expect(headerState(shown, new Set())).toBe("none");
  });

  it("is some when part of the shown ids are selected", () => {
    expect(headerState(shown, new Set(["a", "c"]))).toBe("some");
  });

  it("is all when every shown id is selected", () => {
    expect(headerState(shown, new Set(shown))).toBe("all");
  });

  it("ignores hidden selected ids", () => {
    expect(headerState(shown, new Set(["hidden"]))).toBe("none");
    expect(headerState(shown, new Set([...shown, "hidden"]))).toBe("all");
  });

  it("is none for an empty shown list", () => {
    expect(headerState([], new Set(["hidden"]))).toBe("none");
  });
});

describe("toggleShown", () => {
  it("selects every shown id when not all are selected", () => {
    const next = toggleShown(shown, new Set(["a"]));
    expect([...next].sort()).toEqual(shown);
  });

  it("clears the shown ids when all are selected", () => {
    const next = toggleShown(shown, new Set(shown));
    expect(next.size).toBe(0);
  });

  it("keeps hidden selected ids when selecting", () => {
    const next = toggleShown(shown, new Set(["hidden"]));
    expect([...next].sort()).toEqual([...shown, "hidden"]);
  });

  it("keeps hidden selected ids when clearing", () => {
    const next = toggleShown(shown, new Set([...shown, "hidden"]));
    expect([...next]).toEqual(["hidden"]);
  });

  it("does not mutate the input set", () => {
    const selected = new Set(["a"]);
    toggleShown(shown, selected);
    expect([...selected]).toEqual(["a"]);
  });
});
