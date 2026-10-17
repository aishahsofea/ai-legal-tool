import { useCallback } from "react";
import { useCopyToClipboard } from "./useCopyToClipboard";

export function useShareText() {
  const { copied, copy } = useCopyToClipboard();

  const share = useCallback(
    async (title: string, text: string) => {
      if (typeof navigator.share === "function") {
        try {
          await navigator.share({ title, text });
          return;
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return;
        }
      }
      await copy(text);
    },
    [copy],
  );

  return { copied, share };
}
