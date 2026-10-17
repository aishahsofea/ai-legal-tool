import { type FormEvent, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Composer } from "./Composer";

it("keeps the compact composer action accessible as its label changes responsively", async () => {
  const onSubmit = vi.fn((event: FormEvent) => event.preventDefault());

  function Harness() {
    const [input, setInput] = useState("");
    return (
      <Composer
        input={input}
        onInput={setInput}
        onSubmit={onSubmit}
        onStop={() => {}}
        isLoading={false}
      />
    );
  }

  render(<Harness />);
  const send = screen.getByRole("button", { name: "Send message" });
  expect(send).toBeDisabled();

  await userEvent.type(screen.getByPlaceholderText("Ask a follow-up, or paste a clause…"), "Section 60A");
  expect(send).toBeEnabled();
  await userEvent.click(send);

  expect(onSubmit).toHaveBeenCalledOnce();
});

const PLACEHOLDER = "Ask a follow-up, or paste a clause…";

function renderComposer(initial = "", isLoading = false) {
  const onSubmit = vi.fn((event: FormEvent) => event.preventDefault());

  function Harness() {
    const [input, setInput] = useState(initial);
    return <Composer input={input} onInput={setInput} onSubmit={onSubmit} onStop={() => {}} isLoading={isLoading} />;
  }

  render(<Harness />);
  return { onSubmit, field: screen.getByLabelText("Message") as HTMLTextAreaElement };
}

it("sends once on Enter", () => {
  const { onSubmit, field } = renderComposer("Section 60A");
  fireEvent.keyDown(field, { key: "Enter" });
  expect(onSubmit).toHaveBeenCalledOnce();
});

it("keeps a newline and does not send on Shift+Enter", async () => {
  const { onSubmit, field } = renderComposer();
  await userEvent.type(field, "line one{Shift>}{Enter}{/Shift}line two");
  expect(field.value).toBe("line one\nline two");
  expect(onSubmit).not.toHaveBeenCalled();
});

it("does not send whitespace-only input on Enter", () => {
  const { onSubmit, field } = renderComposer("   ");
  fireEvent.keyDown(field, { key: "Enter" });
  expect(onSubmit).not.toHaveBeenCalled();
});

it("does not send on Enter while an IME composition is active", () => {
  const { onSubmit, field } = renderComposer("にほん");
  fireEvent.keyDown(field, { key: "Enter", isComposing: true });
  expect(onSubmit).not.toHaveBeenCalled();
});

it("disables the field while loading", () => {
  const { field } = renderComposer("", true);
  expect(field).toBeDisabled();
  expect(field).toHaveAttribute("placeholder", PLACEHOLDER);
});
