import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "app/globals.css"), "utf8");

type Rgba = [number, number, number, number];

function block(selector: RegExp): Record<string, string> {
  const body = css.match(selector)?.[1] ?? "";
  return Object.fromEntries(
    [...body.matchAll(/(--[\w-]+|color-scheme)\s*:\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]),
  );
}

const light = block(/:root\s*\{([^}]*)\}/);
const dark = block(/:root\[data-theme="dark"\]\s*\{([^}]*)\}/);

function parse(value: string): Rgba {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
  }
  const fn = value.match(/^rgba?\(([^)]+)\)$/);
  if (!fn) throw new Error(`unparseable colour: ${value}`);
  const [r, g, b, a = "1"] = fn[1].split(/[\s,/]+/).filter(Boolean);
  return [Number(r), Number(g), Number(b), Number(a)];
}

function flatten(fg: Rgba, bg: Rgba): Rgba {
  const a = fg[3];
  return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat(1) as Rgba;
}

function luminance([r, g, b]: Rgba): number {
  const [R, G, B] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}

function ratio(vars: Record<string, string>, fg: string, bg: string): number {
  const back = parse(vars[bg]);
  const [l1, l2] = [luminance(flatten(parse(vars[fg]), back)), luminance(back)];
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

describe("dark theme block", () => {
  it("overrides every variable defined in :root", () => {
    const missing = Object.keys(light).filter((name) => !(name in dark));
    expect(missing).toEqual([]);
  });

  it("sets color-scheme in both blocks", () => {
    expect(light["color-scheme"]).toBe("light");
    expect(dark["color-scheme"]).toBe("dark");
  });

  it("keeps the strong eval fills and their text as in light mode", () => {
    for (const name of ["--eval-pass-strong", "--eval-fail-strong", "--eval-on-strong"]) {
      expect(dark[name]).toBe(light[name]);
    }
  });

  it("uses a darker canvas than surface-soft and not pure black", () => {
    expect(dark["--canvas"]).not.toMatch(/^#0{6}$/);
    expect(luminance(parse(dark["--canvas"]))).toBeLessThan(0.05);
  });
});

describe("dark theme contrast (WCAG AA)", () => {
  const atLeast = (fg: string, bg: string, min: number) =>
    expect(ratio(dark, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(min);

  it.each(["--canvas", "--surface"])("text and accent reach 4.5:1 on %s", (bg) => {
    for (const fg of ["--text", "--text-muted", "--text-subtle", "--accent"]) atLeast(fg, bg, 4.5);
  });

  it("button text reaches 4.5:1 on its fill", () => {
    atLeast("--on-accent", "--accent", 4.5);
    atLeast("--on-danger", "--danger", 4.5);
  });

  it("status colours reach 4.5:1 on their soft backgrounds", () => {
    for (const name of ["success", "danger", "warning"]) atLeast(`--${name}`, `--${name}-soft`, 4.5);
  });

  it("eval text reaches 4.5:1 on both strong fills", () => {
    atLeast("--eval-on-strong", "--eval-pass-strong", 4.5);
    atLeast("--eval-on-strong", "--eval-fail-strong", 4.5);
  });

  it("graph label reaches 4.5:1 on the canvas", () => {
    atLeast("--graph-label", "--canvas", 4.5);
  });

  it("accent as a border reaches 3:1 on the surface", () => {
    atLeast("--accent", "--surface", 3);
  });

  it("logs the ratios for the PR description", () => {
    const rows = ["--text-muted", "--text-subtle", "--accent"].map((fg) => ({
      pair: fg,
      "on canvas": ratio(dark, fg, "--canvas").toFixed(2),
      "on surface": ratio(dark, fg, "--surface").toFixed(2),
    }));
    console.table(rows);
    expect(rows).toHaveLength(3);
  });
});
