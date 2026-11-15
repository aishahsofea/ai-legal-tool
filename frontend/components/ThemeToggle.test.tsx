import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

const setChoice = vi.fn();
let current: "light" | "dark" | "system" | null = "system";

vi.mock("@/lib/useTheme", () => ({
  useTheme: () => [current, setChoice],
}));

beforeEach(() => {
  setChoice.mockClear();
  current = "system";
});

const button = () => screen.getByRole("button", { name: "Theme" });

describe("ThemeToggle", () => {
  it("is a closed menu button by default", () => {
    render(<ThemeToggle />);
    expect(button()).toHaveAttribute("aria-haspopup", "menu");
    expect(button()).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens a menu with three radio items and marks the current choice", async () => {
    current = "dark";
    render(<ThemeToggle />);
    await userEvent.click(button());
    expect(button()).toHaveAttribute("aria-expanded", "true");
    const items = screen.getAllByRole("menuitemradio");
    expect(items.map((i) => i.textContent)).toEqual(["Light", "Dark", "System"]);
    expect(items.map((i) => i.getAttribute("aria-checked"))).toEqual(["false", "true", "false"]);
  });

  it("checks nothing before mount", async () => {
    current = null;
    render(<ThemeToggle />);
    await userEvent.click(button());
    for (const item of screen.getAllByRole("menuitemradio")) {
      expect(item).toHaveAttribute("aria-checked", "false");
    }
  });

  it("selecting an item calls setChoice and closes the menu", async () => {
    const { rerender } = render(<ThemeToggle />);
    await userEvent.click(button());
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Light" }));
    expect(setChoice).toHaveBeenCalledWith("light");
    expect(screen.queryByRole("menu")).toBeNull();

    current = "light";
    rerender(<ThemeToggle />);
    await userEvent.click(button());
    expect(screen.getByRole("menuitemradio", { name: "Light" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "System" })).toHaveAttribute("aria-checked", "false");
  });

  it("Escape closes the menu and returns focus to the button", async () => {
    render(<ThemeToggle />);
    await userEvent.click(button());
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button()).toHaveFocus();
  });

  it("an outside click closes the menu", async () => {
    render(
      <div>
        <span>outside</span>
        <ThemeToggle />
      </div>,
    );
    await userEvent.click(button());
    await userEvent.click(screen.getByText("outside"));
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
