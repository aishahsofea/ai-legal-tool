import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchThread, fetchThreads } from "./threadsTransport";

vi.mock("@/lib/supabaseClient", () => ({
  authHeaders: async () => ({ Authorization: "Bearer test-token" }),
}));

function stubFetch(body: unknown, ok = true, status = 200) {
  const fn = vi.fn(async () => ({ ok, status, json: async () => body }) as unknown as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("threads transport", () => {
  it("lists threads with the bearer token", async () => {
    const fn = stubFetch([{ id: "t1", title: "Q", created_at: "a", updated_at: "b" }]);
    const threads = await fetchThreads();
    expect(threads.map((t) => t.id)).toEqual(["t1"]);
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/threads$/);
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("fetches one thread by encoded id", async () => {
    const fn = stubFetch({ id: "a/b", messages: [] });
    await fetchThread("a/b");
    expect((fn.mock.calls[0] as unknown as [string])[0]).toMatch(/\/threads\/a%2Fb$/);
  });

  it("throws on a non-ok response", async () => {
    stubFetch({}, false, 404);
    await expect(fetchThread("t1")).rejects.toThrow("HTTP 404");
  });
});
