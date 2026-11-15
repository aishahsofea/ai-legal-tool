import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useThemeAttribute } from "./useThemeAttribute";

afterEach(() => document.documentElement.removeAttribute("data-theme"));

describe("useThemeAttribute", () => {
  it("returns the current data-theme", () => {
    document.documentElement.dataset.theme = "dark";
    const { result } = renderHook(() => useThemeAttribute());
    expect(result.current).toBe("dark");
  });

  it("returns null when the attribute is unset", () => {
    const { result } = renderHook(() => useThemeAttribute());
    expect(result.current).toBeNull();
  });

  it("updates when the attribute changes", async () => {
    document.documentElement.dataset.theme = "light";
    const { result } = renderHook(() => useThemeAttribute());
    await act(async () => {
      document.documentElement.dataset.theme = "dark";
      await Promise.resolve();
    });
    expect(result.current).toBe("dark");
  });
});
