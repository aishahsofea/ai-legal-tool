import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConversationHeader } from "./ConversationHeader";
import type { Message } from "./types";

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

describe("ConversationHeader share", () => {
  const messages = [
    { id: "1", role: "user", content: "What is s 3?" },
    { id: "2", role: "assistant", content: "Section 3 says X." },
  ] as Message[];

  afterEach(() => {
    Object.assign(navigator, { share: undefined });
  });

  it("has no Coming soon title or removed stubs", () => {
    const { container } = render(<ConversationHeader title="T" messages={messages} />);
    expect(container.querySelector('[title="Coming soon"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /highlights|memo|export/i })).toBeNull();
  });

  it("is disabled with no messages", () => {
    render(<ConversationHeader title="T" messages={[]} />);
    expect(screen.getByRole("button", { name: "Share thread" })).toBeDisabled();
  });

  it("copies thread markdown when navigator.share is missing", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { share: undefined, clipboard: { writeText } });
    render(<ConversationHeader title="My thread" messages={messages} />);
    fireEvent.click(screen.getByRole("button", { name: "Share thread" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("# My thread");
    expect(text).toContain("What is s 3?");
    expect(text).toContain("Section 3 says X.");
  });
});
