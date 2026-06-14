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

  it("stepper stage keys match the backend orchestrator emit keys", () => {
    // Regression: the stepper labels each backend stage. Driving the real emit keys
    // (execute_batch/fill/post_scan_recheck/cleanup/summaries) must mark those steps
    // active/done — NOT leave them stuck pending under stale keys.
    const { container } = render(
      <PostScanExecutionPanel
        {...defaults()}
        connected={true}
        steps={[
          { stage: "execute_batch", status: "done", pct: 20 },
          { stage: "fill", status: "done", pct: 40 },
          { stage: "post_scan_recheck", status: "active", pct: 60 },
        ]}
        accounts={[{ acctOrdinal: 1, status: "active", tradesExecuted: 1, tradesFailed: 0, tradesSkipped: 0 }]}
      />,
    );
    // The stepper renders all five stage labels (the keys resolve, not all-pending).
    expect(container.textContent).toContain("Placing batch orders");
    expect(container.textContent).toContain("Filling remaining slots");
    expect(container.textContent).toContain("Re-checking accounts");
    expect(container.textContent).toContain("Cleaning up rules");
    expect(container.textContent).toContain("Finalizing summaries");
    // execute_batch + fill report done; recheck reports active — at least one "done".
    expect(container.textContent).toContain("done");
    expect(container.textContent).toContain("active");
  });

  it("micro-throttle (rate_wait) renders a distinct hint, not the ban cooloff", () => {
    const { container, queryByText } = render(
      <PostScanExecutionPanel
        {...defaults()}
        connected={true}
        steps={[{ stage: "execute_batch", status: "active", pct: 20 }]}
        accounts={[{
          acctOrdinal: 1, status: "active", tradesExecuted: 0, tradesFailed: 0,
          tradesSkipped: 0, substatus: "rate_wait",
        }]}
      />,
    );
    expect(container.textContent).toContain("rate limit");
    // It is NOT the confirmed-ban cooloff banner (no cooloffUntil set).
    expect(queryByText(/rate-limit cooloff/)).toBeNull();
  });

  it("live order feed shows a check for a 'placed' order (backend success status)", () => {
    // The backend emits per-symbol status="placed" for a successful order (NOT "done").
    // The feed must render a success check, not blank.
    const { container } = render(
      <PostScanExecutionPanel
        {...defaults()}
        connected={true}
        steps={[{ stage: "execute_batch", status: "active", pct: 20 }]}
        orders={[
          { seq: 2, acctOrdinal: 1, symbol: "BTCUSDT", side: "buy", status: "placed" },
          { seq: 1, acctOrdinal: 1, symbol: "ETHUSDT", side: "sell", status: "failed" },
        ]}
      />,
    );
    // Both the placed (BTC) and failed (ETH) rows render; the placed one is not blank.
    expect(container.textContent).toContain("BTCUSDT");
    expect(container.textContent).toContain("✓"); // placed -> success check
    expect(container.textContent).toContain("✗"); // failed -> cross
  });
});
