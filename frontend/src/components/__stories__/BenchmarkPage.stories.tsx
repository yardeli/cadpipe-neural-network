/**
 * Stories for BenchmarkPage cover the three states the route can be in:
 *   - LIVE with the current 6-pass / 6-fail mock_benchmark.json data
 *   - LIVE with a fake all-passing dataset (what we'd ship after a model
 *     improvement that brought the M22.5/61 km error inside ±0.5)
 *   - MOCK fallback when the upstream is unreachable
 *
 * The `parameters.fetch` block isn't a real Storybook param — we patch
 * window.fetch in a decorator so each story controls the upstream
 * response without caring about the page's internal state machine.
 */
import { useEffect } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import BenchmarkPage from "../../routes/benchmark";
import staticMock from "../../data/mock_benchmark.json";
import type { RamCBenchmarkResponse } from "../../types/los";

const meta = {
  title: "Pages/BenchmarkPage",
  component: BenchmarkPage,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof BenchmarkPage>;

export default meta;
type Story = StoryObj<typeof meta>;

function patchFetch(response: RamCBenchmarkResponse | null) {
  window.fetch = async () => {
    if (response === null) {
      throw new TypeError("Failed to fetch");
    }
    return new Response(JSON.stringify(response), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}

function FetchPatch({
  response,
  children,
}: {
  response: RamCBenchmarkResponse | null;
  children: React.ReactNode;
}) {
  useEffect(() => {
    patchFetch(response);
  }, [response]);
  return <>{children}</>;
}

const passingMock: RamCBenchmarkResponse = {
  ...(staticMock as unknown as RamCBenchmarkResponse),
  cases: (staticMock as unknown as RamCBenchmarkResponse).cases.map((c) => ({
    ...c,
    log10_error: c.log10_error * 0.3,         // shrink errors so all pass
    within_uncertainty: true,
  })),
  summary: {
    total_cases: 12,
    pass_count: 12,
    fail_count: 0,
    max_log10_error: 0.35,
    note: "pass = |log10_error| < 0.5 (within factor 3.2 of reference)",
  },
};

export const LiveMixedPassFail: Story = {
  name: "LIVE — current data (6 pass / 6 fail)",
  render: () => (
    <FetchPatch response={staticMock as unknown as RamCBenchmarkResponse}>
      <BenchmarkPage />
    </FetchPatch>
  ),
};

export const LiveAllPassing: Story = {
  name: "LIVE — hypothetical all-passing model",
  render: () => (
    <FetchPatch response={passingMock}>
      <BenchmarkPage />
    </FetchPatch>
  ),
};

export const MockFallback: Story = {
  name: "MOCK — upstream unreachable",
  render: () => (
    <FetchPatch response={null}>
      <BenchmarkPage />
    </FetchPatch>
  ),
};
