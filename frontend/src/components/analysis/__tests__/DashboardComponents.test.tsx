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
    expect(screen.getAllByText(/bull researcher/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/trader/i).length).toBeGreaterThan(0);
  });

  it("renders empty state when no agents", () => {
    render(<AgentStatusTable agents={{}} />);
    expect(screen.getAllByText(/waiting for agents/i).length).toBeGreaterThan(0);
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
    expect(screen.getAllByText("Hello").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Done").length).toBeGreaterThan(0);
  });

  it("shows empty state", () => {
    render(<MessagesPanel messages={[]} />);
    expect(screen.getAllByText(/no messages yet/i).length).toBeGreaterThan(0);
  });
});

describe("ReportPanel", () => {
  it("renders report sections", () => {
    render(
      <ReportPanel
        reports={{ trader: "BUY SPY", research_bull: "Bullish outlook" }}
      />,
    );
    expect(screen.getAllByText(/buy spy/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/bullish outlook/i).length).toBeGreaterThan(0);
  });

  it("shows empty state", () => {
    render(<ReportPanel reports={{}} />);
    expect(screen.getByText(/report sections appear/i)).toBeInTheDocument();
  });
});

describe("StatsBar", () => {
  it("renders stats", () => {
    render(
      <StatsBar
        stats={{ tokens_in: 1000, tokens_out: 500, llm_calls: 5, tool_calls: 3 }}
      />,
    );
    expect(screen.getAllByText(/1\.0K/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/500/).length).toBeGreaterThan(0);
  });

  it("shows placeholder when no stats", () => {
    render(<StatsBar stats={null} />);
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
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
