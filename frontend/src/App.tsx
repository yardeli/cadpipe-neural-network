import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { LOSPolarPlot } from "@/components/LOSPolarPlot";
import { StationProfileChart } from "@/components/StationProfileChart";
import staticMock from "@/data/mock_los.json";
import type { LOSData, MultiFreqScanRequest } from "@/types/los";

const MOCK_SERVER = "http://localhost:8200";

// RAM-C II validation grid — Jones & Cross 1972 instrumented altitudes
// and the matching trajectory Mach numbers.
const ALTITUDE_OPTIONS_KM = [47, 61, 71, 81] as const;
const MACH_OPTIONS = [18.5, 22.5, 23.6, 23.9] as const;

// Default to the J&C primary validation point (M22.5 / 61 km).
const DEFAULT_MACH = 22.5;
const DEFAULT_ALT = 61;

const RAM_C_VEHICLE = {
  nose_radius_m: 0.1524,
  half_angle_deg: 9.0,
  length_m: 1.295,
  name: "ram_c",
} as const;

const DEFAULT_ANGLES = [
  0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180,
] as const;

type DataSource = "loading" | "live" | "mock" | "error";

export default function App() {
  const [mach, setMach] = useState<number>(DEFAULT_MACH);
  const [alt, setAlt] = useState<number>(DEFAULT_ALT);

  const [data, setData] = useState<LOSData>(staticMock as unknown as LOSData);
  const [source, setSource] = useState<DataSource>("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [visibleFreqs, setVisibleFreqs] = useState<number[]>([]);
  const [showUQ, setShowUQ] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setSource("loading");
    setErrorMsg(null);

    const request: MultiFreqScanRequest = {
      vehicle: { ...RAM_C_VEHICLE },
      flight: { mach, altitude_km: alt },
      aspect_angles_deg: [...DEFAULT_ANGLES],
    };

    async function load() {
      try {
        const res = await fetch(`${MOCK_SERVER}/api/plasma/analyze_scan`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
          signal: AbortSignal.timeout(6000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
        const live = (await res.json()) as LOSData;
        validateLOSData(live);

        if (!cancelled) {
          setData(live);
          setVisibleFreqs(live.frequencies.map((_, i) => i));
          setSource("live");
        }
      } catch (err) {
        // Server unreachable → fall back to static mock; malformed server
        // response → show inline error so the user sees what went wrong.
        if (cancelled) return;

        const msg = err instanceof Error ? err.message : String(err);
        const isFetchFailure =
          msg.includes("Failed to fetch") ||
          msg.includes("NetworkError") ||
          msg.includes("timeout") ||
          msg.includes("AbortError");

        if (isFetchFailure) {
          const fallback = staticMock as unknown as LOSData;
          setData(fallback);
          setVisibleFreqs(fallback.frequencies.map((_, i) => i));
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
  }, [mach, alt]);

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

        {/* Flight-condition selectors */}
        <div className="flex flex-wrap gap-4 rounded-lg border border-border bg-card p-3">
          <SelectorRow
            label="Mach"
            value={mach}
            options={MACH_OPTIONS}
            format={(v) => v.toFixed(1)}
            onChange={setMach}
          />
          <SelectorRow
            label="Altitude"
            value={alt}
            options={ALTITUDE_OPTIONS_KM}
            format={(v) => `${v} km`}
            onChange={setAlt}
          />
        </div>

        {/* Error state */}
        {source === "error" && <ErrorBanner message={errorMsg} />}

        {/* Frequency / UQ controls */}
        <div className="flex flex-wrap gap-3 items-center rounded-lg border border-border bg-card p-3">
          <span className="text-xs font-medium text-muted-foreground">
            Frequencies:
          </span>
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

        {/* Loading skeleton OR charts */}
        {source === "loading" ? (
          <LoadingSkeleton />
        ) : (
          <>
            <LOSPolarPlot
              data={data}
              visibleFreqs={visibleFreqs}
              showUQ={showUQ}
              width={620}
              height={380}
            />
            {data.meta.station_profile && data.meta.station_profile.length > 0 && (
              <StationProfileChart
                stations={data.meta.station_profile}
                width={620}
                height={240}
              />
            )}
          </>
        )}

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
                    data.meta.stagnation.T_tr_K -
                    data.meta.stagnation.T_ve_K
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

// ── Helpers ─────────────────────────────────────────────────────────────────

function validateLOSData(d: unknown): asserts d is LOSData {
  if (!d || typeof d !== "object") throw new Error("response is not an object");
  const obj = d as Record<string, unknown>;
  if (!obj.meta || typeof obj.meta !== "object") {
    throw new Error("response missing meta");
  }
  if (!Array.isArray(obj.frequencies)) {
    throw new Error("response missing frequencies array");
  }
}

interface SelectorRowProps<T extends number> {
  label: string;
  value: T;
  options: readonly T[];
  format: (v: T) => string;
  onChange: (v: T) => void;
}

function SelectorRow<T extends number>({
  label,
  value,
  options,
  format,
  onChange,
}: SelectorRowProps<T>) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex gap-1">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className={[
              "rounded px-2 py-1 text-xs font-medium transition-colors tabular-nums",
              opt === value
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80",
            ].join(" ")}
          >
            {format(opt)}
          </button>
        ))}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex h-[380px] items-center justify-center rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Fetching scan…
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string | null }) {
  return (
    <div className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
      <div className="font-medium">Failed to load scan</div>
      <div className="mt-1 font-mono text-xs">{message ?? "unknown error"}</div>
    </div>
  );
}

function SourceBadge({ source }: { source: DataSource }) {
  if (source === "loading") {
    return (
      <span className="mt-1 flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
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
  if (source === "error") {
    return (
      <span className="mt-1 flex items-center gap-1.5 rounded-full border border-red-700 bg-red-950 px-2.5 py-0.5 text-xs font-medium text-red-400">
        <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
        ERROR
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
