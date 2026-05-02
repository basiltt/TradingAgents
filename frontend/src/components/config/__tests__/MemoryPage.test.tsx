import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryPage } from "../MemoryPage";

describe("MemoryPage", () => {
  it("renders memory page heading", () => {
    render(<MemoryPage />);
    expect(screen.getByRole("heading", { name: /memory/i })).toBeInTheDocument();
  });

  it("shows placeholder text", () => {
    render(<MemoryPage />);
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });
});
