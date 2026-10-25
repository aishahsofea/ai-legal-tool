import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

const LISTED = [
  { id: "t1", title: "Thread one title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
  { id: "t2", title: "Thread two title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const QUESTION = "Question from thread one";
const WELCOME = "Ask about statutory text, amendments, and Acts.";

// Registered after signIn, so these routes win over its stub.
async function stubThreads(page: Page, deleteStatus = 204) {
  const deleted = new Set<string>();
  const deletes: string[] = [];
  await page.route("**/threads", (route) =>
    route.fulfill({ json: LISTED.filter((t) => !deleted.has(t.id)) }),
  );
  await page.route("**/threads/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    if (route.request().method() === "DELETE") {
      deletes.push(id);
      if (deleteStatus === 204) deleted.add(id);
      return route.fulfill({ status: deleteStatus, body: deleteStatus === 204 ? "" : "boom" });
    }
    return route.fulfill({
      json: {
        ...LISTED.find((t) => t.id === id)!,
        messages: [
          { role: "user", content: QUESTION },
          { role: "assistant", content: `Answer for ${id}` },
        ],
      },
    });
  });
  return { deletes };
}

async function open(page: Page, deleteStatus?: number) {
  await signIn(page);
  const stub = await stubThreads(page, deleteStatus);
  await page.goto("/workspace");
  return stub;
}

const row = (page: Page, title: string) => page.getByRole("button", { name: new RegExp(`^${title}`) });
const deleteButton = (page: Page, title: string) =>
  page.getByRole("button", { name: `Delete thread ${title}` });

test("deleting the open thread removes the row and shows the empty workspace", async ({ page }) => {
  const { deletes } = await open(page);
  await row(page, LISTED[0].title).click();
  await expect(page.getByText(QUESTION)).toBeVisible();

  await deleteButton(page, LISTED[0].title).click();
  await page.getByRole("button", { name: "Yes" }).click();

  await expect(deleteButton(page, LISTED[0].title)).toBeHidden();
  await expect(page.getByText(LISTED[0].title)).toBeHidden();
  await expect(page.getByText(WELCOME)).toBeVisible();
  await expect(page.getByText(QUESTION)).toBeHidden();
  expect(deletes).toEqual(["t1"]);
  await expect(page.getByText(LISTED[1].title)).toBeVisible();
});

test("a deleted thread stays gone after reload", async ({ page }) => {
  await open(page);
  await deleteButton(page, LISTED[0].title).click();
  await page.getByRole("button", { name: "Yes" }).click();
  await expect(page.getByText(LISTED[0].title)).toBeHidden();

  await page.reload();
  await expect(page.getByText(LISTED[1].title)).toBeVisible();
  await expect(page.getByText(LISTED[0].title)).toBeHidden();
});

test("on desktop the delete button is hidden until the row is hovered", async ({ page }) => {
  await open(page);
  const button = deleteButton(page, LISTED[0].title);
  await expect(button).toHaveCSS("opacity", "0");

  await row(page, LISTED[0].title).hover();
  await expect(button).toHaveCSS("opacity", "1");
});

test("on mobile the delete button is visible without hover", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  await expect(deleteButton(page, LISTED[0].title)).toHaveCSS("opacity", "1");
});

test("a failed delete keeps the row and shows the error", async ({ page }) => {
  const { deletes } = await open(page, 500);
  await deleteButton(page, LISTED[0].title).click();
  await page.getByRole("button", { name: "Yes" }).click();

  await expect(page.getByRole("alert").filter({ hasText: "Could not delete that thread." })).toBeVisible();
  await expect(row(page, LISTED[0].title)).toBeVisible();
  expect(deletes).toEqual(["t1"]);
});
