import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/api/client", () => ({
  accountsApi: {
    getCooloffStatus: vi.fn(),
    clearCooloff: vi.fn(),
  },
}));

import { accountsApi, type CooloffStatus } from "@/api/client";
import { CoolOffBadge } from "../CoolOffBadge";

const getStatus = accountsApi.getCooloffStatus as unknown as ReturnType<typeof vi.fn>;
const clearCooloff = accountsApi.clearCooloff as unknown as ReturnType<typeof vi.fn>;

function status(overrides: Partial<CooloffStatus> = {}): CooloffStatus {
  return {
    account_id: "acct-1",
    cooling: false,
    cooloff_until: null,
    cooloff_reason: null,
    consecutive_wins: 0,
    consecutive_losses: 0,
    cooloff_remaining_seconds: 0,
    ...overrides,
  };
}

function renderBadge(tiersEnabled = true, accountId = "acct-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CoolOffBadge accountId={accountId} tiersEnabled={tiersEnabled} />
    </QueryClientProvider>,
  );
}

describe("CoolOffBadge", () => {
  beforeEach(() => {
    getStatus.mockReset();
    clearCooloff.mockReset();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("renders nothing when the account is not cooling", async () => {
    getStatus.mockResolvedValue(status({ cooling: false }));
    const { container } = renderBadge();
    // give the query a tick to resolve
    await waitFor(() => expect(getStatus).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("still surfaces an actively-cooling account even when no tier is enabled in the draft", async () => {
    // An account can be cooling server-side while the user has toggled every tier
    // off in the UNSAVED draft. Polling is gated on accountId (not tiersEnabled), so
    // the live pause + Resume-now must remain visible rather than silently vanish.
    getStatus.mockResolvedValue(
      status({ cooling: true, cooloff_reason: "failure", cooloff_remaining_seconds: 600 }),
    );
    renderBadge(false);
    const badge = await screen.findByRole("status");
    expect(badge).toHaveTextContent(/Cooling off/);
    expect(getStatus).toHaveBeenCalled();
  });

  it("renders the cooling badge with reason and remaining time", async () => {
    // The badge counts down to the absolute cooloff_until; anchor it just over 1h 2m
    // out (+5s buffer) so sub-second test timing can't round the label down to 1h 1m.
    getStatus.mockResolvedValue(
      status({
        cooling: true,
        cooloff_reason: "failure",
        cooloff_remaining_seconds: 3725,
        cooloff_until: new Date(Date.now() + 3725_000).toISOString(),
      }),
    );
    renderBadge();
    const badge = await screen.findByRole("status");
    expect(badge).toHaveTextContent(/Cooling off/);
    expect(badge).toHaveTextContent(/after a loss/);
    expect(badge).toHaveTextContent(/1h 2m left/);
    expect(screen.getByRole("button", { name: /Resume now/i })).toBeInTheDocument();
  });

  it("renders nothing when the FIRST status fetch errors (cold fail-open)", async () => {
    // Cold error: no prior data → data is undefined → badge hidden (correct).
    getStatus.mockRejectedValue(new Error("network"));
    renderBadge();
    await waitFor(() => expect(getStatus).toHaveBeenCalled());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps an actively-cooling badge visible when a later poll errors (warm refetch failure)", async () => {
    // Warm error: a successful cooling:true fetch, then a transient refetch failure.
    // TanStack Query keeps the last-good data while flagging the query errored; the
    // badge must NOT gate on isError or it would hide an active pause + Resume-now.
    getStatus.mockResolvedValueOnce(
      status({
        cooling: true,
        cooloff_reason: "failure",
        cooloff_remaining_seconds: 600,
        cooloff_until: new Date(Date.now() + 600_000).toISOString(),
      }),
    );
    const client = new QueryClient({
      // retry:1 mirrors the app's global config so the refetch genuinely reaches error state.
      defaultOptions: { queries: { retry: 1 }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <CoolOffBadge accountId="acct-1" tiersEnabled />
      </QueryClientProvider>,
    );
    const badge = await screen.findByRole("status");
    expect(badge).toHaveTextContent(/Cooling off/);
    // Now make subsequent refetches fail, and force a refetch.
    getStatus.mockRejectedValue(new Error("blip"));
    await client.refetchQueries({ queryKey: ["account-cooloff", "acct-1"] });
    // The badge is still present — the cached cooling status keeps it alive.
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/Cooling off/);
  });

  it("Resume now calls clearCooloff after the user confirms", async () => {
    getStatus.mockResolvedValue(
      status({ cooling: true, cooloff_reason: "success", cooloff_remaining_seconds: 120 }),
    );
    clearCooloff.mockResolvedValue({ cleared: true, cooloff_until: null });
    const confirmSpy = vi.fn(() => true);
    vi.stubGlobal("confirm", confirmSpy);
    renderBadge();
    const btn = await screen.findByRole("button", { name: /Resume now/i });
    fireEvent.click(btn);
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(clearCooloff).toHaveBeenCalledWith("acct-1", false));
  });

  it("Resume now does nothing when the user cancels the confirm", async () => {
    getStatus.mockResolvedValue(
      status({ cooling: true, cooloff_reason: "success", cooloff_remaining_seconds: 120 }),
    );
    const confirmSpy = vi.fn(() => false);
    vi.stubGlobal("confirm", confirmSpy);
    renderBadge();
    const btn = await screen.findByRole("button", { name: /Resume now/i });
    fireEvent.click(btn);
    expect(confirmSpy).toHaveBeenCalled();
    expect(clearCooloff).not.toHaveBeenCalled();
  });

  it("ticks the client countdown down each second and invalidates once at zero", async () => {
    // Fake timers BEFORE render so the countdown's setInterval + Date.now() run on a
    // pinned clock; advanceTimersByTimeAsync also flushes the query's promise.
    vi.useFakeTimers();
    const t0 = new Date("2026-06-12T00:00:00.000Z").getTime();
    vi.setSystemTime(t0);
    // Production always sends an absolute cooloff_until; the badge counts down to it.
    getStatus.mockResolvedValue(
      status({
        cooling: true,
        cooloff_reason: "failure",
        cooloff_until: new Date(t0 + 3000).toISOString(),
        cooloff_remaining_seconds: 3,
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    try {
      render(
        <QueryClientProvider client={client}>
          <CoolOffBadge accountId="acct-1" tiersEnabled />
        </QueryClientProvider>,
      );
      // Flush the resolved query + mount the countdown.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const badge = screen.getByRole("status");
      expect(badge).toHaveTextContent(/3s left/);

      invalidateSpy.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(badge).toHaveTextContent(/2s left/);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(badge).toHaveTextContent(/1s left/);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(badge).toHaveTextContent(/0m left/);
      // The zero crossing invalidates the cool-off query exactly once.
      const cooloffInvalidations = invalidateSpy.mock.calls.filter(
        (c) => JSON.stringify(c[0]) === JSON.stringify({ queryKey: ["account-cooloff", "acct-1"] }),
      );
      expect(cooloffInvalidations).toHaveLength(1);

      // Advancing further must NOT keep invalidating (interval was stopped at zero).
      invalidateSpy.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
      const moreCooloffInvalidations = invalidateSpy.mock.calls.filter(
        (c) => JSON.stringify(c[0]) === JSON.stringify({ queryKey: ["account-cooloff", "acct-1"] }),
      );
      expect(moreCooloffInvalidations).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("re-arms and invalidates AGAIN when a fresh later deadline arrives after zero", async () => {
    // This exercises the zeroFiredRef RESET (remaining goes back >0), which the
    // single-countdown test cannot — making the once-only guard load-bearing.
    vi.useFakeTimers();
    const t0 = new Date("2026-06-12T00:00:00.000Z").getTime();
    vi.setSystemTime(t0);
    // First poll: 2s of cool-off remaining.
    getStatus.mockResolvedValue(
      status({
        cooling: true,
        cooloff_reason: "failure",
        cooloff_until: new Date(t0 + 2000).toISOString(),
        cooloff_remaining_seconds: 2,
      }),
    );
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");
    const cooloffCount = () =>
      invalidateSpy.mock.calls.filter(
        (c) => JSON.stringify(c[0]) === JSON.stringify({ queryKey: ["account-cooloff", "acct-1"] }),
      ).length;
    try {
      render(
        <QueryClientProvider client={client}>
          <CoolOffBadge accountId="acct-1" tiersEnabled />
        </QueryClientProvider>,
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      // Re-arm the server status to a NEW later deadline BEFORE the first one expires.
      getStatus.mockResolvedValue(
        status({
          cooling: true,
          cooloff_reason: "failure",
          cooloff_until: new Date(t0 + 5000).toISOString(),
          cooloff_remaining_seconds: 5,
        }),
      );
      invalidateSpy.mockClear();
      // Tick past the FIRST deadline → remaining hits 0 → invalidate #1 (and the
      // refetch picks up the new 5s deadline, so remaining climbs back above 0).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(cooloffCount()).toBeGreaterThanOrEqual(1);
      const afterFirstZero = cooloffCount();
      // Now tick past the SECOND (re-armed) deadline → remaining hits 0 again →
      // a NEW invalidate fires (proves zeroFiredRef reset when remaining went >0).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(cooloffCount()).toBeGreaterThan(afterFirstZero);
    } finally {
      vi.useRealTimers();
    }
  });
});
