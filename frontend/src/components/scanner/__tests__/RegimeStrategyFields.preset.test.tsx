import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RegimeStrategyFields } from "../RegimeStrategyFields";
import { RECOMMENDED_PRESET } from "../regimeStrategyPreset";
import type { AutoTradeConfig } from "@/api/client";

describe("RECOMMENDED_PRESET", () => {
  it("enables F1 with the proven blocked Asian-session hours", () => {
    expect(RECOMMENDED_PRESET.regime_filter_enabled).toBe(true);
    expect(RECOMMENDED_PRESET.session_filter_enabled).toBe(true);
    expect(RECOMMENDED_PRESET.session_blocked_hours_utc).toEqual([1, 6, 7, 8, 9, 10, 11, 12]);
  });

  it("keeps the negative-expectancy long side OFF", () => {
    expect(RECOMMENDED_PRESET.mr_long_enabled).toBe(false);
  });

  it("uses conservative F2 sizing", () => {
    expect(RECOMMENDED_PRESET.mr_capital_pct).toBeLessThanOrEqual(2);
    expect(RECOMMENDED_PRESET.mr_leverage).toBeLessThanOrEqual(5);
  });
});

describe("RegimeStrategyFields preset button", () => {
  it("applies the full recommended preset in one click (TASK-5.3)", () => {
    const onChange = vi.fn();
    const config = {} as AutoTradeConfig;
    render(<RegimeStrategyFields config={config} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("apply-recommended-preset"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const payload = onChange.mock.calls[0][0];
    expect(payload.regime_filter_enabled).toBe(true);
    expect(payload.mean_reversion_enabled).toBe(true);
    expect(payload.strategy_cohort).toBe("mean_reversion");
    expect(payload.mr_long_enabled).toBe(false);
  });
});
