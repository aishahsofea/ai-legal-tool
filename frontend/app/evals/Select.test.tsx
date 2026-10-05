import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Select } from "./Select";

const OPTIONS = [
  { value: "", label: "Choose…" },
  { value: "bm", label: "bm" },
  { value: "en", label: "en" },
];

function Harness({ onChange = () => {} }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState("");
  return <Select aria-label="Language" value={value} options={OPTIONS} onChange={(next) => { setValue(next); onChange(next); }} />;
}

beforeEach(() => {
  // jsdom does not implement scrollIntoView.
  Element.prototype.scrollIntoView = vi.fn();
});

describe("Select", () => {
  it("shows the selected label and keeps the list closed", () => {
    render(<Harness />);
    expect(screen.getByRole("combobox", { name: "Language" })).toHaveTextContent("Choose…");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("opens on click and selects an option by click", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "bm" }));
    expect(onChange).toHaveBeenCalledWith("bm");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveTextContent("bm");
  });

  it("moves with arrow keys and picks with Enter", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("combobox").focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("en");
  });

  it("clamps at the ends and supports Home and End", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("combobox").focus();
    await userEvent.keyboard("{ArrowDown}{End}{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("en");
    await userEvent.keyboard("{ArrowDown}{Home}{ArrowUp}{Enter}");
    expect(onChange).toHaveBeenLastCalledWith("");
  });

  it("closes on Escape without changing the value", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("combobox").focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("closes on outside click", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await userEvent.click(document.body);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("does not open when disabled", async () => {
    render(<Select aria-label="Set" value="" options={OPTIONS} onChange={() => {}} disabled />);
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
