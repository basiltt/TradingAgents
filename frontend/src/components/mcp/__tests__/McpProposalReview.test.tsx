import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { McpProposalReview } from "../McpProposalReview";
import type { MCPProposal } from "../types";

function makeProposal(over: Partial<MCPProposal> = {}): MCPProposal {
  return {
    id: "p-123456789",
    status: "pending",
    target_schedule_id: "sch-abc",
    target_config_index: 0,
    config: {},
    diff: {
      before: { leverage: 5, take_profit_pct: 150 },
      fields: {
        leverage: { from: 5, to: 50 }, // high-risk
        take_profit_pct: { from: 150, to: 200 }, // not high-risk
      },
    },
    risk_verdict: { robustness: "robust", rationale: "agent says it's great" },
    ...over,
  };
}

describe("McpProposalReview", () => {
  it("disables approve until each high-risk field is acked AND typed-confirm matches", () => {
    const onApprove = vi.fn();
    render(
      <McpProposalReview
        proposal={makeProposal()}
        busy={false}
        onApprove={onApprove}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    const approve = screen.getByRole("button", { name: /approve & apply/i });
    expect(approve).toBeDisabled(); // nothing acked, nothing typed

    // ack the high-risk leverage field
    const ackBox = screen.getByRole("checkbox");
    fireEvent.click(ackBox);
    expect(approve).toBeDisabled(); // still need typed-confirm

    // type the confirm word
    const input = screen.getByPlaceholderText("APPLY");
    fireEvent.change(input, { target: { value: "APPLY" } });
    expect(approve).toBeEnabled();

    fireEvent.click(approve);
    expect(onApprove).toHaveBeenCalledWith("p-123456789");
  });

  it("flags only the high-risk field and shows the segregated agent rationale", () => {
    render(
      <McpProposalReview
        proposal={makeProposal()}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    // exactly one "High risk" flag (leverage), not take_profit_pct
    expect(screen.getAllByText(/high risk/i).length).toBeGreaterThanOrEqual(1);
    // the agent rationale is fenced as unverified
    expect(screen.getByText(/agent-generated · unverified/i)).toBeInTheDocument();
    expect(screen.getByText(/agent says it's great/i)).toBeInTheDocument();
  });

  it("a proposal with no high-risk fields needs no typed-confirm", () => {
    const onApprove = vi.fn();
    render(
      <McpProposalReview
        proposal={makeProposal({
          diff: { before: {}, fields: { take_profit_pct: { from: 150, to: 200 } } },
        })}
        busy={false}
        onApprove={onApprove}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    const approve = screen.getByRole("button", { name: /approve & apply/i });
    expect(approve).toBeEnabled(); // no high-risk → immediately approvable
  });

  it("an applied proposal shows revert, not approve", () => {
    render(
      <McpProposalReview
        proposal={makeProposal({ status: "applied" })}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onRevert={vi.fn()}
        onBack={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /approve & apply/i })).toBeNull();
    expect(screen.getByRole("button", { name: /revert to prior config/i })).toBeInTheDocument();
  });
});
