import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, themeScript } from "./themeScript";

type Listener = () => void;

function stubMedia(initialDark: boolean) {
  const listeners = new Set<Listener>();
  const media = {
    matches: initialDark,
    addEventListener: (_: string, fn: Listener) => listeners.add(fn),
    removeEventListener: (_: string, fn: Listener) => listeners.delete(fn),
  };
  vi.stubGlobal("matchMedia", () => media);
  return (dark: boolean) => {
    media.matches = dark;
    listeners.forEach((fn) => fn());
  };
}

function stubStorage(value: string | null) {
  const store = new Map<string, string>();
  if (value !== null) store.set(THEME_STORAGE_KEY, value);
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, v: string) => store.set(key, v),
  });
  return store;
}

const run = () => new Function(themeScript)();
const theme = () => document.documentElement.dataset.theme;

describe("themeScript", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.theme;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the storage key from the plan", () => {
    expect(THEME_STORAGE_KEY).toBe("locus.theme.v1");
  });

  it("follows a dark OS when nothing is stored", () => {
    stubStorage(null);
    stubMedia(true);
    run();
    expect(theme()).toBe("dark");
  });

  it("follows a light OS when nothing is stored", () => {
    stubStorage(null);
    stubMedia(false);
    run();
    expect(theme()).toBe("light");
  });

  it("falls back to the OS value when storage is blocked", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
    });
    stubMedia(true);
    run();
    expect(theme()).toBe("dark");
  });

  it("flips with the OS while the choice is system", () => {
    stubStorage("system");
    const setOs = stubMedia(false);
    run();
    expect(theme()).toBe("light");
    setOs(true);
    expect(theme()).toBe("dark");
  });

  it("ignores OS changes under an explicit choice", () => {
    stubStorage("light");
    const setOs = stubMedia(false);
    run();
    setOs(true);
    expect(theme()).toBe("light");
  });

  it("ignores a stored value it does not know", () => {
    stubStorage("sepia");
    stubMedia(true);
    run();
    expect(theme()).toBe("dark");
  });

  it("stops following the OS once an explicit choice is stored later", () => {
    const store = stubStorage("system");
    const setOs = stubMedia(false);
    run();
    store.set(THEME_STORAGE_KEY, "light");
    setOs(true);
    expect(theme()).toBe("light");
  });
});
