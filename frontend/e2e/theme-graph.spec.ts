import { expect, test, type Locator, type Page } from "@playwright/test";

// Re-drawing the same layout shifts anti-aliased edge pixels by a few levels; a moved node changes pixels by far more.
const MOVED_PIXEL_DELTA = 64;

// Only Cytoscape's own canvas layers: the container's CSS background flips with the theme by itself and would hide a missing restyle.
async function graphLayers(canvas: Locator): Promise<Buffer> {
  const base64 = await canvas.evaluate((el) => {
    const layers = [...el.querySelectorAll("canvas")];
    const out = document.createElement("canvas");
    out.width = Math.max(...layers.map((l) => l.width));
    out.height = Math.max(...layers.map((l) => l.height));
    const context = out.getContext("2d")!;
    for (const layer of layers) context.drawImage(layer, 0, 0);
    return out.toDataURL("image/png").split(",")[1];
  });
  return Buffer.from(base64, "base64");
}

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
  // Under load the first layout is still animating; wait until two frames match.
  await expect.poll(() => canvas.evaluate((el) => [...el.querySelectorAll("canvas")].some((l) => l.width > 0))).toBe(true);
  await page.evaluate(() => document.fonts.ready);
  let light = await graphLayers(canvas);
  await expect.poll(async () => {
    await page.waitForTimeout(400);
    const next = await graphLayers(canvas);
    const settled = (await movedPixels(page, light, next)) === 0;
    light = next;
    return settled;
  }).toBe(true);

  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect.poll(async () => movedPixels(page, light, await graphLayers(canvas))).toBeGreaterThan(0);
  if (process.env.PIPELINE_EVIDENCE_DIR) await page.screenshot({ path: `${process.env.PIPELINE_EVIDENCE_DIR}/graph-dark.png` });

  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(async () => movedPixels(page, light, await graphLayers(canvas))).toBe(0);

  await expect(page.getByRole("complementary", { name: "Selected reference evidence" })).toBeVisible();
  await expect(row).toHaveCount(1);
  expect(await row.innerText()).toBe(rowText);
});
