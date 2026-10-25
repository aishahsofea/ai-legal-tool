import { expect, test } from "@playwright/test";

const BLANK_PDF = "%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R/Size 4>>\n%%EOF";

test("signed-out landing shows the saved answer and opens a receipt without /query", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));

  await page.goto("/");
  await expect(page.getByText(/Saved example · produced/)).toBeVisible();
  const open = page.getByRole("button", { name: /Open Citation Receipt 8:/ });
  await expect(open).toBeVisible();

  await open.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(dialog.getByText(/No verified passage/)).toHaveCount(0);
  const box = (await dialog.boundingBox())!;
  const layer = (await page.getByTestId("receipt-layer").boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(layer.x);
  expect(box.y).toBeGreaterThanOrEqual(layer.y);
  expect(box.x + box.width).toBeLessThanOrEqual(layer.x + layer.width + 1);
  expect(box.y + box.height).toBeLessThanOrEqual(layer.y + layer.height + 1);

  expect(requests.filter((url) => /\/query/.test(url))).toEqual([]);
  expect(new URL(page.url()).pathname).toBe("/");
});

test("receipt without evidence names the unchecked fallback page", async ({ page }) => {
  await page.route("**/receipts/*/locate", (route) =>
    route.fulfill({ status: 200, json: {
        status: "not_found",
        fallback_page: 259,
        pages: [],
        document: {
          document_id: "act-574-en-sha256-89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0",
          act_number: "574",
          act_title: "PENAL CODE",
          language: "en",
          timeline_date: "2024-01-01",
          timeline_type: "consolidated",
          sha256: "89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0",
        },
      },
    }),
  );
  await page.route("**/receipts/*/pdf", (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: BLANK_PDF }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: /Open Citation Receipt 4:/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/Showing PDF page 259/)).toBeVisible();
  await expect(dialog.getByText(/not been checked/)).toBeVisible();
});

test("on desktop the receipt opens as a right-side panel and leaves the answer visible", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));

  await page.goto("/");
  await page.getByRole("button", { name: /Open Citation Receipt 8:/ }).click();
  const box = (await page.getByRole("dialog").boundingBox())!;
  const layer = (await page.getByTestId("receipt-layer").boundingBox())!;
  expect(box.width).toBeLessThan(1280 * 0.6);
  expect(box.x + box.width).toBeCloseTo(layer.x + layer.width, 0);
  expect(box.x).toBeGreaterThan(400);
});

test("the landing receipt stays in its section and is gone when scrolled past it", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));

  await page.goto("/");
  await page.getByRole("button", { name: /Open Citation Receipt 8:/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.evaluate(() => {
    const layer = document.querySelector("[data-testid=receipt-layer]")!;
    window.scrollTo(0, layer.getBoundingClientRect().top + window.scrollY + 200);
  });
  await expect.poll(async () => (await dialog.boundingBox())!.y).toBeCloseTo(0, 0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(dialog).not.toBeInViewport();
});

test("on a phone the receipt stays full width",async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 });
  await page.route("**/receipts/*/locate", (route) => route.fulfill({ status: 404, json: { detail: "stub" } }));
  await page.route("**/receipts/*/pdf", (route) => route.fulfill({ status: 404, body: "" }));

  await page.goto("/");
  await page.getByRole("button", { name: /Open Citation Receipt 8:/ }).click();
  const box = (await page.getByRole("dialog").boundingBox())!;
  const layer = (await page.getByTestId("receipt-layer").boundingBox())!;
  expect(box.x).toBeCloseTo(layer.x, 0);
  expect(box.width).toBeCloseTo(layer.width, 0);
});
