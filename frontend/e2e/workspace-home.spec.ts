import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

for (const [name, width, height] of [["phone", 375, 812], ["desktop", 1280, 800]] as const) {
  test(`Home link leaves the workspace for the landing page on ${name}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await signIn(page);
    await page.goto("/workspace");

    const link = page.getByRole("link", { name: "Home" });
    await expect(link).toBeVisible();
    const box = (await link.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(width);

    await link.click();
    await expect(page).toHaveURL(/\/$/);
  });
}

test("Home link stays visible with the sidebar collapsed", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page);
  await page.goto("/workspace");
  await page.getByRole("button", { name: "Hide thread list" }).click();
  await expect(page.getByRole("link", { name: "Home" })).toBeVisible();
});
