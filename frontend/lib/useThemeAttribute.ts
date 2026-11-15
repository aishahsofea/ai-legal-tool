import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

const read = () => document.documentElement.getAttribute("data-theme");

export function useThemeAttribute(): string | null {
  return useSyncExternalStore(subscribe, read, () => null);
}
