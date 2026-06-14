import { describe, it, expect, vi } from "vitest";
import { render, act } from "@testing-library/react";

import { PostScanExecutionPanel } from "../PostScanExecutionPanel";
import type { ScanStep, ScanAccountRow, ScanOrderRow } from "@/hooks/useScanAutoTradeProgressWS";
import type { AutoTradeResult } from "@/api/client";

function defaults() {
  return {
    steps: [] as ScanStep[],
    accounts: [] as ScanAccountRow[],
    orders: [] as ScanOrderRow[],
    pct: null,
    connected: false,
    terminal: false,
    done: false,
    cooloffUntil: null,
    results: undefined as AutoTradeResult[] | undefined,
    summaries: undefined,
  };
}

describe("PostScanExecutionPanel", () => {
  it("live phase: shows stepper + live rows, hides persisted grid", () => {
    const { container, queryByText } = render(
      <PostScanExecutionPanel
        {...defaults()}
        steps={[{ stage: "execute_batch", status: "active", pct: null }]}
        accounts={[{ acctOrdinal: 1, status: "active", tradesExecuted: 1, tradesFailed: 0, tradesSkipped: 0 }]}
        orders={[{ seq: 1, acctOrdinal: 1, symbol: "BTCUSDT", side: "buy", status: "done" }]}
        connected={true}
        results={[{ symbol: "BTCUSDT", side: "buy", status: "success", account_id: "a" }]}
      />,
    );
    expect(container.textContent).toContain("acct#1");
    expect(queryByText("Executed")).toBeNull(); // persisted grid hidden while live
    expect(queryByText("Live")).not.toBeNull();
  });

  it("finished: shows persisted Executed/Failed + Done badge, no stepper", () => {
    const { container, queryByText } = render(
      <PostScanExecutionPanel
        {...defaults()}
        done={true}
        results={[
          { symbol: "BTCUSDT", side: "buy", status: "success", account_id: "a" },
          { symbol: "ETHUSDT", side: "sell", status: "failed", account_id: "b" },
        ]}
      />,
    );
    expect(queryByText("Executed")).not.toBeNull();
    expect(queryByText("Done")).not.toBeNull();
    // No "pending" stepper rows on a finished scan.
    expect(container.textContent).not.toContain("pending");
  });

  it("cold-load with persisted results + no live: NO grey stepper", () => {
    // The F8 regression: connected but not done, poll already returned results
    // before summaries — must NOT show an all-pending stepper over the results.
    const { container } = render(
      <PostScanExecutionPanel
        {...defaults()}
        connected={true}
        done={false}
        terminal={false}
        results={[{ symbol: "BTCUSDT", side: "buy", status: "success", account_id: "a" }]}
      />,
    );
    expect(container.textContent).not.toContain("pending");
    expect(container.textContent).toContain("Executed");
  });

  it("finished with zero trades: shows 'No trades placed'", () => {
    const { queryByText } = render(
      <PostScanExecutionPanel {...defaults()} done={true} results={[]} summaries={[]} />,
    );
    expect(queryByText(/No trades placed/)).not.toBeNull();
  });

  it("does not render the live order feed and persisted grid together", () => {
    const { queryByText, container } = render(
      <PostScanExecutionPanel
        {...defaults()}
        terminal={true}
        orders={[{ seq: 1, acctOrdinal: 1, symbol: "ZZZ", side: "buy", status: "done" }]}
        results={[{ symbol: "BTCUSDT", side: "buy", status: "success", account_id: "a" }]}
      />,
    );
    // Terminal -> persisted grid shows, live feed (ZZZ) does not.
    expect(queryByText("Executed")).not.toBeNull();
    expect(container.textContent).not.toContain("ZZZ");
  });

  it("cooloff: shows the rate-limit pause banner", () => {
    const { queryByText } = render(
      <PostScanExecutionPanel {...defaults()} cooloffUntil={Date.now() / 1000 + 120} />,
    );
    expect(queryByText(/rate-limit cooloff/)).not.toBeNull();
  });

  it("cooloff banner disappears after the cooloff expires", () => {
    vi.useFakeTimers();
    try {
      const start = Date.now();
      const { queryByText } = render(
        <PostScanExecutionPanel {...defaults()} cooloffUntil={start / 1000 + 2} />,
      );
      expect(queryByText(/rate-limit cooloff/)).not.toBeNull();
      // Advance past the cooloff deadline; the interval self-stops with a final tick.
      act(() => {
        vi.advanceTimersByTime(4000);
      });
      expect(queryByText(/rate-limit cooloff/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
