# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: frontend/e2e/landing-example.spec.ts >> signed-out landing shows the saved answer and opens a receipt without /query
- Location: frontend/e2e/landing-example.spec.ts:3:5

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/", waiting until "load"

```

# Test source

```ts
  1  | import { expect, test } from "@playwright/test";
  2  | 
  3  | test("signed-out landing shows the saved answer and opens a receipt without /query", async ({ page }) => {
  4  |   const requests: string[] = [];
  5  |   page.on("request", (request) => requests.push(request.url()));
  6  |   await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  7  |   await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));
  8  | 
> 9  |   await page.goto("/");
     |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  10 |   await expect(page.getByText(/Saved example · produced/)).toBeVisible();
  11 |   const open = page.getByRole("button", { name: /Open Citation Receipt/ }).first();
  12 |   await expect(open).toBeVisible();
  13 | 
  14 |   await open.click();
  15 |   const dialog = page.getByRole("dialog");
  16 |   await expect(dialog).toBeVisible();
  17 |   await expect(dialog).toHaveAttribute("aria-modal", "true");
  18 |   const box = await dialog.boundingBox();
  19 |   const viewport = page.viewportSize()!;
  20 |   expect(box!.x).toBeGreaterThanOrEqual(0);
  21 |   expect(box!.y).toBeGreaterThanOrEqual(0);
  22 |   expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  23 |   expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  24 | 
  25 |   expect(requests.filter((url) => /\/query/.test(url))).toEqual([]);
  26 |   expect(new URL(page.url()).pathname).toBe("/");
  27 | });
  28 | 
```