import { useCallback, useEffect, useRef, useState } from "react";

const COPIED_RESET_MS = 1600;

function execCommandCopy(text: string): boolean {
  const node = document.createElement("textarea");
  node.value = text;
  node.setAttribute("readonly", "");
  node.style.position = "fixed";
  node.style.left = "-9999px";
  document.body.appendChild(node);
  try {
    node.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    node.remove();
  }
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Missing or denied Clipboard API (insecure origin, old browser): try the legacy path.
    return execCommandCopy(text);
  }
}

export function useCopyToClipboard() {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = useCallback(async (text: string) => {
    const ok = await copyText(text);
    if (!ok) return false;
    window.clearTimeout(timer.current);
    setCopied(true);
    timer.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS);
    return true;
  }, []);

  return { copied, copy };
}
