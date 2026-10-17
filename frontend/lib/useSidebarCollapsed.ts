import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "locus.sidebar-collapsed.v1";

export function useSidebarCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the stored state after mount to match SSR markup.
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch {
      // Storage blocked: the sidebar just starts expanded.
    }
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // Storage blocked: the choice lasts for this page load only.
      }
      return next;
    });
  }, []);

  return [collapsed, toggle];
}
