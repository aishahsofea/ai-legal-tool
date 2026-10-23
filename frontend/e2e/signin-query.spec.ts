import { expect, test } from "@playwright/test";
import { signIn } from "./auth";

const QUERY = "Is a verbal tenancy agreement valid?";

const PENDING_KEY = "locus:pending-query";

test.describe("auth callback", () => {
  test("restores the saved query into the composer", async ({ page }) => {
    await signIn(page);
    await page.addInitScript(([k, v]) => window.sessionStorage.setItem(k, v), [PENDING_KEY, QUERY]);
    await page.goto("/auth/callback");
    await page.waitForURL(/\/workspace/);
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(QUERY);
  });

  test("leaves the composer empty with nothing saved", async ({ page }) => {
    await signIn(page);
    await page.goto("/auth/callback");
    await page.waitForURL(/\/workspace/);
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
  });

  test("full chain: workspace?q= -> login -> GitHub click -> callback -> composer", async ({ page }) => {
    await page.route("**/auth/v1/authorize**", (route) => route.fulfill({ body: "" }));
    await page.goto("/workspace?q=" + encodeURIComponent(QUERY));
    await page.waitForURL(/\/login/);
    await page.getByRole("button", { name: "Continue with GitHub" }).click();
    await signIn(page);
    await page.goto("/auth/callback");
    await page.waitForURL(/\/workspace/);
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(QUERY);
  });
});

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
