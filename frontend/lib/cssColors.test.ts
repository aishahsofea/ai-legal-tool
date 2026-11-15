import { afterEach, describe, expect, it } from "vitest";
import { resolveColors } from "./cssColors";

afterEach(() => document.documentElement.removeAttribute("style"));

describe("resolveColors", () => {
  it("reads each named property from the root element", () => {
    document.documentElement.style.setProperty("--a", " #112233 ");
    document.documentElement.style.setProperty("--b", "rgb(1, 2, 3)");
    expect(resolveColors(["--a", "--b"])).toEqual({ "--a": "#112233", "--b": "rgb(1, 2, 3)" });
  });

  it("returns an empty string for an undefined property", () => {
    expect(resolveColors(["--missing"])).toEqual({ "--missing": "" });
  });
});
