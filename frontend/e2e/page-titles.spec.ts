import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test.describe("page titles", () => {
  test("landing", async ({ page }) => {
    await page.goto("/");
    expect(await page.title()).toBe("Locus");
  });

  test("login", async ({ page }) => {
    await page.goto("/login");
    expect(await page.title()).toBe("Sign in · Locus");
  });

  test("workspace", async ({ page }) => {
    await signIn(page);
    await page.goto("/workspace");
    await expect(page).toHaveTitle("Workspace · Locus");
  });

  test("reference graph", async ({ page }) => {
    await page.goto("/reference-graph");
    await expect(page).toHaveTitle("Reference graph · Locus");
  });
});
