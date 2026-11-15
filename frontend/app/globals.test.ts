import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
const themeBlocks = /:root(\[data-theme="dark"\])?\s*\{[^}]*\}/g;

describe("globals.css", () => {
  it("has no hardcoded colours outside the theme blocks", () => {
    const rest = css.replace(themeBlocks, "");
    expect(rest.match(/#[0-9a-f]{3,8}\b|rgba?\(/gi) ?? []).toEqual([]);
  });
});
