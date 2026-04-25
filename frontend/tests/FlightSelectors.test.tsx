import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FlightSelectors } from "@/components/FlightSelectors";

describe("FlightSelectors", () => {
  it("renders both Mach and Altitude radiogroups", () => {
    render(<FlightSelectors mach={22.5} alt={61}
                            onMachChange={vi.fn()} onAltChange={vi.fn()} />);
    expect(screen.getByRole("radiogroup", { name: "Mach" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Altitude" })).toBeInTheDocument();
  });

  it("marks the currently selected pill aria-checked", () => {
    render(<FlightSelectors mach={22.5} alt={61}
                            onMachChange={vi.fn()} onAltChange={vi.fn()} />);
    const machGroup = screen.getByRole("radiogroup", { name: "Mach" });
    const altGroup = screen.getByRole("radiogroup", { name: "Altitude" });
    // Each group has 4 radio buttons; the selected one is aria-checked=true.
    const mach22 = within(machGroup).getByRole("radio", { name: "22.5" });
    const alt61 = within(altGroup).getByRole("radio", { name: "61 km" });
    expect(mach22).toHaveAttribute("aria-checked", "true");
    expect(alt61).toHaveAttribute("aria-checked", "true");
  });

  it("calls onMachChange with the clicked Mach value", async () => {
    const onMachChange = vi.fn();
    render(<FlightSelectors mach={22.5} alt={61}
                            onMachChange={onMachChange} onAltChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: "18.5" }));
    expect(onMachChange).toHaveBeenCalledWith(18.5);
  });

  it("calls onAltChange with the clicked altitude", async () => {
    const onAltChange = vi.fn();
    render(<FlightSelectors mach={22.5} alt={61}
                            onMachChange={vi.fn()} onAltChange={onAltChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "81 km" }));
    expect(onAltChange).toHaveBeenCalledWith(81);
  });
});

// Need to import within after the describe block reference; pulling here so
// the file stays organized with the API-style tests above.
import { within } from "@testing-library/react";
