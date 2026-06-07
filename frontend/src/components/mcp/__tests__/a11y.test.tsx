import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { McpProposalReview } from "../McpProposalReview";
import { TokenMeter } from "../TokenMeter";
import type { MCPProposal } from "../types";

/**
 * Accessibility gate (NFR-013) for the /mcp components. Without pulling in a new
 * axe dependency, this asserts the concrete a11y guarantees the spec names:
 * interactive controls expose accessible roles/names, the progress meter has
 * proper ARIA, and high-risk gates are keyboard-reachable (native inputs/buttons).
 */

function proposal(): MCPProposal {
  return {
    id: "p-1",
    status: "pending",
    target_schedule_id: "sch",
    target_config_index: 0,
    config: {},
    diff: { before: { leverage: 5 }, fields: { leverage: { from: 5, to: 50 } } },
    risk_verdict: { robustness: "robust", rationale: "r" },
  };
}

describe("MCP a11y (NFR-013)", () => {
  it("TokenMeter exposes a labelled progressbar with min/max/now", () => {
    render(<TokenMeter selected={5000} total={20000} budget={16000} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "5000");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "16000");
  });

  it("proposal review controls have accessible names + are native (keyboard-reachable)", () => {
    render(
      <McpProposalReview
        proposal={proposal()}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    // buttons resolve by accessible name (so screen readers announce them)
    expect(screen.getByRole("button", { name: /approve & apply/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    // the high-risk ack is a native checkbox (focusable, space-toggle)
    const ack = screen.getByRole("checkbox");
    expect(ack.tagName).toBe("INPUT");
    expect(ack).toHaveAttribute("type", "checkbox");
    // the typed-confirm is a native text input with a placeholder cue
    expect(screen.getByPlaceholderText("APPLY").tagName).toBe("INPUT");
  });

  it("no positive tabindex traps (controls use natural tab order)", () => {
    const { container } = render(
      <McpProposalReview
        proposal={proposal()}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    const positiveTabindex = container.querySelectorAll('[tabindex]:not([tabindex="0"]):not([tabindex="-1"])');
    expect(positiveTabindex.length).toBe(0);
  });
});
