import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

const BANNER = "Your session has ended.";
const LOAD_ERROR = "Could not load your threads.";

const authKeys = (page: Page) =>
  page.evaluate(() => Object.keys(window.localStorage).filter((k) => /^sb-.*-auth-token$/.test(k)));

test("401 from /threads shows the banner, and Sign in leaves without looping", async ({ page }) => {
  await signIn(page);
  await page.route("**/threads", (route) => route.fulfill({ status: 401, body: "no" }));
  await page.goto("/workspace");

  await expect(page.getByRole("alert").filter({ hasText: BANNER })).toBeVisible();
  await expect(page.getByText(LOAD_ERROR)).toHaveCount(0);

  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/login/);
  await page.waitForTimeout(2000);
  expect(new URL(page.url()).pathname).toBe("/login");
  expect(await authKeys(page)).toEqual([]);
});

test("401 from the query keeps the question and carries it to /login", async ({ page }) => {
  const question = "What is a contract of service?";
  await signIn(page);
  await page.route("**/threads", (route) => route.fulfill({ json: [] }));
  await page.route("**/query", (route) => route.fulfill({ status: 401, body: "no" }));
  await page.goto("/workspace");

  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: "Send message" }).click();

  await expect(page.getByRole("alert").filter({ hasText: BANNER })).toBeVisible();
  await expect(page.getByText(question)).toBeVisible();
  await expect(page.getByText("HTTP 401")).toHaveCount(0);

  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/login/);
  expect(new URL(page.url()).searchParams.get("q")).toBe(question);
});

test("500 from /threads shows the load error, not the banner", async ({ page }) => {
  await signIn(page);
  await page.route("**/threads", (route) => route.fulfill({ status: 500, body: "boom" }));
  await page.goto("/workspace");

  await expect(page.getByText(LOAD_ERROR)).toBeVisible();
  await expect(page.getByText(BANNER)).toHaveCount(0);
});
