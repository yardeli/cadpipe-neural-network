import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LOSPolarPlot } from "@/components/LOSPolarPlot";
import staticMock from "@/data/mock_los.json";
import type { LOSData } from "@/types/los";

const data = staticMock as unknown as LOSData;
const ALL_VISIBLE = data.frequencies.map((_, i) => i);

describe("LOSPolarPlot", () => {
  it("renders the SVG chart container", () => {
    const { container } = render(
      <LOSPolarPlot data={data} visibleFreqs={ALL_VISIBLE} showUQ
                    width={620} height={380} />
    );
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("draws one freq-line path per visible frequency band", () => {
    render(
      <LOSPolarPlot data={data} visibleFreqs={ALL_VISIBLE} showUQ={false}
                    width={620} height={380} />
    );
    const lines = screen.getAllByTestId("freq-line");
    expect(lines).toHaveLength(data.frequencies.length);
  });

  it("each freq-line carries its band label as data-band-label", () => {
    render(
      <LOSPolarPlot data={data} visibleFreqs={ALL_VISIBLE} showUQ={false}
                    width={620} height={380} />
    );
    const lines = screen.getAllByTestId("freq-line");
    const labels = lines.map((el) => el.getAttribute("data-band-label"));
    expect(labels).toEqual(data.frequencies.map((f) => f.label));
  });

  it("toggling a frequency off removes its line from the chart", () => {
    const { rerender } = render(
      <LOSPolarPlot data={data} visibleFreqs={ALL_VISIBLE} showUQ={false}
                    width={620} height={380} />
    );
    expect(screen.getAllByTestId("freq-line")).toHaveLength(data.frequencies.length);

    // Hide the first band.
    rerender(
      <LOSPolarPlot data={data} visibleFreqs={ALL_VISIBLE.slice(1)} showUQ={false}
                    width={620} height={380} />
    );
    const remaining = screen.getAllByTestId("freq-line");
    expect(remaining).toHaveLength(data.frequencies.length - 1);
    // The hidden band's label is not in the rendered set.
    const labels = remaining.map((el) => el.getAttribute("data-band-label"));
    expect(labels).not.toContain(data.frequencies[0].label);
  });

  it("renders no freq-lines when no frequencies are visible", () => {
    render(
      <LOSPolarPlot data={data} visibleFreqs={[]} showUQ={false}
                    width={620} height={380} />
    );
    expect(screen.queryAllByTestId("freq-line")).toHaveLength(0);
  });
});
