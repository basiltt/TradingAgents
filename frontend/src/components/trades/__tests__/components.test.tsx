import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PnLDisplay } from "../PnLDisplay";
import { TradeStatusBadge } from "../TradeStatusBadge";

describe("PnLDisplay", () => {
  it("shows -- for null", () => {
    render(<PnLDisplay value={null} />);
    expect(screen.getByText("--")).toBeDefined();
  });

  it("shows -- for NaN", () => {
    render(<PnLDisplay value={NaN} />);
    expect(screen.getByText("--")).toBeDefined();
  });

  it("shows green arrow for positive", () => {
    const { container } = render(<PnLDisplay value={100} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("green");
    expect(span?.textContent).toContain("↑");
  });

  it("shows red arrow for negative", () => {
    const { container } = render(<PnLDisplay value={-50} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("red");
    expect(span?.textContent).toContain("↓");
  });

  it("shows gray for zero", () => {
    const { container } = render(<PnLDisplay value={0} />);
    const span = container.querySelector("span");
    expect(span?.className).toContain("gray");
    expect(span?.textContent).not.toContain("↑");
    expect(span?.textContent).not.toContain("↓");
  });
});

describe("TradeStatusBadge", () => {
  it.each(["open", "pending", "closing", "closed", "failed", "cancelled"])("renders known status: %s", (status) => {
      const { container } = render(<TradeStatusBadge status={status} />);
      expect(container.textContent).toBeTruthy();
    });

  it("renders unknown status as Unknown", () => {
    render(<TradeStatusBadge status="weird" />);
    expect(screen.getByText("Unknown")).toBeDefined();
  });

  it("open badge has green class", () => {
    const { container } = render(<TradeStatusBadge status="open" />);
    expect(container.innerHTML).toContain("green");
  });

  it("failed badge has red class", () => {
    const { container } = render(<TradeStatusBadge status="failed" />);
    expect(container.innerHTML).toContain("red");
  });
});
