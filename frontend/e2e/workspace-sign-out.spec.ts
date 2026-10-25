import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

const headerSignOut = (page: import("@playwright/test").Page) =>
  page.getByRole("group", { name: "Thread actions" }).getByRole("button", { name: "Sign out" });

test("Sign out is reachable at 375px", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page);
  await page.goto("/workspace");

  const button = headerSignOut(page);
  await expect(button).toBeVisible();
  const box = (await button.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(375);

  await button.click();
  await page.waitForURL(/\/login/);
});

test("Sign out is reachable with the sidebar collapsed", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page);
  await page.goto("/workspace");

  await page.getByRole("button", { name: "Hide thread list" }).click();
  await expect(headerSignOut(page)).toBeVisible();
  await headerSignOut(page).click();
  await page.waitForURL(/\/login/);
});
