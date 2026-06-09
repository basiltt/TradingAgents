import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { logger, setErrorReporter, type ErrorReporter } from "../logger";

describe("logger", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    setErrorReporter(null);
  });

  it("prefixes warn output with the scope", () => {
    logger.warn("MyScope", "something happened");
    expect(warnSpy).toHaveBeenCalledWith("[MyScope] something happened", "");
  });

  it("prefixes error output with the scope and passes context", () => {
    logger.error("TradeActions", "close failed", { tradeId: "t1" });
    expect(errorSpy).toHaveBeenCalledWith("[TradeActions] close failed", { tradeId: "t1" });
  });

  it("forwards warn to a registered error reporter with level and context", () => {
    const reporter = vi.fn<ErrorReporter>();
    setErrorReporter(reporter);
    logger.warn("Net", "retrying", { attempt: 2 });
    expect(reporter).toHaveBeenCalledWith("warn", "[Net] retrying", { attempt: 2 });
  });

  it("forwards error to a registered error reporter", () => {
    const reporter = vi.fn<ErrorReporter>();
    setErrorReporter(reporter);
    logger.error("Boom", "kaboom");
    expect(reporter).toHaveBeenCalledWith("error", "[Boom] kaboom", undefined);
  });

  it("does NOT forward debug/info to the error reporter", () => {
    const reporter = vi.fn<ErrorReporter>();
    setErrorReporter(reporter);
    logger.debug("X", "d");
    logger.info("X", "i");
    expect(reporter).not.toHaveBeenCalled();
  });

  it("detaches the reporter when set to null", () => {
    const reporter = vi.fn<ErrorReporter>();
    setErrorReporter(reporter);
    setErrorReporter(null);
    logger.error("X", "e");
    expect(reporter).not.toHaveBeenCalled();
  });

  it("a throwing reporter does not prevent the console write", () => {
    // The console.error happens BEFORE the reporter call, so even a broken
    // reporter cannot suppress the local log. (The reporter throw propagates;
    // callers should register a non-throwing reporter — documented contract.)
    setErrorReporter(() => {
      throw new Error("reporter down");
    });
    expect(() => logger.error("X", "e")).toThrow("reporter down");
    expect(errorSpy).toHaveBeenCalled();
  });
});
