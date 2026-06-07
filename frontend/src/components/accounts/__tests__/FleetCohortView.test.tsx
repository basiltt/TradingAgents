import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FleetCohortView, computeConcentration } from "../FleetCohortView";
import type { TradingAccount } from "../../../api/client";

function acct(id: string, cohort?: "trend" | "mean_reversion"): TradingAccount {
  return {
    id,
    label: `acct-${id}`,
    account_type: "demo",
    api_key_masked: "x",
    is_active: true,
    include_in_analytics: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    strategy_cohort: cohort,
  };
}

describe("computeConcentration", () => {
  it("flags a cohort that exceeds 70% of the fleet (AC-014)", () => {
    const accounts = [acct("1"), acct("2"), acct("3"), acct("4", "mean_reversion")];
    const c = computeConcentration(accounts);
    expect(c.trend).toBe(3);
    expect(c.mean_reversion).toBe(1);
    expect(c.dominant).toBe("trend");
    expect(c.warn).toBe(true); // 75% > 70%
  });

  it("does not warn on a balanced fleet", () => {
    const accounts = [acct("1"), acct("2", "mean_reversion")];
    expect(computeConcentration(accounts).warn).toBe(false); // 50%
  });

  it("treats missing cohort as trend", () => {
    expect(computeConcentration([acct("1")]).trend).toBe(1);
  });

  it("handles an empty fleet without warning", () => {
    const c = computeConcentration([]);
    expect(c.warn).toBe(false);
    expect(c.dominant).toBeNull();
  });
});

describe("FleetCohortView", () => {
  it("renders the concentration warning when a cohort dominates", () => {
    const accounts = [acct("1"), acct("2"), acct("3"), acct("4", "mean_reversion")];
    render(<FleetCohortView accounts={accounts} onAssign={vi.fn()} />);
    expect(screen.getByTestId("concentration-warning")).toBeTruthy();
  });

  it("bulk-assigns the selected accounts to the chosen cohort (preview→confirm)", async () => {
    const onAssign = vi.fn().mockResolvedValue(undefined);
    const accounts = [acct("1"), acct("2", "mean_reversion")];
    render(<FleetCohortView accounts={accounts} onAssign={onAssign} />);

    // select account 1
    fireEvent.click(screen.getByLabelText("select acct-1"));
    expect(screen.getByTestId("selected-count").textContent).toMatch(/1 selected/);

    // choose a cohort + apply
    fireEvent.change(screen.getByLabelText("cohort to apply"), { target: { value: "mean_reversion" } });
    fireEvent.click(screen.getByTestId("apply-cohort"));

    await waitFor(() => expect(onAssign).toHaveBeenCalledWith(["1"], "mean_reversion"));
  });

  it("disables apply until a cohort and at least one account are chosen", () => {
    render(<FleetCohortView accounts={[acct("1")]} onAssign={vi.fn()} />);
    expect((screen.getByTestId("apply-cohort") as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the selection when every assignment fails (onAssign returns 0)", async () => {
    const onAssign = vi.fn().mockResolvedValue(0); // total failure
    render(<FleetCohortView accounts={[acct("1")]} onAssign={onAssign} />);
    fireEvent.click(screen.getByLabelText("select acct-1"));
    fireEvent.change(screen.getByLabelText("cohort to apply"), { target: { value: "trend" } });
    fireEvent.click(screen.getByTestId("apply-cohort"));
    await waitFor(() => expect(onAssign).toHaveBeenCalled());
    // selection preserved so the user can retry the same set
    await waitFor(() => expect(screen.getByTestId("selected-count").textContent).toMatch(/1 selected/));
  });

  it("clears the selection when at least one assignment succeeds", async () => {
    const onAssign = vi.fn().mockResolvedValue(1);
    render(<FleetCohortView accounts={[acct("1")]} onAssign={onAssign} />);
    fireEvent.click(screen.getByLabelText("select acct-1"));
    fireEvent.change(screen.getByLabelText("cohort to apply"), { target: { value: "trend" } });
    fireEvent.click(screen.getByTestId("apply-cohort"));
    await waitFor(() => expect(screen.getByTestId("selected-count").textContent).toMatch(/0 selected/));
  });
});
