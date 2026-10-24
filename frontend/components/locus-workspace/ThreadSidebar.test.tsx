import { render, screen } from "@testing-library/react";
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
