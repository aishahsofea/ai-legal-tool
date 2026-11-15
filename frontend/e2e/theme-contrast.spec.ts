import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

const BLANK_PDF = "%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R/Size 4>>\n%%EOF";

const LISTED = [
  { id: "t1", title: "Thread one title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" },
  { id: "t2", title: "Thread two title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
];

const MIN_RATIO = 3;

type Failure = { selector: string; text: string; ratio: number };

// Runs in the browser. Flattens translucent layers up to the first opaque background.
async function lowContrast(page: Page): Promise<Failure[]> {
  return page.evaluate((min) => {
    const ctx = document.createElement("canvas").getContext("2d", { willReadFrequently: true })!;
    const parse = (css: string): [number, number, number, number] => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = css;
      ctx.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
      return [r, g, b, a / 255];
    };
    const over = (top: number[], under: number[]) =>
      [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3]));
    const channel = (v: number) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const lum = (rgb: number[]) => 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);

    const backdrop = (el: Element): number[] => {
      const layers: [number, number, number, number][] = [];
      for (let node: Element | null = el; node; node = node.parentElement) {
        const layer = parse(getComputedStyle(node).backgroundColor);
        if (layer[3] > 0) layers.push(layer);
        if (layer[3] === 1) break;
      }
      let flat: number[] = [255, 255, 255];
      for (const layer of layers.reverse()) flat = over(layer, flat);
      return flat;
    };

    const label = (el: Element) => {
      const testId = el.closest("[data-testid]")?.getAttribute("data-testid");
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 3).join(".") : "";
      return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}${testId ? ` [in ${testId}]` : ""}`;
    };

    const failures: { selector: string; text: string; ratio: number }[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    for (let el = walker.nextNode() as Element | null; el; el = walker.nextNode() as Element | null) {
      if (["SCRIPT", "STYLE", "NOSCRIPT", "CANVAS", "SVG"].includes(el.tagName.toUpperCase())) continue;
      const text = [...el.childNodes]
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => n.textContent ?? "")
        .join("")
        .trim();
      if (!text) continue;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) continue;
      if (el.closest("[aria-hidden='true']")) continue;

      const bg = backdrop(el);
      const fg = parse(style.color);
      const fgFlat = over(fg, bg);
      const [hi, lo] = [lum(fgFlat), lum(bg)].sort((a, b) => b - a);
      const ratio = (hi + 0.05) / (lo + 0.05);
      if (ratio < min) failures.push({ selector: label(el), text: text.slice(0, 40), ratio: Math.round(ratio * 100) / 100 });
    }
    return failures;
  }, MIN_RATIO);
}

async function expectReadable(page: Page) {
  expect(await lowContrast(page)).toEqual([]);
}

async function stubThreads(page: Page) {
  await page.route("**/threads", (route) => route.fulfill({ json: LISTED }));
  await page.route("**/threads/*", (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop()!;
    return route.fulfill({
      json: {
        ...LISTED.find((t) => t.id === id)!,
        messages: [
          { role: "user", content: "A question" },
          { role: "assistant", content: `Answer for ${id}` },
        ],
      },
    });
  });
}

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => localStorage.setItem("locus.theme.v1", value), theme);
    });

    test("landing", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByText(/Saved example · produced/)).toBeVisible();
      await expectReadable(page);
    });

    test("sign-in", async ({ page }) => {
      await page.goto("/login");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expectReadable(page);
    });

    test("workspace home", async ({ page }) => {
      await signIn(page);
      await page.goto("/workspace");
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(page.getByText("Ask about statutory text, amendments, and Acts.")).toBeVisible();
      await expectReadable(page);
    });

    test("loaded thread with composer", async ({ page }) => {
      await signIn(page);
      await stubThreads(page);
      await page.goto("/workspace");
      await page.getByRole("button", { name: /^Thread one title/ }).click();
      await expect(page.getByText("A question")).toBeVisible();
      await page.getByRole("textbox").fill("Draft question typed into the composer");
      await expectReadable(page);
    });

    test("delete dialog", async ({ page }) => {
      await signIn(page);
      await stubThreads(page);
      await page.goto("/workspace");
      await page.getByRole("button", { name: "Delete thread Thread one title" }).click();
      await expect(page.getByRole("dialog", { name: "Delete thread?" })).toBeVisible();
      await expectReadable(page);
    });

    test("phone sidebar drawer", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 812 });
      await signIn(page);
      await stubThreads(page);
      await page.goto("/workspace");
      await page.getByRole("button", { name: "Show thread list" }).click();
      await expect(page.getByRole("button", { name: /^Thread two title/ })).toBeVisible();
      await expectReadable(page);
    });

    test("receipt panel", async ({ page }) => {
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
      await page.getByRole("button", { name: /Open Citation Receipt 8:/ }).click();
      await expect(page.getByTestId("receipt-highlight")).toHaveCount(1);
      await expectReadable(page);
    });

    test("reference graph", async ({ page }) => {
      const target = "act:265/section:60D";
      const source = "act:265/section:100/subsection:3";
      const node = (id: string, label: string) => ({
        provision_id: id, version_id: "v1", label, kind: "section", page_start: 60, page_end: 63,
      });
      await page.route("**/reference-graph/snapshots*", (route) => route.fulfill({
        json: { status: "available", comparison_enabled: false, snapshots: [] },
      }));
      await page.route("**/reference-graph/neighborhood*", (route) => route.fulfill({
        json: {
          status: "available",
          document_id: "act-265-reprint-2023-6fec2f07",
          focus_provision_id: target,
          nodes: [node(target, "Section 60D"), node(source, "Section 100(3)")],
          edges: [{
            edge_id: "edge:a",
            source_provision_id: source,
            target_provision_id: target,
            relationship: "explicit_reference",
            reference_kind: "section",
            evidence: { text: "section 60D", start_offset: 0, end_offset: 11, pages: [{ page_number: 100, rectangles: [] }] },
          }],
        },
      }));
      await page.goto("/reference-graph");
      await expect(page.getByRole("complementary", { name: "Selected reference evidence" })).toBeVisible();
      await expectReadable(page);
    });
  });
}
