import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "@/App";
import staticMock from "@/data/mock_los.json";

// Build a fresh mock response each time so per-test mutations don't bleed.
function mockResponse(overrides: Record<string, unknown> = {}): Response {
  const body = { ...(staticMock as unknown as object), ...overrides };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  // Force a clean fetch mock for every test.
  vi.spyOn(globalThis, "fetch").mockResolvedValue(mockResponse());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("shows the page header on initial render", async () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: /PlasmaNet — Detection Dashboard/i })
    ).toBeInTheDocument();
  });

  it("transitions to LIVE badge after a successful fetch", async () => {
    render(<App />);
    await waitFor(() => {
      const badge = screen.getByTestId("live-mock-badge");
      expect(badge).toHaveAttribute("data-source", "live");
    });
  });

  it("renders the polar chart and station chart after a successful fetch", async () => {
    render(<App />);
    await waitFor(() => {
      // freq-line testids come from LOSPolarPlot once data is loaded.
      expect(screen.getAllByTestId("freq-line").length).toBeGreaterThan(0);
    });
    // mock_los.json has a station_profile baked in (commit 1881a68).
    expect(
      screen.getByRole("img", { name: /electron density vs axial station/i })
    ).toBeInTheDocument();
  });

  it("falls back to MOCK badge when fetch fails (network error)", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("Failed to fetch")
    );
    render(<App />);
    await waitFor(() => {
      const badge = screen.getByTestId("live-mock-badge");
      expect(badge).toHaveAttribute("data-source", "mock");
    });
    // Chart still renders from static mock.
    expect(screen.getAllByTestId("freq-line").length).toBeGreaterThan(0);
  });

  it("shows ERROR banner when fetch returns a malformed response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ unexpected: "shape" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "error");
  });

  it("shows ERROR badge on a 5xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("internal error", { status: 500 })
    );
    render(<App />);
    await waitFor(() => {
      const badge = screen.getByTestId("live-mock-badge");
      expect(badge).toHaveAttribute("data-source", "error");
    });
  });

  it("refetches with new flight params when a Mach pill is clicked", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse());
    render(<App />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });

    const mach18 = screen.getByRole("radio", { name: "18.5" });
    await userEvent.click(mach18);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });

    // Inspect the second call's body — should carry mach=18.5.
    const secondCall = fetchSpy.mock.calls[1];
    const init = secondCall[1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.flight.mach).toBe(18.5);
  });

  it("refetches with new altitude when an Altitude pill is clicked", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(mockResponse());
    render(<App />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });

    const alt81 = screen.getByRole("radio", { name: "81 km" });
    await userEvent.click(alt81);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });

    const init = fetchSpy.mock.calls[1][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.flight.altitude_km).toBe(81);
  });
});
