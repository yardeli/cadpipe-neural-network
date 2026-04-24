import { useState } from "react";
import { LOSPolarPlot } from "@/components/LOSPolarPlot";
import mockData from "@/data/mock_los.json";
import type { LOSData } from "@/types/los";

const data = mockData as unknown as LOSData;

const FREQ_LABELS = data.frequencies.map((f) => f.label);

export default function App() {
  const [visibleFreqs, setVisibleFreqs] = useState<number[]>(
    data.frequencies.map((_, i) => i)
  );
  const [showUQ, setShowUQ] = useState(true);

  function toggleFreq(i: number) {
    setVisibleFreqs((prev) =>
      prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Page header */}
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            PlasmaNet — Detection Dashboard
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Aspect-resolved LOS radar attenuation · Mock data (no backend wired)
          </p>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap gap-3 items-center rounded-lg border border-border bg-card p-3">
          <span className="text-xs font-medium text-muted-foreground">Frequencies:</span>
          {FREQ_LABELS.map((label, i) => (
            <button
              key={label}
              onClick={() => toggleFreq(i)}
              className={[
                "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                visibleFreqs.includes(i)
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              ].join(" ")}
            >
              {label}
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

        {/* Stagnation summary card */}
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
              <div className="mt-1 text-sm font-semibold tabular-nums">
                {value}
              </div>
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
          Static mock data — wire to{" "}
          <code className="rounded bg-muted px-1">POST /api/plasma/analyze</code>{" "}
          to show live predictions. See{" "}
          <code className="rounded bg-muted px-1">
            docs/SIMOPS_INTEGRATION.md
          </code>{" "}
          for the API contract.
        </p>
      </div>
    </div>
  );
}
