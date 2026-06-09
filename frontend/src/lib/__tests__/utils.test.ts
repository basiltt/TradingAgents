import { describe, it, expect } from "vitest";
import { cn } from "../utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes", () => {
    // `show`/`hide` are runtime values (not literals) so the linter does not
    // flag a constant truthiness expression; `cn` must drop the falsy branch.
    const hide = false;
    const show = true;
    expect(cn("base", hide && "hidden", show && "visible")).toBe("base visible");
  });

  it("merges tailwind conflicts correctly", () => {
    expect(cn("px-4", "px-2")).toBe("px-2");
  });

  it("handles undefined and null", () => {
    expect(cn("a", undefined, null, "b")).toBe("a b");
  });

  it("handles empty input", () => {
    expect(cn()).toBe("");
  });
});
