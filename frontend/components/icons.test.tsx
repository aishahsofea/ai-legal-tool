import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Check, Copy, PanelLeft, Share } from "@/components/icons";

describe("icons", () => {
  it.each([
    ["copy", Copy],
    ["check", Check],
    ["share", Share],
    ["panel-left", PanelLeft],
  ])("%s renders a hidden svg tagged data-icon", (name, Icon) => {
    const { container } = render(<Icon className="x" />);
    const svg = container.querySelector(`svg[data-icon="${name}"]`);
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.getAttribute("class")).toBe("x");
  });
});
