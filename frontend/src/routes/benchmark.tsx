/**
 * /benchmark — RAM-C II J&C 1972 validation table.
 *
 * Fetches GET /api/plasma/benchmark/ram_c on mount and renders:
 *   - summary card  (total / pass / fail / max |log10 error|)
 *   - 12-row comparison table (4 altitudes × 3 reflectometer frequencies)
 *   - trajectory chart (predicted vs reference n_e, log-y by altitude)
 *
 * LIVE/MOCK badge in the header signals whether the data came from the
 * mock_server or fell back to the static mock_benchmark.json snapshot.
 */
import { useEffect, useState } from "react";
import { LiveMockBadge, type DataSource } from "@/components/LiveMockBadge";
import { BenchmarkChart } from "@/components/BenchmarkChart";
import staticMock from "@/data/mock_benchmark.json";
import type { RamCBenchmarkResponse } from "@/types/los";
import { API_BASE_URL, BENCHMARK_PATH } from "@/config";

export default function BenchmarkPage() {
  // `data` is null while loading so we don't render the chart with stale
  // mock numbers and then snap to live numbers — that's the "second dot
  // drops between LOADING and LIVE" effect. Show a skeleton instead and
  // only paint once we know what the server actually says.
  const [data, setData] = useState<RamCBenchmarkResponse | null>(null);
  const [source, setSource] = useState<DataSource>("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSource("loading");
    setErrorMsg(null);

    async function load() {
      try {
        const res = await fetch(`${API_BASE_URL}${BENCHMARK_PATH}`, {
          signal: AbortSignal.timeout(6000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
        const live = (await res.json()) as RamCBenchmarkResponse;
        if (!live || !Array.isArray(live.cases) || !live.summary) {
          throw new Error("response missing required fields");
        }
        if (!cancelled) {
          setData(live);
          setSource("live");
        }
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        const isFetchFailure =
          msg.includes("Failed to fetch") ||
          msg.includes("NetworkError") ||
          msg.includes("timeout") ||
          msg.includes("AbortError");
        if (isFetchFailure) {
          setData(staticMock as unknown as RamCBenchmarkResponse);
          setSource("mock");
          setErrorMsg(null);
        } else {
          setErrorMsg(msg);
          setSource("error");
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Benchmark — RAM-C II / Jones &amp; Cross 1972
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Predicted vs published peak n
              <sub>e</sub> at the 4 reflectometer instrumentation altitudes,
              compared at 3 radar frequencies each.
            </p>
          </div>
          <LiveMockBadge source={source} />
        </div>

        {source === "error" && (
          <div
            data-testid="error-banner"
            role="alert"
            className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm text-red-300"
          >
            <div className="font-medium">Failed to load benchmark</div>
            <div className="mt-1 font-mono text-xs">
              {errorMsg ?? "unknown error"}
            </div>
          </div>
        )}

        {data === null ? (
          <BenchmarkSkeleton />
        ) : (
          <>
            <SummaryCard summary={data.summary} />
            <BenchmarkChart cases={data.cases} width={620} height={240} />
            <ComparisonTable cases={data.cases} />
            <p className="text-xs text-muted-foreground">
              Reference: Jones &amp; Cross 1972 (NASA TN D-6617). Pass criterion:
              <code className="mx-1 rounded bg-muted px-1">|log10 error| &lt; 0.5</code>
              (within a factor of ~3.2 of the published n
              <sub>e</sub>). Generated{" "}
              <span className="font-mono">{data.generated_at}</span>.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function SummaryCard({
  summary,
}: {
  summary: RamCBenchmarkResponse["summary"];
}) {
  const passRate = summary.total_cases
    ? ((summary.pass_count / summary.total_cases) * 100).toFixed(0)
    : "—";
  return (
    <div
      data-testid="benchmark-summary"
      className="rounded-lg border border-border bg-card p-3"
    >
      <div className="mb-2 text-xs font-medium text-muted-foreground">
        Summary
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <SummaryStat label="Total cases" value={summary.total_cases.toString()} />
        <SummaryStat
          label="Pass"
          value={`${summary.pass_count} (${passRate}%)`}
          tone="pass"
        />
        <SummaryStat
          label="Fail"
          value={summary.fail_count.toString()}
          tone={summary.fail_count > 0 ? "fail" : undefined}
        />
        <SummaryStat
          label="Max |log10 err|"
          value={summary.max_log10_error.toFixed(2)}
          tone={summary.max_log10_error < 0.5 ? "pass" : "fail"}
        />
      </div>
      {summary.note && (
        <div className="mt-3 text-xs text-muted-foreground">{summary.note}</div>
      )}
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pass" | "fail";
}) {
  const toneClass =
    tone === "pass"
      ? "text-emerald-400"
      : tone === "fail"
        ? "text-red-400"
        : "";
  return (
    <div className="rounded border border-border bg-background p-2 text-center">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}

function BenchmarkSkeleton() {
  return (
    <div
      data-testid="benchmark-skeleton"
      className="space-y-3"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="h-[88px] animate-pulse rounded-lg border border-border bg-card" />
      <div className="h-[260px] animate-pulse rounded-lg border border-border bg-card" />
      <div className="h-[420px] animate-pulse rounded-lg border border-border bg-card" />
    </div>
  );
}

function ComparisonTable({ cases }: { cases: RamCBenchmarkResponse["cases"] }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <table
        data-testid="benchmark-table"
        className="w-full text-left text-sm"
      >
        <caption className="sr-only">
          RAM-C II J&amp;C 1972 benchmark cases — predicted vs reference electron
          density and log10 error per altitude / radar frequency.
        </caption>
        <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2">Alt (km)</th>
            <th scope="col" className="px-3 py-2">Mach</th>
            <th scope="col" className="px-3 py-2">Freq (GHz)</th>
            <th scope="col" className="px-3 py-2 text-right">Predicted nₑ</th>
            <th scope="col" className="px-3 py-2 text-right">Reference nₑ</th>
            <th scope="col" className="px-3 py-2 text-right">log10 err</th>
            <th scope="col" className="px-3 py-2 text-center">Pass</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => {
            const pass = c.within_uncertainty;
            return (
              <tr
                key={i}
                data-pass={pass}
                aria-label={
                  `${c.altitude_km} km Mach ${c.mach} ${c.frequency_ghz} GHz: ` +
                  (pass ? "pass" : "fail")
                }
                className={
                  pass
                    ? "border-t border-border bg-emerald-950/30"
                    : "border-t border-border bg-red-950/20"
                }
              >
                <td className="px-3 py-2 tabular-nums">{c.altitude_km}</td>
                <td className="px-3 py-2 tabular-nums">{c.mach.toFixed(1)}</td>
                <td className="px-3 py-2 tabular-nums">
                  {c.frequency_ghz.toFixed(c.frequency_ghz < 1 ? 3 : 2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums font-mono">
                  {c.ne_predicted_m3.toExponential(2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums font-mono">
                  {c.ne_reference_m3.toExponential(2)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {c.log10_error >= 0 ? "+" : ""}
                  {c.log10_error.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-center">
                  <span
                    aria-label={pass ? "pass" : "fail"}
                    className={
                      pass
                        ? "inline-block rounded bg-emerald-900/60 px-2 py-0.5 text-xs font-medium text-emerald-300"
                        : "inline-block rounded bg-red-900/60 px-2 py-0.5 text-xs font-medium text-red-300"
                    }
                  >
                    {pass ? "✓" : "✗"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
