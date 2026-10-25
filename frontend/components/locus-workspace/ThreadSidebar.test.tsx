import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ThreadSidebar } from "./ThreadSidebar";
import type { ThreadSummary } from "./types";

function renderSidebar(listStatus: "loading" | "ready" | "failed", threads: ThreadSummary[] = []) {
  render(
    <ThreadSidebar
      threads={threads}
      listStatus={listStatus}
      onNewThread={vi.fn()}
      onSelectThread={vi.fn()}
      userName="Ada"
      onSignOut={vi.fn()}
    />,
  );
}

it("loading shows skeleton, not empty copy", () => {
  renderSidebar("loading");
  expect(screen.getByRole("status", { name: "Loading threads" })).toBeInTheDocument();
  expect(screen.queryByText("No threads yet")).not.toBeInTheDocument();
});

it("ready and empty shows empty copy", () => {
  renderSidebar("ready");
  expect(screen.getByText("No threads yet")).toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("failed and empty shows neither", () => {
  renderSidebar("failed");
  expect(screen.queryByText("No threads yet")).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("ready with threads shows rows", () => {
  renderSidebar("ready", [
    { id: "t1", title: "First question", meta: "1 msg", active: false },
    { id: "t2", title: "Second question", meta: "2 msgs", active: false },
  ]);
  expect(screen.getByText("First question")).toBeInTheDocument();
  expect(screen.getByText("Second question")).toBeInTheDocument();
});

function renderWithDelete(onDeleteThread = vi.fn(), pendingThreadId: string | null = null, onSelectThread = vi.fn()) {
  render(
    <ThreadSidebar
      threads={[
        { id: "t1", title: "First question", meta: "1 msg", active: false },
        { id: "t2", title: "Second question", meta: "2 msgs", active: false },
      ]}
      listStatus="ready"
      onNewThread={vi.fn()}
      onSelectThread={onSelectThread}
      onDeleteThread={onDeleteThread}
      pendingThreadId={pendingThreadId}
      userName="Ada"
      onSignOut={vi.fn()}
    />,
  );
  return { onDeleteThread, onSelectThread };
}

it("delete click shows Yes/No and does not delete yet", () => {
  const { onDeleteThread } = renderWithDelete();
  fireEvent.click(screen.getByRole("button", { name: "Delete thread First question" }));
  expect(screen.getByText("Delete?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Yes" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "No" })).toBeInTheDocument();
  expect(onDeleteThread).not.toHaveBeenCalled();
});

it("No restores the row without deleting", () => {
  const { onDeleteThread } = renderWithDelete();
  fireEvent.click(screen.getByRole("button", { name: "Delete thread First question" }));
  fireEvent.click(screen.getByRole("button", { name: "No" }));
  expect(screen.queryByText("Delete?")).not.toBeInTheDocument();
  expect(screen.getByText("First question")).toBeInTheDocument();
  expect(onDeleteThread).not.toHaveBeenCalled();
});

it("Yes deletes that thread id", () => {
  const { onDeleteThread } = renderWithDelete();
  fireEvent.click(screen.getByRole("button", { name: "Delete thread Second question" }));
  fireEvent.click(screen.getByRole("button", { name: "Yes" }));
  expect(onDeleteThread).toHaveBeenCalledTimes(1);
  expect(onDeleteThread).toHaveBeenCalledWith("t2");
});

it("pending row delete button is disabled", () => {
  renderWithDelete(vi.fn(), "t1");
  expect(screen.getByRole("button", { name: "Delete thread First question" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Delete thread Second question" })).toBeEnabled();
});

it("clicking the title still selects the thread", () => {
  const { onSelectThread } = renderWithDelete();
  fireEvent.click(screen.getByText("First question"));
  expect(onSelectThread).toHaveBeenCalledWith("t1");
});
