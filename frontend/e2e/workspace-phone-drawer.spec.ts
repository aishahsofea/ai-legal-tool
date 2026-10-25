import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

const LISTED = [
  { id: "t1", title: "Thread one title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
  { id: "t2", title: "Thread two title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const sidebar = (page: Page) => page.locator("#workspace-thread-sidebar");
const row = (page: Page, title: string) => page.getByRole("button", { name: new RegExp(`^${title}`) });

async function open(page: Page) {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page);
  await page.route("**/threads", (route) => route.fulfill({ json: LISTED }));
  await page.route("**/threads/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    return route.fulfill({
      json: {
        ...LISTED.find((t) => t.id === id)!,
        messages: [
          { role: "user", content: "A question" },
          { role: "assistant", content: `Answer for ${id}` },
        ],
      },
    });
  });
  await page.goto("/workspace");
}

test("thread list is a closed vertical drawer on a phone", async ({ page }) => {
  await open(page);
  const closed = await sidebar(page).boundingBox();
  expect(closed === null || closed.x + closed.width <= 0).toBe(true);

  await page.getByRole("button", { name: "Show thread list" }).click();
  await expect(row(page, LISTED[1].title)).toBeVisible();
  await expect.poll(async () => Math.abs((await sidebar(page).boundingBox())!.x)).toBeLessThan(2);
  const box = (await sidebar(page).boundingBox())!;
  expect(box.height).toBeGreaterThanOrEqual(812 * 0.9);
  expect(box.width).toBeLessThanOrEqual(375 * 0.85 + 1);

  const first = (await row(page, LISTED[0].title).boundingBox())!;
  const second = (await row(page, LISTED[1].title).boundingBox())!;
  expect(second.y).toBeGreaterThanOrEqual(first.y + first.height);
  expect(Math.abs(second.x - first.x)).toBeLessThan(2);
});

test("selecting a thread closes the drawer; Escape closes it too", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Show thread list" }).click();
  await row(page, LISTED[0].title).click();
  await expect(page.getByRole("button", { name: "Show thread list" })).toBeVisible();
  await expect.poll(async () => {
    const box = await sidebar(page).boundingBox();
    return box === null ? 0 : box.x + box.width;
  }).toBeLessThanOrEqual(0);

  await page.getByRole("button", { name: "Show thread list" }).click();
  await expect(page.getByRole("button", { name: "Hide thread list" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Show thread list" })).toBeVisible();
});

test("backdrop click and New thread close the drawer", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Show thread list" }).click();
  await page.getByTestId("sidebar-backdrop").click({ position: { x: 360, y: 400 } });
  await expect(page.getByRole("button", { name: "Show thread list" })).toBeVisible();

  await page.getByRole("button", { name: "Show thread list" }).click();
  await page.getByRole("button", { name: /New thread/ }).click();
  await expect(page.getByRole("button", { name: "Show thread list" })).toBeVisible();
});
