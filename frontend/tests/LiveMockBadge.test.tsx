import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LiveMockBadge } from "@/components/LiveMockBadge";

describe("LiveMockBadge", () => {
  it("renders the LIVE state with green pill text", () => {
    render(<LiveMockBadge source="live" />);
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "live");
    expect(badge).toHaveTextContent("LIVE");
  });

  it("renders the MOCK state when the server is unreachable", () => {
    render(<LiveMockBadge source="mock" />);
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "mock");
    expect(badge).toHaveTextContent("MOCK");
  });

  it("renders the ERROR state in red", () => {
    render(<LiveMockBadge source="error" />);
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "error");
    expect(badge).toHaveTextContent("ERROR");
  });

  it("renders the loading state with the connecting spinner", () => {
    render(<LiveMockBadge source="loading" />);
    const badge = screen.getByTestId("live-mock-badge");
    expect(badge).toHaveAttribute("data-source", "loading");
    expect(badge).toHaveTextContent(/connecting/i);
  });
});
