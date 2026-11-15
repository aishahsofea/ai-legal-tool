import { expect, test } from "@playwright/test";

const BLANK_PDF = "%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R/Size 4>>\n%%EOF";

const channel = (value: number) => {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = ([r, g, b]: number[]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
const rgbOf = (css: string) => css.match(/[\d.]+/g)!.slice(0, 3).map(Number);

test("receipt PDF page stays white in dark mode and its highlight stays visible", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("locus.theme.v1", "dark"));
  await page.route("**/receipts/*/locate", (route) => {
    const documentId = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[2]);
    return route.fulfill({
      status: 200,
      json: {
        status: "matched",
        fallback_page: 1,
        pages: [{ page_number: 1, rectangles: [{ x: 0.2, y: 0.3, width: 0.5, height: 0.1 }] }],
        document: {
          document_id: documentId,
          act_number: "574",
          act_title: "PENAL CODE",
          language: "en",
          timeline_date: "2024-01-01",
          timeline_type: "consolidated",
          sha256: "89c0f2f6f13f20c0b085a0de404d3d056de92374c9f300704d42c50800a77fa0",
        },
      },
    });
  });
  await page.route("**/receipts/*/pdf", (route) =>
    route.fulfill({ status: 200, contentType: "application/pdf", body: BLANK_PDF }),
  );

  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /Open Citation Receipt 8:/ }).click();

  const pdfPage = page.getByTestId("receipt-pdf-page");
  await expect(pdfPage).toBeVisible();
  expect(await pdfPage.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");

  const highlight = page.getByTestId("receipt-highlight");
  await expect(highlight).toHaveCount(1);
  const box = (await highlight.boundingBox())!;
  expect(box.width).toBeGreaterThan(0);
  expect(box.height).toBeGreaterThan(0);

  const style = await highlight.evaluate((el) => {
    const computed = getComputedStyle(el);
    return { background: computed.backgroundColor, border: computed.borderTopColor };
  });
  expect(style.background).not.toMatch(/rgba\(0, 0, 0, 0\)|transparent/);

  // Alpha-flatten the border over white, as it is painted on the page.
  const [r, g, b] = rgbOf(style.border);
  const alpha = Number(style.border.match(/[\d.]+/g)![3] ?? 1);
  const flat = [r, g, b].map((v) => v * alpha + 255 * (1 - alpha));
  const ratio = 1.05 / (luminance(flat) + 0.05);
  expect(ratio).toBeGreaterThanOrEqual(3);
});
