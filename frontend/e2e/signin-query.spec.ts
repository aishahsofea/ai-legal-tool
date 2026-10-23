import { expect, test } from "@playwright/test";

const QUERY = "Is a verbal tenancy agreement valid?";

test.describe("signed out", () => {
  test("/workspace?q= forwards q to /login", async ({ page }) => {
    await page.goto("/workspace?q=" + encodeURIComponent(QUERY));
    await page.waitForURL(/\/login/);
    expect(new URL(page.url()).searchParams.get("q")).toBe(QUERY);
  });

  test("bare /workspace goes to bare /login", async ({ page }) => {
    await page.goto("/workspace");
    await page.waitForURL(/\/login/);
    expect(new URL(page.url()).search).toBe("");
  });
});
