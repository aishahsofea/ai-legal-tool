import { expect, test, type Page } from "@playwright/test";

// Re-drawing the same layout shifts anti-aliased edge pixels by a few levels; a moved node changes pixels by far more.
const MOVED_PIXEL_DELTA = 64;

async function movedPixels(page: Page, a: Buffer, b: Buffer) {
  return page.evaluate(async ([x, y, threshold]) => {
    const load = async (base64: string) => {
      const image = new Image();
      image.src = `data:image/png;base64,${base64}`;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d")!;
      context.drawImage(image, 0, 0);
      return context.getImageData(0, 0, image.width, image.height).data;
    };
    const [first, second] = await Promise.all([load(x), load(y)]);
    let moved = 0;
    for (let i = 0; i < first.length; i += 4) {
      const delta = Math.max(...[0, 1, 2, 3].map((k) => Math.abs(first[i + k] - second[i + k])));
      if (delta > Number(threshold)) moved++;
    }
    return moved;
  }, [a.toString("base64"), b.toString("base64"), String(MOVED_PIXEL_DELTA)] as const);
}

const documentId = "act-265-reprint-2023-6fec2f07";
const target = "act:265/section:60D";
const source = "act:265/section:100/subsection:3";

const mention = (id: string, page: number) => ({
  edge_id: id,
  source_provision_id: source,
  target_provision_id: target,
  relationship: "explicit_reference",
  reference_kind: "section",
  evidence: { text: "section 60D", start_offset: 0, end_offset: 11, pages: [{ page_number: page, rectangles: [] }] },
});
const node = (id: string, label: string) => ({
  provision_id: id, version_id: "v1", label, kind: "section", page_start: 60, page_end: 63,
});

test("graph re-colours on theme change without moving nodes or losing the evidence row", async ({ page }) => {
  await page.route("**/reference-graph/snapshots*", (route) => route.fulfill({
    json: { status: "available", comparison_enabled: false, snapshots: [] },
  }));
  await page.route("**/reference-graph/neighborhood*", (route) => route.fulfill({
    json: {
      status: "available",
      document_id: documentId,
      focus_provision_id: target,
      nodes: [node(target, "Section 60D"), node(source, "Section 100(3)")],
      edges: [mention("edge:a", 100), mention("edge:b", 101)],
    },
  }));

  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/reference-graph");
  const canvas = page.getByTestId("reference-graph-canvas");
  const row = page.getByRole("article").filter({ hasText: "section:100 · subsection:3 → section:60D" });
  await expect(row).toHaveCount(1);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const rowText = await row.innerText();
  const light = await canvas.screenshot({ animations: "disabled" });

  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect.poll(async () => movedPixels(page, light, await canvas.screenshot({ animations: "disabled" }))).toBeGreaterThan(0);

  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const relit = await canvas.screenshot({ animations: "disabled" });
  expect(await movedPixels(page, light, relit)).toBe(0);

  await expect(page.getByRole("complementary", { name: "Selected reference evidence" })).toBeVisible();
  await expect(row).toHaveCount(1);
  expect(await row.innerText()).toBe(rowText);
});
