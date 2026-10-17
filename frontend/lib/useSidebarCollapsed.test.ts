import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useSidebarCollapsed } from "./useSidebarCollapsed";

const KEY = "locus.sidebar-collapsed.v1";

describe("useSidebarCollapsed", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("starts expanded", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(false);
  });

  it("restores a stored collapsed state", () => {
    window.localStorage.setItem(KEY, "1");
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(true);
  });

  it("persists on toggle", () => {
    const { result } = renderHook(() => useSidebarCollapsed());
    act(() => result.current[1]());
    expect(result.current[0]).toBe(true);
    expect(window.localStorage.getItem(KEY)).toBe("1");
    act(() => result.current[1]());
    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem(KEY)).toBe("0");
  });

  it("does not throw when localStorage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { result } = renderHook(() => useSidebarCollapsed());
    expect(result.current[0]).toBe(false);
    act(() => result.current[1]());
    expect(result.current[0]).toBe(true);
  });
});
