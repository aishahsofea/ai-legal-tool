import { expect, test } from "@playwright/test";

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

test("repeated mentions of one pair show as one row with a count", async ({ page }) => {
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

  await page.goto("/reference-graph");
  await expect(page.getByRole("complementary", { name: "Selected reference evidence" })).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "section:100 · subsection:3 → section:60D" })).toHaveCount(1);
  await expect(page.getByText("2 mentions")).toBeVisible();
});

const stubGraph = async (page: import("@playwright/test").Page) => {
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
};

test("phone: canvas keeps its height and evidence sits below it", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await stubGraph(page);
  await page.goto("/reference-graph");
  const aside = page.getByRole("complementary", { name: "Selected reference evidence" });
  await expect(aside).toBeVisible();
  const canvas = await page.getByTestId("reference-graph-canvas").boundingBox();
  const evidence = await aside.boundingBox();
  expect(canvas!.height).toBeGreaterThanOrEqual(0.45 * 812);
  expect(evidence!.y).toBeGreaterThanOrEqual(canvas!.y + canvas!.height - 1);
});

test("header kicker names Employment Act only for the default document", async ({ page }) => {
  await stubGraph(page);
  await page.goto("/reference-graph");
  await expect(page.getByText("Employment Act 1955")).toHaveCount(1);
  await page.goto("/reference-graph?document_id=other");
  await expect(page.getByRole("heading", { name: "Statutory reference graph" })).toBeVisible();
  await expect(page.getByText("Employment Act 1955")).toHaveCount(0);
});
