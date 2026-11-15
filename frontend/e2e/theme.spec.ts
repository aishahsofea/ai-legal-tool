import { expect, test } from "@playwright/test";

const CREAM = "rgb(246, 241, 231)";
const DARK = "rgb(26, 24, 21)";

// The body paints a surface-to-canvas gradient, so its colour lives in background-image.
const bodyBackground = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundImage);

test.describe("theme runtime", () => {
  test("no saved choice follows a dark OS", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => bodyBackground(page)).toContain(DARK);
  });

  test("no saved choice follows a light OS", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect.poll(() => bodyBackground(page)).toContain(CREAM);
  });

  test("system choice follows an OS change without reload", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("a stored dark choice is set before hydration", async ({ page }) => {
    await page.addInitScript(() => {
      const seen: Record<string, string | undefined> = {};
      Object.assign(window, { __themeSeen: seen });
      window.localStorage.setItem("locus.theme.v1", "dark");
      // The init script runs before <html> exists, so watch the whole document.
      const observer = new MutationObserver(() => {
        if (document.body) {
          seen.body = document.documentElement.dataset.theme;
          observer.disconnect();
        }
      });
      observer.observe(document, { childList: true, subtree: true });
      document.addEventListener("DOMContentLoaded", () => {
        seen.domContentLoaded = document.documentElement.dataset.theme;
      });
    });
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    const seen = await page.evaluate(() => (window as unknown as { __themeSeen: Record<string, string> }).__themeSeen);
    expect(seen).toEqual({ body: "dark", domContentLoaded: "dark" });
  });
});
