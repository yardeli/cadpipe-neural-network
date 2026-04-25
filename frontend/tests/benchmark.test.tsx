import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import BenchmarkPage from "@/routes/benchmark";
import staticMock from "@/data/mock_benchmark.json";

function liveResponse(overrides: Record<string, unknown> = {}): Response {
  const body = { ...(staticMock as unknown as object), ...overrides };
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(liveResponse());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BenchmarkPage", () => {
  it("renders the page header on initial render", () => {
    render(<BenchmarkPage />);
    expect(
      screen.getByRole("heading", { name: /Benchmark — RAM-C II/i })
    ).toBeInTheDocument();
  });

  it("transitions to LIVE badge after a successful fetch", async () => {
    render(<BenchmarkPage />);
    await waitFor(() => {
      const badge = screen.getByTestId("live-mock-badge");
      expect(badge).toHaveAttribute("data-source", "live");
    });
  });

  it("renders the summary card with totals + pass/fail counts", async () => {
    render(<BenchmarkPage />);
    await waitFor(() =>
      expect(screen.getByTestId("benchmark-summary")).toBeInTheDocument()
    );
    const summary = screen.getByTestId("benchmark-summary");
    expect(within(summary).getByText("Total cases")).toBeInTheDocument();
    expect(within(summary).getByText("Pass")).toBeInTheDocument();
    expect(within(summary).getByText("Fail")).toBeInTheDocument();
    expect(within(summary).getByText("Max |log10 err|")).toBeInTheDocument();
  });

  it("renders 12 rows in the comparison table (4 alts × 3 freqs)", async () => {
    render(<BenchmarkPage />);
    await waitFor(() =>
      expect(screen.getByTestId("benchmark-table")).toBeInTheDocument()
    );
    const table = screen.getByTestId("benchmark-table");
    // 1 header row + 12 data rows
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(13);
  });

  it("tags pass/fail rows with data-pass attribute", async () => {
    render(<BenchmarkPage />);
    await waitFor(() =>
      expect(screen.getByTestId("benchmark-table")).toBeInTheDocument()
    );
    const table = screen.getByTestId("benchmark-table");
    const dataRows = within(table)
      .getAllByRole("row")
      .filter((r) => r.hasAttribute("data-pass"));
    // mock_benchmark.json has 6 pass + 6 fail.
    expect(dataRows).toHaveLength(12);
    const passRows = dataRows.filter((r) => r.getAttribute("data-pass") === "true");
    const failRows = dataRows.filter((r) => r.getAttribute("data-pass") === "false");
    expect(passRows).toHaveLength(6);
    expect(failRows).toHaveLength(6);
  });

  it("renders the trajectory chart with an aria-label", async () => {
    render(<BenchmarkPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("img", { name: /benchmark trajectory plot/i })
      ).toBeInTheDocument();
    });
  });

  it("falls back to MOCK badge + static data when fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("Failed to fetch")
    );
    render(<BenchmarkPage />);
    await waitFor(() => {
      const badge = screen.getByTestId("live-mock-badge");
      expect(badge).toHaveAttribute("data-source", "mock");
    });
    // Table still renders from static fallback.
    const table = screen.getByTestId("benchmark-table");
    expect(within(table).getAllByRole("row")).toHaveLength(13);
  });

  it("shows ERROR banner on a 5xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("internal", { status: 500 })
    );
    render(<BenchmarkPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "error");
  });

  it("shows ERROR banner on a malformed response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ unexpected: "shape" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    render(<BenchmarkPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeInTheDocument();
    });
  });
});
