import { useEffect, useState } from "react";
import { LOSPolarPlot } from "@/components/LOSPolarPlot";
import staticMock from "@/data/mock_los.json";
import type { LOSData } from "@/types/los";

const MOCK_SERVER = "http://localhost:8200";

const MOCK_REQUEST = {
  vehicle: { nose_radius_m: 0.1524, half_angle_deg: 9.0, length_m: 1.295, name: "ram_c" },
  flight: { mach: 22.5, altitude_km: 61.0 },
  aspect_angles_deg: [0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180],
};

type DataSource = "loading" | "live" | "mock";

export default function App() {
  const [data, setData] = useState<LOSData>(staticMock as unknown as LOSData);
  const [source, setSource] = useState<DataSource>("loading");
  const [visibleFreqs, setVisibleFreqs] = useState<number[]>([]);
  const [showUQ, setShowUQ] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`${MOCK_SERVER}/api/plasma/analyze_scan`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(MOCK_REQUEST),
          signal: AbortSignal.timeout(4000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const live = (await res.json()) as LOSData;
        if (!cancelled) {
          setData(live);
          setVisibleFreqs(live.frequencies.map((_, i) => i));
          setSource("live");
        }
      } catch {
        if (!cancelled) {
          const fallback = staticMock as unknown as LOSData;
          setData(fallback);
          setVisibleFreqs(fallback.frequencies.map((_, i) => i));
          setSource("mock");
        }
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  function toggleFreq(i: number) {
    setVisibleFreqs((prev) =>
      prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Page header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              PlasmaNet — Detection Dashboard
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Aspect-resolved LOS radar attenuation
            </p>
          </div>
          <SourceBadge source={source} />
        </div>

        {/* Controls */}
        <div className="flex flex-wrap gap-3 items-center rounded-lg border border-border bg-card p-3">
          <span className="text-xs font-medium text-muted-foreground">Frequencies:</span>
          {data.frequencies.map((f, i) => (
            <button
              key={f.label}
              onClick={() => toggleFreq(i)}
              className={[
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                visibleFreqs.includes(i)
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">UQ band</span>
            <button
              onClick={() => setShowUQ((v) => !v)}
              className={[
                "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                showUQ ? "bg-primary" : "bg-muted",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform",
                  showUQ ? "translate-x-4" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </div>
        </div>

        {/* Main chart */}
        <LOSPolarPlot
          data={data}
          visibleFreqs={visibleFreqs}
          showUQ={showUQ}
          width={620}
          height={380}
        />

        {/* Stagnation summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Mach", value: data.meta.mach.toFixed(1) },
            { label: "Altitude", value: `${data.meta.altitude_km} km` },
            {
              label: "nₑ (stag)",
              value: data.meta.stagnation.ne_m3.toExponential(1) + " m⁻³",
            },
            {
              label: "fₚ",
              value: `${data.meta.stagnation.fp_GHz.toFixed(1)} GHz`,
            },
          ].map(({ label, value }) => (
            <div
              key={label}
              className="rounded-lg border border-border bg-card p-3 text-center"
            >
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-1 text-sm font-semibold tabular-nums">{value}</div>
            </div>
          ))}
        </div>

        {/* Two-temperature row (NEMO mode) */}
        {data.meta.stagnation.T_ve_K && (
          <div className="rounded-lg border border-border bg-card p-3">
            <div className="text-xs font-medium text-muted-foreground mb-2">
              Two-temperature state (SU2-NEMO)
            </div>
            <div className="flex gap-6 text-sm">
              <div>
                <span className="text-muted-foreground">T_tr = </span>
                <span className="font-mono">
                  {data.meta.stagnation.T_tr_K.toLocaleString()} K
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">T_ve = </span>
                <span className="font-mono">
                  {data.meta.stagnation.T_ve_K.toLocaleString()} K
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">ΔT = </span>
                <span className="font-mono text-amber-400">
                  {(
                    data.meta.stagnation.T_tr_K - data.meta.stagnation.T_ve_K
                  ).toLocaleString()}{" "}
                  K
                </span>
              </div>
            </div>
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          {source === "live" ? (
            <>
              Live data from{" "}
              <code className="rounded bg-muted px-1">
                POST {MOCK_SERVER}/api/plasma/analyze_scan
              </code>
            </>
          ) : (
            <>
              Static mock data — start{" "}
              <code className="rounded bg-muted px-1">mock_server.py</code> on
              port 8200 to show live predictions. See{" "}
              <code className="rounded bg-muted px-1">
                docs/SIMOPS_INTEGRATION.md
              </code>{" "}
              for the API contract.
            </>
          )}
        </p>
      </div>
    </div>
  );
}

function SourceBadge({ source }: { source: DataSource }) {
  if (source === "loading") {
    return (
      <span className="mt-1 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground animate-pulse">
        connecting…
      </span>
    );
  }
  if (source === "live") {
    return (
      <span className="mt-1 flex items-center gap-1.5 rounded-full border border-emerald-700 bg-emerald-950 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        LIVE
      </span>
    );
  }
  return (
    <span className="mt-1 flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
      MOCK
    </span>
  );
}
