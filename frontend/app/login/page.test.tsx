import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "./page";

const replace = vi.fn();
const signInWithOAuth = vi.fn();
let session: object | null = null;

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/useSession", () => ({ useSession: () => session }));
vi.mock("@/lib/supabaseClient", () => ({
  getSupabase: () => ({ auth: { signInWithOAuth } }),
}));

const QUERY = "Is a verbal tenancy agreement valid?";

beforeEach(() => {
  session = null;
  sessionStorage.clear();
  signInWithOAuth.mockResolvedValue({ error: null });
});

describe("Login", () => {
  it("saves q and keeps redirectTo free of it when signing in", async () => {
    window.history.replaceState(null, "", `/login?q=${encodeURIComponent(QUERY)}`);
    render(<Login />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));

    expect(sessionStorage.getItem("locus:pending-query")).toBe(QUERY);
    expect(signInWithOAuth).toHaveBeenCalledWith({
      provider: "github",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  });

  it("clears an earlier saved query when there is no q", () => {
    sessionStorage.setItem("locus:pending-query", "stale");
    window.history.replaceState(null, "", "/login");
    render(<Login />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with GitHub" }));

    expect(sessionStorage.getItem("locus:pending-query")).toBeNull();
  });

  it("forwards q to /workspace when already signed in", () => {
    session = {};
    window.history.replaceState(null, "", `/login?q=${encodeURIComponent(QUERY)}`);
    render(<Login />);

    expect(replace).toHaveBeenCalledWith(`/workspace?q=${encodeURIComponent(QUERY)}`);
  });

  it("goes to bare /workspace when signed in with no q", () => {
    session = {};
    window.history.replaceState(null, "", "/login");
    render(<Login />);

    expect(replace).toHaveBeenCalledWith("/workspace");
  });
});
