import { useCallback, useEffect, useState } from "react";
import { THEME_STORAGE_KEY } from "@/app/themeScript";

export type ThemeChoice = "light" | "dark" | "system";

const osDark = () => window.matchMedia("(prefers-color-scheme: dark)");

function apply(choice: ThemeChoice) {
  document.documentElement.dataset.theme = choice === "system" ? (osDark().matches ? "dark" : "light") : choice;
}

function readStored(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage blocked: fall through to following the OS.
  }
  return "system";
}

export function useTheme(): [ThemeChoice | null, (next: ThemeChoice) => void] {
  const [choice, setChoiceState] = useState<ThemeChoice | null>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the stored choice after mount to match SSR markup.
    setChoiceState(readStored());
  }, []);

  useEffect(() => {
    if (choice !== "system") return;
    const media = osDark();
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const setChoice = useCallback((next: ThemeChoice) => {
    try {
      // "system" is stored as absence so the inline script falls back to the OS.
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts for this page load only.
    }
    apply(next);
    setChoiceState(next);
  }, []);

  return [choice, setChoice];
}
