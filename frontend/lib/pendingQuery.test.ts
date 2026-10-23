import { beforeEach, describe, expect, it } from "vitest";
import { stashPendingQuery, takePendingQuery, withQuery } from "@/lib/pendingQuery";

describe("withQuery", () => {
  it("returns the bare path for an empty query", () => {
    expect(withQuery("/workspace", null)).toBe("/workspace");
    expect(withQuery("/login", "")).toBe("/login");
  });

  it("encodes a normal query", () => {
    expect(withQuery("/workspace", "Is a verbal tenancy valid?")).toBe(
      "/workspace?q=Is%20a%20verbal%20tenancy%20valid%3F",
    );
  });

  it.each(["//evil.com", "https://evil.com", "/\\evil.com"])(
    "keeps hostile value %s inside the q parameter",
    (hostile) => {
      const target = withQuery("/workspace", hostile);
      expect(target.startsWith("/workspace?q=")).toBe(true);
      expect(new URL(target, "http://x").searchParams.get("q")).toBe(hostile);
    },
  );
});

describe("pending query storage", () => {
  beforeEach(() => sessionStorage.clear());

  it("returns a stashed value once", () => {
    stashPendingQuery("hello");
    expect(takePendingQuery()).toBe("hello");
    expect(takePendingQuery()).toBeNull();
  });

  it("clears an earlier value when stashing null", () => {
    stashPendingQuery("hello");
    stashPendingQuery(null);
    expect(takePendingQuery()).toBeNull();
  });
});
