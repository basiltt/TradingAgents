import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnBadge } from "../conn-badge";

describe("ConnBadge", () => {
  it("returns null for idle status", () => {
    const { container } = render(<ConnBadge status="idle" latency={null} error={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders Checking for checking status", () => {
    render(<ConnBadge status="checking" latency={null} error={null} />);
    expect(screen.getByText("Checking")).toBeDefined();
  });

  it("renders Connected with latency for ok status", () => {
    render(<ConnBadge status="ok" latency={42} error={null} />);
    expect(screen.getByText(/Connected/)).toBeDefined();
    expect(screen.getByText(/42ms/)).toBeDefined();
  });

  it("renders custom label for ok status", () => {
    render(<ConnBadge status="ok" latency={null} error={null} label="Online" />);
    expect(screen.getByText("Online")).toBeDefined();
  });

  it("renders error message for error status", () => {
    render(<ConnBadge status="error" latency={null} error="Timeout" />);
    expect(screen.getByText("Timeout")).toBeDefined();
  });

  it("renders Unreachable when error is null", () => {
    render(<ConnBadge status="error" latency={null} error={null} />);
    expect(screen.getByText("Unreachable")).toBeDefined();
  });
});
