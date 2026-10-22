import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "locus.sidebar-collapsed.v1";

function persist(next: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // Storage blocked: the choice lasts for this page load only.
  }
}

export function useSidebarCollapsed(): [boolean, () => void, (next: boolean) => void] {
  const [collapsed, setCollapsedState] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the stored state after mount to match SSR markup.
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setCollapsedState(true);
    } catch {
      // Storage blocked: the sidebar just starts expanded.
    }
  }, []);

  const toggle = useCallback(() => {
    setCollapsedState((current) => {
      const next = !current;
      persist(next);
      return next;
    });
  }, []);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    persist(next);
  }, []);

  return [collapsed, toggle, setCollapsed];
}
