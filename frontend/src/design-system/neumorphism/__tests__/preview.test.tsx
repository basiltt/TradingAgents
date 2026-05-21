import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { neumorphismComponentChecklist } from "../registry";
import { TradingAgentsNeumorphismPreview } from "../preview/TradingAgentsNeumorphismPreview";

describe("TradingAgentsNeumorphismPreview", () => {
  it("renders the standalone preview surface and every audited component specimen", () => {
    render(<TradingAgentsNeumorphismPreview />);

    expect(screen.getByText("TradingAgents design system review surface")).toBeInTheDocument();

    for (const names of Object.values(neumorphismComponentChecklist)) {
      for (const name of names) {
        expect(screen.getByRole("heading", { name })).toBeInTheDocument();
      }
    }
  }, 15000);
});
