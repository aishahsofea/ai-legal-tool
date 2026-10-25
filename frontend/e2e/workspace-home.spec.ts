import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test("the Locus logo leaves the workspace for the landing page on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page);
  await page.goto("/workspace");

  await expect(page.getByRole("link", { name: "Home", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Locus home" }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("the Locus logo in the thread drawer leaves the workspace on phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page);
  await page.goto("/workspace");

  await page.getByRole("button", { name: "Show thread list" }).click();
  const logo = page.getByRole("link", { name: "Locus home" });
  await expect(logo).toBeVisible();
  await logo.click();
  await expect(page).toHaveURL(/\/$/);
});
