import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY } from "@/app/themeScript";
import { useTheme } from "./useTheme";

function stubMedia(initialDark: boolean) {
  const listeners = new Set<() => void>();
  const media = {
    matches: initialDark,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  };
  vi.stubGlobal("matchMedia", () => media);
  return (dark: boolean) => {
    media.matches = dark;
    act(() => listeners.forEach((fn) => fn()));
  };
}

const theme = () => document.documentElement.dataset.theme;

describe("useTheme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the stored choice after mount", () => {
    stubMedia(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("dark");
  });

  it("defaults to system when nothing valid is stored", () => {
    stubMedia(false);
    window.localStorage.setItem(THEME_STORAGE_KEY, "sepia");
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("system");
  });

  it("still works when storage is blocked", () => {
    stubMedia(true);
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    });
    const { result } = renderHook(() => useTheme());
    expect(result.current[0]).toBe("system");
    act(() => result.current[1]("dark"));
    expect(result.current[0]).toBe("dark");
    expect(theme()).toBe("dark");
  });

  it("persists an explicit choice and applies it", () => {
    stubMedia(true);
    const { result } = renderHook(() => useTheme());
    act(() => result.current[1]("light"));
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(theme()).toBe("light");
  });

  it("follows the OS under system and stops under an explicit choice", () => {
    const setOs = stubMedia(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current[1]("system"));
    expect(theme()).toBe("light");
    setOs(true);
    expect(theme()).toBe("dark");
    act(() => result.current[1]("light"));
    setOs(false);
    setOs(true);
    expect(theme()).toBe("light");
  });
});
