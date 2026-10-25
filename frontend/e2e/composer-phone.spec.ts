import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

test.describe("composer", () => {
  test("phone: no Shift hint, Send stays inside the form", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await signIn(page);
    await page.goto("/workspace");

    const form = page.locator("form").filter({ has: page.getByLabel("Message") });
    await expect(form).toBeVisible();
    await expect(page.getByText("⇧⏎ NEWLINE")).toBeHidden();

    const formBox = await form.boundingBox();
    const sendBox = await page.getByRole("button", { name: "Send message" }).boundingBox();
    expect(formBox).not.toBeNull();
    expect(sendBox).not.toBeNull();
    expect(sendBox!.x + sendBox!.width).toBeLessThanOrEqual(formBox!.x + formBox!.width + 1);
    expect(sendBox!.x + sendBox!.width).toBeGreaterThanOrEqual(formBox!.x + formBox!.width - 1);
  });

  test("desktop: Shift hint visible, no Upload button", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await signIn(page);
    await page.goto("/workspace");

    await expect(page.getByText("⇧⏎ NEWLINE")).toBeVisible();
    await expect(page.getByRole("button", { name: "Upload" })).toHaveCount(0);
  });
});
