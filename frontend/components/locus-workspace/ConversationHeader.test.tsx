import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConversationHeader } from "./ConversationHeader";

describe("ConversationHeader sidebar toggle", () => {
  it("renders no toggle without onToggleSidebar", () => {
    render(<ConversationHeader title="T" />);
    expect(screen.queryByRole("button", { name: /thread list/i })).toBeNull();
  });

  it("labels and aria-expanded follow the collapsed state", () => {
    const { rerender } = render(<ConversationHeader title="T" sidebarCollapsed={false} onToggleSidebar={() => {}} />);
    let button = screen.getByRole("button", { name: "Hide thread list" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", "workspace-thread-sidebar");

    rerender(<ConversationHeader title="T" sidebarCollapsed onToggleSidebar={() => {}} />);
    button = screen.getByRole("button", { name: "Show thread list" });
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("fires onToggleSidebar on click and keyboard activation", async () => {
    const onToggle = vi.fn();
    render(<ConversationHeader title="T" onToggleSidebar={onToggle} />);
    const button = screen.getByRole("button", { name: "Hide thread list" });
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });
});
