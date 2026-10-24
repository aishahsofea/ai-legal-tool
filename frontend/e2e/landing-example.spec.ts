import { expect, test } from "@playwright/test";

test("signed-out landing shows the saved answer and opens a receipt without /query", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));

  await page.goto("/");
  await expect(page.getByText(/Saved example · produced/)).toBeVisible();
  const open = page.getByRole("button", { name: /Open Citation Receipt/ }).first();
  await expect(open).toBeVisible();

  await open.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize()!;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);

  expect(requests.filter((url) => /\/query/.test(url))).toEqual([]);
  expect(new URL(page.url()).pathname).toBe("/");
});
