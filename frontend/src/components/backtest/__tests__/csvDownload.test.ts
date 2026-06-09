import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadCsv } from "../csvDownload";

describe("downloadCsv", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickCount = 0;

  beforeEach(() => {
    clickCount = 0;
    createObjectURL = vi.fn(() => "blob:mock-url");
    revokeObjectURL = vi.fn();
    // jsdom/happy-dom may not implement these; stub them.
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });
    // Intercept the anchor click so jsdom doesn't try to navigate.
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { clickCount += 1; });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a Blob URL, triggers a download with the given filename, and revokes the URL", () => {
    downloadCsv("trades.csv", "symbol,pnl\nBTCUSDT,12.3\n");

    // A Blob was created and turned into an object URL.
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blobArg = createObjectURL.mock.calls[0][0] as Blob;
    expect(blobArg).toBeInstanceOf(Blob);
    expect(blobArg.type).toContain("text/csv");

    // The anchor was clicked to start the download.
    expect(clickCount).toBe(1);

    // The object URL was revoked afterward (no leak).
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

    // The transient anchor was cleaned up (not left in the DOM).
    expect(document.querySelector("a[download]")).toBeNull();
  });
});
