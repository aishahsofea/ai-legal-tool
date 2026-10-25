import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

const THREAD = {
  id: "t1",
  title: "Gig worker thread",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

test.beforeEach(async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "share", { value: undefined, configurable: true });
  });
  await signIn(page);
  await page.route("**/threads", (route) => route.fulfill({ json: [THREAD] }));
  await page.route("**/threads/*", (route) =>
    route.fulfill({
      json: {
        ...THREAD,
        messages: [
          { role: "user", content: "Is a rider an employee?" },
          { role: "assistant", content: "Answer about riders." },
        ],
      },
    }),
  );
  await page.goto("/workspace");
  await page.getByRole("button", { name: /^Gig worker thread/ }).click();
});

async function expectCopiedLabel(page: import("@playwright/test").Page, name: string) {
  const button = page.getByRole("button", { name });
  await button.click();
  const label = button.getByText("Copied");
  await expect(label).toBeVisible();
  const box = (await label.boundingBox())!;
  expect(box.width).toBeGreaterThan(0);
  expect(box.height).toBeGreaterThan(0);
}

test("Share thread shows Copied and copies the thread", async ({ page }) => {
  await expectCopiedLabel(page, "Share thread");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(THREAD.title);
});

test("Share response shows Copied and copies the response", async ({ page }) => {
  await expectCopiedLabel(page, "Share response");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("Answer about riders.");
});
