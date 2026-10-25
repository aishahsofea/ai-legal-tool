import { expect, test } from "@playwright/test";

test.describe("landing header at 375px", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("nav links are visible inside the viewport", async ({ page }) => {
    await page.goto("/");
    for (const name of ["Capabilities", "Method", "Sign in"]) {
      const box = await page.getByRole("link", { name, exact: true }).first().boundingBox();
      expect(box, name).not.toBeNull();
      expect(box!.width).toBeGreaterThan(0);
      expect(box!.height).toBeGreaterThan(0);
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(375);
    }
  });

  for (const [name, id] of [
    ["Capabilities", "capabilities"],
    ["Method", "faq"],
  ]) {
    test(`${name} scrolls to #${id}`, async ({ page }) => {
      await page.goto("/");
      await page.getByRole("link", { name, exact: true }).click();
      await expect
        .poll(() => page.evaluate((i) => document.getElementById(i)!.getBoundingClientRect().top, id))
        .toBeGreaterThanOrEqual(-2);
      const top = await page.evaluate((i) => document.getElementById(i)!.getBoundingClientRect().top, id);
      expect(top).toBeLessThanOrEqual(80);
    });
  }

  test("Sign in while signed out ends on /login", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Sign in", exact: true }).click();
    await page.waitForURL(/\/login/);
  });

  test("placeholder fits inside the input", async ({ page }) => {
    await page.goto("/");
    const fit = await page.getByLabel("Legal research question").evaluate((el) => {
      const input = el as HTMLInputElement;
      const style = getComputedStyle(input);
      const ctx = document.createElement("canvas").getContext("2d")!;
      ctx.font = style.font;
      const available = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return { text: ctx.measureText(input.placeholder).width, available };
    });
    expect(fit.text).toBeLessThanOrEqual(fit.available);
  });

  test("a chip while signed out ends on /login with its query", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Section 57 frustration" }).click();
    await page.waitForURL(/\/login\?q=/);
    expect(new URL(page.url()).searchParams.get("q")).toBe(
      "How does Section 57 of the Contracts Act 1950 address frustration?",
    );
  });

  test("no Request access, no PRIVATE BETA, no horizontal overflow", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Request access")).toHaveCount(0);
    await expect(page.getByText("PRIVATE BETA")).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    expect(overflow).toBe(true);
  });
});
