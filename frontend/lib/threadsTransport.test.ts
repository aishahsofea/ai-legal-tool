import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "./httpError";
import { deleteThread, fetchThread, fetchThreads } from "./threadsTransport";

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

describe("deleteThread", () => {
  it("sends DELETE with the bearer token and encoded id", async () => {
    const fn = stubFetch(null, true, 204);
    await deleteThread("a/b");
    const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/threads\/a%2Fb$/);
    expect(init.method).toBe("DELETE");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });

  it("resolves on 204", async () => {
    stubFetch(null, true, 204);
    await expect(deleteThread("t1")).resolves.toBeUndefined();
  });

  it("resolves on 404 because the thread is already gone", async () => {
    stubFetch({}, false, 404);
    await expect(deleteThread("t1")).resolves.toBeUndefined();
  });

  it("rejects on 500", async () => {
    stubFetch({}, false, 500);
    await expect(deleteThread("t1")).rejects.toThrow("HTTP 500");
  });
});

describe("401 handling", () => {
  it.each([
    ["fetchThreads", () => fetchThreads()],
    ["fetchThread", () => fetchThread("t1")],
    ["deleteThread", () => deleteThread("t1")],
  ])("%s rejects with an HttpError carrying the status", async (_name, call) => {
    stubFetch({}, false, 401);
    const err = await call().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(HttpError);
    expect((err as HttpError).status).toBe(401);
    expect((err as HttpError).message).toBe("HTTP 401");
  });
});
