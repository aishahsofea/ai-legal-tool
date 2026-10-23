import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./auth";

const VIEWPORTS = [
  { name: "mobile portrait", width: 375, height: 667 },
  { name: "mobile landscape", width: 667, height: 375 },
  { name: "tablet", width: 800, height: 900 },
  { name: "desktop", width: 1440, height: 900 },
];

async function metrics(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector("main.workspace-main")!;
    const wrap = document.querySelector(".chamber-grid-app")!.parentElement!;
    const doc = document.scrollingElement!;
    const box = (selector: string) => {
      const r = document.querySelector(selector)!.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom };
    };
    return {
      innerH: window.innerHeight,
      docScrollH: doc.scrollHeight,
      docTop: doc.scrollTop,
      wrapScrollH: wrap.scrollHeight,
      wrapClientH: wrap.clientHeight,
      wrapTop: wrap.scrollTop,
      mainScrollH: main.scrollHeight,
      mainClientH: main.clientHeight,
      mainTop: main.scrollTop,
      header: box("main.workspace-main > :first-child"),
      composer: box("main.workspace-main > :last-child"),
    };
  });
}

async function expectContained(page: Page, label: string) {
  const m = await metrics(page);
  const at = `${label}: ${JSON.stringify(m)}`;
  expect(m.docScrollH, at).toBeLessThanOrEqual(m.innerH);
  expect(m.docTop, at).toBe(0);
  expect(m.wrapScrollH, at).toBeLessThanOrEqual(m.wrapClientH);
  expect(m.wrapTop, at).toBe(0);
  expect(m.mainScrollH, at).toBeLessThanOrEqual(m.mainClientH);
  expect(m.mainTop, at).toBe(0);
  expect(m.header.top, at).toBeGreaterThanOrEqual(0);
  expect(m.composer.bottom, at).toBeLessThanOrEqual(m.innerH);
}

for (const vp of VIEWPORTS) {
  test.describe(`${vp.name} ${vp.width}x${vp.height}`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, hasTouch: vp.width < 768 });

    test("page does not scroll past the chat window", async ({ page }) => {
      await signIn(page);
      await page.goto("/workspace");
      const textarea = page.locator("main.workspace-main textarea");
      await textarea.waitFor();
      await expectContained(page, "default");

      await textarea.click();
      await textarea.fill(Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n"));
      await expectContained(page, "composer at max height");

      const before = await metrics(page);
      await page.mouse.move(vp.width / 2, vp.height / 2);
      await page.mouse.wheel(0, 800);
      await page.mouse.wheel(0, -800);
      for (const key of ["PageDown", "Space", "ArrowDown", "End"]) {
        await page.locator("body").press(key);
      }
      await textarea.evaluate((el) => (el as HTMLElement).blur());
      for (const key of ["PageDown", "Space", "ArrowDown", "End"]) {
        await page.keyboard.press(key);
      }
      await expectContained(page, "after wheel and keyboard");

      const after = await metrics(page);
      expect(after.header, "header moved").toEqual(before.header);
      expect(after.composer, "composer moved").toEqual(before.composer);
    });

    test("focusing the textarea does not scroll the wrapper", async ({ page }) => {
      await signIn(page);
      await page.goto("/workspace");
      const textarea = page.locator("main.workspace-main textarea");
      await textarea.waitFor();
      await textarea.fill(Array.from({ length: 12 }, (_, i) => `line ${i}`).join("\n"));
      await textarea.focus();
      await expectContained(page, "focused");
    });
  });
}

test.describe("sidebar collapsed", () => {
  for (const vp of VIEWPORTS.filter((v) => v.width >= 768)) {
    test(`${vp.name} stays contained`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await signIn(page);
      await page.goto("/workspace");
      await page.locator("main.workspace-main textarea").waitFor();
      await page.locator("main.workspace-main header button").first().click();
      await expectContained(page, "sidebar collapsed");
    });
  }

  test("drag handle collapses, persists and expands", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await signIn(page);
    await page.goto("/workspace");
    await page.locator("main.workspace-main textarea").waitFor();
    const handle = page.locator("[role=separator][aria-controls=workspace-thread-sidebar]");
    const sidebar = page.locator("#workspace-thread-sidebar");
    const drag = async (dx: number) => {
      const box = (await handle.boundingBox())!;
      const x = box.x + box.width / 2;
      const y = box.y + box.height / 2;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + dx, y, { steps: 5 });
      await page.mouse.up();
    };
    await drag(-100);
    await expect(sidebar).toBeHidden();
    await page.reload();
    await expect(sidebar).toBeHidden();
    await drag(100);
    await expect(sidebar).toBeVisible();
  });
});
