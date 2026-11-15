import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { palette } from "./palette";

const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");
const root = css.match(/:root\s*{([^}]*)}/)![1];

describe("palette", () => {
  it.each(Object.entries(palette))("%s is a variable defined in :root", (_key, value) => {
    const name = value.match(/^var\((--[\w-]+)\)$/)?.[1];
    expect(name, `${value} is not var(--x)`).toBeDefined();
    expect(root).toContain(`${name}:`);
  });
});
