import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useShareText } from "./useShareText";

const writeText = vi.fn().mockResolvedValue(undefined);

function setShare(share?: (data: ShareData) => Promise<void>) {
  Object.defineProperty(navigator, "share", { value: share, configurable: true });
}

beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

afterEach(() => {
  setShare(undefined);
});

describe("useShareText", () => {
  it("hands title and text to navigator.share when present", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    setShare(share);
    const { result } = renderHook(() => useShareText());

    await act(async () => {
      await result.current.share("Title", "body");
    });

    expect(share).toHaveBeenCalledWith({ title: "Title", text: "body" });
    expect(writeText).not.toHaveBeenCalled();
    expect(result.current.copied).toBe(false);
  });

  it("does nothing when the user cancels the share sheet", async () => {
    setShare(vi.fn().mockRejectedValue(new DOMException("cancelled", "AbortError")));
    const { result } = renderHook(() => useShareText());

    await act(async () => {
      await result.current.share("Title", "body");
    });

    expect(writeText).not.toHaveBeenCalled();
    expect(result.current.copied).toBe(false);
  });

  it("copies to the clipboard when navigator.share fails", async () => {
    setShare(vi.fn().mockRejectedValue(new Error("boom")));
    const { result } = renderHook(() => useShareText());

    await act(async () => {
      await result.current.share("Title", "body");
    });

    expect(writeText).toHaveBeenCalledWith("body");
    expect(result.current.copied).toBe(true);
  });

  it("copies to the clipboard when navigator.share is missing", async () => {
    const { result } = renderHook(() => useShareText());

    await act(async () => {
      await result.current.share("Title", "body");
    });

    expect(writeText).toHaveBeenCalledWith("body");
    expect(result.current.copied).toBe(true);
  });
});
