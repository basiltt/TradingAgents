import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AgentStatusTable } from "../AgentStatusTable";
import { MessagesPanel } from "../MessagesPanel";
import { ReportPanel } from "../ReportPanel";
import { StatsBar } from "../StatsBar";
import { ErrorBanner } from "../ErrorBanner";
import { ReconnectionIndicator } from "../ReconnectionIndicator";

describe("AgentStatusTable", () => {
  it("renders agent statuses", () => {
    render(
      <AgentStatusTable
        agents={{ "Bull Researcher": "in_progress", Trader: "completed" }}
      />,
    );
    expect(screen.getByText(/bull researcher/i)).toBeInTheDocument();
    expect(screen.getByText(/trader/i)).toBeInTheDocument();
  });

  it("renders empty state when no agents", () => {
    render(<AgentStatusTable agents={{}} />);
    expect(screen.getByText(/no agents/i)).toBeInTheDocument();
  });
});

describe("MessagesPanel", () => {
  it("renders messages", () => {
    render(
      <MessagesPanel
        messages={[
          { sender: "System", content: "Hello", seq: 1 },
          { sender: "Tool", content: "Done", seq: 2 },
        ]}
      />,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
  });

  it("shows empty state", () => {
    render(<MessagesPanel messages={[]} />);
    expect(screen.getByText(/no messages/i)).toBeInTheDocument();
  });
});

describe("ReportPanel", () => {
  it("renders report sections", () => {
    render(
      <ReportPanel
        reports={{ trader: "BUY SPY", research_bull: "Bullish outlook" }}
      />,
    );
    expect(screen.getByText(/buy spy/i)).toBeInTheDocument();
    expect(screen.getByText(/bullish outlook/i)).toBeInTheDocument();
  });

  it("shows empty state", () => {
    render(<ReportPanel reports={{}} />);
    expect(screen.getByText(/no report/i)).toBeInTheDocument();
  });
});

describe("StatsBar", () => {
  it("renders stats", () => {
    render(
      <StatsBar
        stats={{ tokens_in: 1000, tokens_out: 500, llm_calls: 5, tool_calls: 3 }}
      />,
    );
    expect(screen.getByText(/1,?000/)).toBeInTheDocument();
    expect(screen.getByText(/500/)).toBeInTheDocument();
  });

  it("shows placeholder when no stats", () => {
    render(<StatsBar stats={null} />);
    expect(screen.getByText(/waiting/i)).toBeInTheDocument();
  });
});

describe("ErrorBanner", () => {
  it("renders error message", () => {
    render(<ErrorBanner message="Something went wrong" />);
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });

  it("has assertive aria-live", () => {
    render(<ErrorBanner message="Error" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("ReconnectionIndicator", () => {
  it("shows reconnecting state", () => {
    render(<ReconnectionIndicator status="reconnecting" attempt={2} />);
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    expect(screen.getByText(/attempt 2/i)).toBeInTheDocument();
  });

  it("shows connected state", () => {
    render(<ReconnectionIndicator status="connected" attempt={0} />);
    expect(screen.getByText(/connected/i)).toBeInTheDocument();
  });

  it("has status role", () => {
    render(<ReconnectionIndicator status="connecting" attempt={0} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
