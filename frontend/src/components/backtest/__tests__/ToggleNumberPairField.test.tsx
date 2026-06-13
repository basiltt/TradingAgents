import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { useForm } from "react-hook-form";
import { ToggleNumberPairField } from "../config-form/ToggleNumberPairField";

function Harness({ enabled = false, minutes = null }: { enabled?: boolean; minutes?: number | null }) {
  const { control } = useForm({
    defaultValues: { cooloff_on_success_enabled: enabled, cooloff_on_success_minutes: minutes },
  });
  return (
    <ToggleNumberPairField
      control={control as never}
      enabledName={"cooloff_on_success_enabled" as never}
      valueName={"cooloff_on_success_minutes" as never}
      title="Cool off after a win"
      description="pause new entries after a winning cycle"
      enabledValue={60}
      unit="min"
    />
  );
}

describe("ToggleNumberPairField", () => {
  it("hides the value input when the toggle is off", () => {
    render(<Harness enabled={false} />);
    expect(screen.queryByRole("spinbutton")).toBeNull();
  });

  it("reveals the value input and seeds the default when toggled on", () => {
    render(<Harness enabled={false} />);
    // The neu Checkbox is a span[role=checkbox]; click the wrapping label text to
    // toggle it (matches how the form's other toggle tests interact).
    fireEvent.click(screen.getByText("Cool off after a win"));
    const input = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("60");
  });

  it("shows the existing value when mounted already-enabled", () => {
    render(<Harness enabled={true} minutes={480} />);
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("480");
  });

  it("re-seeds the default after a disable→re-enable cycle (keeps the form valid)", () => {
    render(<Harness enabled={false} />);
    // Enable (seeds 60), disable (clears to null), enable again — must re-seed 60 so
    // the schema's enabled-requires-minutes refinement still holds.
    fireEvent.click(screen.getByText("Cool off after a win"));
    fireEvent.click(screen.getByText("Cool off after a win"));
    expect(screen.queryByRole("spinbutton")).toBeNull();
    fireEvent.click(screen.getByText("Cool off after a win"));
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("60");
  });
});
