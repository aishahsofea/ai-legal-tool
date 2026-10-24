import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthCallback from "./page";

const replace = vi.fn();
const getSession = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/supabaseClient", () => ({
  getSupabase: () => ({ auth: { getSession } }),
}));

const KEY = "locus:pending-query";
const QUERY = "Is a verbal tenancy agreement valid?";

beforeEach(() => {
  replace.mockReset();
  sessionStorage.clear();
});

describe("AuthCallback", () => {
  it("restores the saved q on /workspace and clears it", async () => {
    getSession.mockResolvedValue({ data: { session: {} } });
    sessionStorage.setItem(KEY, QUERY);
    render(<AuthCallback />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/workspace?q=${encodeURIComponent(QUERY)}`));
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("returns to /login?q= when the exchange gave no session", async () => {
    getSession.mockResolvedValue({ data: { session: null } });
    sessionStorage.setItem(KEY, QUERY);
    render(<AuthCallback />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/login?q=${encodeURIComponent(QUERY)}`));
  });

  it("goes to bare /workspace with nothing saved", async () => {
    getSession.mockResolvedValue({ data: { session: {} } });
    render(<AuthCallback />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace"));
  });

  it.each(["//evil.com", "https://evil.com"])("keeps hostile value %s inside q", async (value) => {
    getSession.mockResolvedValue({ data: { session: {} } });
    sessionStorage.setItem(KEY, value);
    render(<AuthCallback />);

    await waitFor(() => expect(replace).toHaveBeenCalled());
    const target = replace.mock.calls[0][0] as string;
    expect(target.startsWith("/workspace?q=")).toBe(true);
    expect(new URL(target, "http://x").searchParams.get("q")).toBe(value);
  });
});
