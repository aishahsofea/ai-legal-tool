import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

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
    if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/os-dark-follows.png` });
  });

  test("no saved choice follows a light OS", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect.poll(() => bodyBackground(page)).toContain(CREAM);
    if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/os-light-follows.png` });
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

const choose = async (page: import("@playwright/test").Page, name: "Light" | "Dark" | "System") => {
  await page.getByRole("button", { name: "Theme" }).click();
  await page.getByRole("menuitemradio", { name }).click();
};

test.describe("theme toggle", () => {
  test("landing: Dark survives a reload", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await choose(page, "Dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => bodyBackground(page)).toContain(DARK);
    await page.getByRole("button", { name: "Theme" }).click();
    await expect(page.getByRole("menuitemradio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");
    if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/landing-dark-after-reload.png` });
  });

  test("workspace: Light survives a reload", async ({ page }) => {
    await signIn(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/workspace");
    await choose(page, "Light");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "Theme" }).click();
    await expect(page.getByRole("menuitemradio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
    if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/workspace-light-after-reload.png` });
  });

  test("System follows the OS", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await choose(page, "Dark");
    await choose(page, "System");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/system-follows-os.png` });
  });

  test.describe("at 375px", () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test("landing toggle is inside the viewport", async ({ page }) => {
      await page.goto("/");
      const box = await page.getByRole("button", { name: "Theme" }).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(375);
      if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/landing-toggle-375.png` });
    });
  });
});
