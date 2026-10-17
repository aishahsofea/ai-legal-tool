import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copyText, useCopyToClipboard } from "./useCopyToClipboard";

function setClipboard(writeText?: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: writeText ? { writeText } : undefined,
    configurable: true,
  });
}

function setExecCommand(result: boolean | Error) {
  const fn = vi.fn(() => {
    if (result instanceof Error) throw result;
    return result;
  });
  Object.defineProperty(document, "execCommand", {
    value: fn,
    configurable: true,
  });
  return fn;
}

describe("copyText", () => {
  beforeEach(() => {
    setExecCommand(true);
  });

  afterEach(() => {
    setClipboard(undefined);
  });

  it("uses navigator.clipboard.writeText when available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard(writeText);
    const exec = setExecCommand(true);

    expect(await copyText("hello")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(exec).not.toHaveBeenCalled();
  });

  it("falls back to execCommand when writeText rejects", async () => {
    setClipboard(vi.fn().mockRejectedValue(new Error("denied")));
    const exec = setExecCommand(true);

    expect(await copyText("hello")).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("falls back to execCommand when clipboard is missing", async () => {
    setClipboard(undefined);
    const exec = setExecCommand(true);

    expect(await copyText("hello")).toBe(true);
    expect(exec).toHaveBeenCalledWith("copy");
  });

  it("returns false without throwing when every path fails", async () => {
    setClipboard(undefined);
    setExecCommand(false);
    expect(await copyText("hello")).toBe(false);

    setExecCommand(new Error("boom"));
    expect(await copyText("hello")).toBe(false);
    expect(document.querySelector("textarea")).toBeNull();
  });
});

describe("useCopyToClipboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    setClipboard(undefined);
  });

  it("sets copied for 1600ms after a successful copy", async () => {
    setClipboard(vi.fn().mockResolvedValue(undefined));
    const { result } = renderHook(() => useCopyToClipboard());
    expect(result.current.copied).toBe(false);

    await act(async () => {
      await result.current.copy("hello");
    });
    expect(result.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1599);
    });
    expect(result.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.copied).toBe(false);
  });

  it("leaves copied false when the copy fails", async () => {
    setClipboard(undefined);
    setExecCommand(false);
    const { result } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current.copy("hello");
    });
    expect(result.current.copied).toBe(false);
  });

  it("restarts the timer on a repeat copy", async () => {
    setClipboard(vi.fn().mockResolvedValue(undefined));
    const { result } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current.copy("a");
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    await act(async () => {
      await result.current.copy("b");
    });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(result.current.copied).toBe(false);
  });

  it("clears the timer on unmount", async () => {
    setClipboard(vi.fn().mockResolvedValue(undefined));
    const { result, unmount } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current.copy("hello");
    });
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
