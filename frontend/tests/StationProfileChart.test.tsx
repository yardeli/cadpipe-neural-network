import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StationProfileChart } from "@/components/StationProfileChart";
import type { StationEntry } from "@/types/los";

const FIVE_STATIONS: StationEntry[] = [
  { zL: 0.14, z_m: 0.18, r_wall_m: 0.19, max_ne_m3: 1.5e18, p99_ne_m3: 1.4e18, max_T_tr_K: 4500 },
  { zL: 0.32, z_m: 0.41, r_wall_m: 0.26, max_ne_m3: 6.9e17, p99_ne_m3: 6.3e17, max_T_tr_K: 3400 },
  { zL: 0.48, z_m: 0.62, r_wall_m: 0.32, max_ne_m3: 3.3e17, p99_ne_m3: 3.0e17, max_T_tr_K: 2600 },
  { zL: 0.67, z_m: 0.87, r_wall_m: 0.40, max_ne_m3: 1.4e17, p99_ne_m3: 1.3e17, max_T_tr_K: 1900 },
  { zL: 0.88, z_m: 1.14, r_wall_m: 0.48, max_ne_m3: 5.2e16, p99_ne_m3: 4.8e16, max_T_tr_K: 1370 },
];

describe("StationProfileChart", () => {
  it("renders the SVG chart container with an aria-label", () => {
    render(<StationProfileChart stations={FIVE_STATIONS} />);
    const svg = screen.getByRole("img", {
      name: /electron density vs axial station/i,
    });
    expect(svg).toBeInTheDocument();
  });

  it("renders one marker dot per station (5 input → 5 circles)", () => {
    const { container } = render(<StationProfileChart stations={FIVE_STATIONS} />);
    // The chart draws one <circle> per station as the data marker.
    expect(container.querySelectorAll("circle")).toHaveLength(5);
  });

  it("renders a polyline connecting the stations", () => {
    const { container } = render(<StationProfileChart stations={FIVE_STATIONS} />);
    // Two polylines: max nₑ (solid) and p99 nₑ (dashed).
    expect(container.querySelectorAll("polyline").length).toBeGreaterThanOrEqual(2);
  });

  it("shows zL tick labels for each station along the x-axis", () => {
    render(<StationProfileChart stations={FIVE_STATIONS} />);
    expect(screen.getByText("0.14")).toBeInTheDocument();
    expect(screen.getByText("0.88")).toBeInTheDocument();
  });

  it("renders an empty SVG without circles when stations is empty", () => {
    const { container } = render(<StationProfileChart stations={[]} />);
    expect(container.querySelectorAll("circle")).toHaveLength(0);
  });
});
