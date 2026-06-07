import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StrategyChip } from "../StrategyChip";

describe("StrategyChip", () => {
  it("renders the trend label and kind data attribute", () => {
    render(<StrategyChip kind="trend" />);
    const chip = screen.getByTestId("strategy-chip");
    expect(chip).toHaveAttribute("data-kind", "trend");
    expect(chip.textContent).toMatch(/trend/i);
  });

  it("renders the mean-reversion label", () => {
    render(<StrategyChip kind="mean_reversion" />);
    const chip = screen.getByTestId("strategy-chip");
    expect(chip).toHaveAttribute("data-kind", "mean_reversion");
    expect(chip.textContent).toMatch(/mean-rev/i);
  });

  it("shows direction when provided", () => {
    render(<StrategyChip kind="mean_reversion" direction="long" />);
    expect(screen.getByTestId("strategy-chip-direction").textContent).toMatch(/long/i);
  });

  it("omits direction sub-label when not provided", () => {
    render(<StrategyChip kind="trend" />);
    expect(screen.queryByTestId("strategy-chip-direction")).toBeNull();
  });

  it("falls back to trend styling for an unknown kind", () => {
    // @ts-expect-error intentional bad input
    render(<StrategyChip kind="bogus" />);
    expect(screen.getByTestId("strategy-chip").textContent).toMatch(/trend/i);
  });
});
