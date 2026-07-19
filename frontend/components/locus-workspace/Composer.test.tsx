import { type FormEvent, useState } from "react";
import { render, screen } from "@testing-library/react";
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
