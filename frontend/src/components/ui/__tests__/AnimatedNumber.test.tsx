import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnimatedNumber } from "../animated-number";

describe("AnimatedNumber", () => {
  it("renders non-numeric string as-is", () => {
    render(<AnimatedNumber value="N/A" />);
    expect(screen.getByText("N/A")).toBeDefined();
  });

  it("renders numeric string with prefix and suffix", () => {
    render(<AnimatedNumber value="$1,234.56 USD" />);
    const el = screen.getByText(/1,234\.56/);
    expect(el.textContent).toContain("$");
    expect(el.textContent).toContain("USD");
  });

  it("renders a number value", () => {
    render(<AnimatedNumber value={42} />);
    expect(screen.getByText("42")).toBeDefined();
  });

  it("renders negative numbers", () => {
    render(<AnimatedNumber value="-99.5" />);
    expect(screen.getByText(/-99\.5/)).toBeDefined();
  });

  it("applies className", () => {
    const { container } = render(<AnimatedNumber value="100" className="test-class" />);
    expect(container.querySelector(".test-class")).toBeDefined();
  });
});
