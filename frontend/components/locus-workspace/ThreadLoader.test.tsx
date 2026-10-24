import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ThreadLoader } from "./ThreadLoader";

it("renders a status with the opening copy", () => {
  render(<ThreadLoader />);
  expect(screen.getByRole("status")).toHaveTextContent("Opening thread…");
});
