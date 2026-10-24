import { expect, test, type Page, type Route } from "@playwright/test";
import { signIn } from "./auth";

const LISTED = [
  { id: "t1", title: "Thread one title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
  { id: "t2", title: "Thread two title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const QUESTIONS: Record<string, string> = {
  t1: "Question from thread one",
  t2: "Question from thread two",
};

function stored(id: string) {
  const item = LISTED.find((t) => t.id === id)!;
  return {
    ...item,
    messages: [
      { role: "user", content: QUESTIONS[id] },
      { role: "assistant", content: `Answer for ${id}` },
    ],
  };
}

const WELCOME = "Ask about statutory text, amendments, and Acts.";

// Registered after signIn, so these routes win over its stub.
async function holdThreads(page: Page) {
  const held: Record<string, Route> = {};
  const requests: string[] = [];
  const waiters: Record<string, () => void> = {};
  await page.route("**/threads", (route) => route.fulfill({ json: LISTED }));
  await page.route("**/threads/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    requests.push(id);
    held[id] = route;
    waiters[id]?.();
  });
  return {
    requests,
    async requested(id: string) {
      if (held[id]) return;
      await new Promise<void>((resolve) => (waiters[id] = resolve));
    },
    release: (id: string) => held[id].fulfill({ json: stored(id) }),
    fail: (id: string) => held[id].fulfill({ status: 500, body: "boom" }),
  };
}

async function open(page: Page) {
  await signIn(page);
  const threads = await holdThreads(page);
  await page.goto("/workspace");
  return threads;
}

const row = (page: Page, title: string) => page.getByRole("button", { name: title });

test("opening an unloaded thread shows its row, title and loader before the fetch returns", async ({ page }) => {
  const threads = await open(page);
  await row(page, LISTED[0].title).click();
  await threads.requested("t1");

  const accent = row(page, LISTED[0].title).locator("span").first();
  await expect(accent).not.toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(page.locator("main.workspace-main header")).toContainText(LISTED[0].title);
  await expect(page.getByText("Opening thread…")).toBeVisible();
  await expect(page.getByText(WELCOME)).toBeHidden();

  await threads.release("t1");
  await expect(page.getByText("Opening thread…")).toBeHidden();
  await expect(page.getByText(QUESTIONS.t1)).toBeVisible();
});

test("a failed fetch removes the loader and shows the error", async ({ page }) => {
  const threads = await open(page);
  await row(page, LISTED[0].title).click();
  await threads.requested("t1");
  await threads.fail("t1");

  await expect(page.getByText("Opening thread…")).toBeHidden();
  await expect(page.getByRole("alert").filter({ hasText: "Could not open that thread." })).toBeVisible();
});

test("clicking A then B only ever shows B", async ({ page }) => {
  const threads = await open(page);
  await row(page, LISTED[0].title).click();
  await threads.requested("t1");
  await row(page, LISTED[1].title).click();
  await threads.requested("t2");

  await threads.release("t1");
  await expect(page.getByText("Opening thread…")).toBeVisible();
  await expect(page.getByText(QUESTIONS.t1)).toBeHidden();

  await threads.release("t2");
  await expect(page.getByText(QUESTIONS.t2)).toBeVisible();
  await expect(page.getByText(QUESTIONS.t1)).toBeHidden();
});

test("an already-loaded thread switches with no loader", async ({ page }) => {
  const threads = await open(page);
  await row(page, LISTED[0].title).click();
  await threads.requested("t1");
  await threads.release("t1");
  await expect(page.getByText(QUESTIONS.t1)).toBeVisible();
  await row(page, LISTED[1].title).click();
  await threads.requested("t2");
  await threads.release("t2");
  await expect(page.getByText(QUESTIONS.t2)).toBeVisible();

  await row(page, LISTED[0].title).click();
  await expect(page.getByText(QUESTIONS.t1)).toBeVisible();
  await expect(page.getByText("Opening thread…")).toBeHidden();
  expect(threads.requests.filter((id) => id === "t1")).toHaveLength(1);
});

test.describe("thread list load", () => {
  async function holdList(page: Page) {
    await signIn(page);
    let release!: (items: unknown[]) => void;
    const body = new Promise<unknown[]>((resolve) => (release = resolve));
    await page.route("**/threads", async (route) => route.fulfill({ json: await body }));
    await page.goto("/workspace");
    return release;
  }

  test("empty list: skeleton first, then the empty copy", async ({ page }) => {
    const release = await holdList(page);
    await expect(page.getByRole("status", { name: "Loading threads" })).toBeVisible();
    await expect(page.getByText("No threads yet")).toBeHidden();

    release([]);
    await expect(page.getByText("No threads yet")).toBeVisible();
    await expect(page.getByRole("status", { name: "Loading threads" })).toBeHidden();
  });

  test("listed threads show their titles once loaded", async ({ page }) => {
    const release = await holdList(page);
    await expect(page.getByRole("status", { name: "Loading threads" })).toBeVisible();

    release(LISTED);
    await expect(page.getByText(LISTED[0].title)).toBeVisible();
    await expect(page.getByText(LISTED[1].title)).toBeVisible();
  });
});
