/**
 * / — Live LOS detectability dashboard.
 *
 * Was previously the entire App.tsx; the routing migration moved it here
 * unchanged except for dropping the outer min-h-screen wrapper (RootLayout
 * owns that now) and the duplicate page header (also in RootLayout).
 */
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { LOSPolarPlot } from "@/components/LOSPolarPlot";
import { StationProfileChart } from "@/components/StationProfileChart";
import { LiveMockBadge, type DataSource } from "@/components/LiveMockBadge";
import { FlightSelectors, GEOMETRY_PRESETS, type GeometryPreset } from "@/components/FlightSelectors";
import { GeometryUpload } from "@/components/GeometryUpload";
import { ResultsCard } from "@/components/ResultsCard";
import staticMock from "@/data/mock_los.json";
import type { LOSData, MultiFreqScanRequest } from "@/types/los";
import { API_BASE_URL, ANALYZE_PATH } from "@/config";

const DEFAULT_MACH = 22.5;
const DEFAULT_ALT = 61;

const DEFAULT_GEOMETRY: GeometryPreset = GEOMETRY_PRESETS[0]; // RAM-C

const DEFAULT_ANGLES = [
  0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180,
] as const;

export default function HomePage() {
  const [mach, setMach] = useState<number>(DEFAULT_MACH);
  const [alt, setAlt] = useState<number>(DEFAULT_ALT);
  const [geometry, setGeometry] = useState<GeometryPreset>(DEFAULT_GEOMETRY);

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
      vehicle: {
        nose_radius_m: geometry.nose_radius_m,
        half_angle_deg: geometry.half_angle_deg,
        length_m: geometry.length_m,
        name: geometry.name,
      },
      flight: { mach, altitude_km: alt },
      aspect_angles_deg: [...DEFAULT_ANGLES],
    };

    async function load() {
      try {
        const res = await fetch(`${API_BASE_URL}${ANALYZE_PATH}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
          signal: AbortSignal.timeout(15000),
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
  }, [mach, alt, geometry]);

  function toggleFreq(i: number) {
    setVisibleFreqs((prev) =>
      prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]
    );
  }

  return (
    <div className="p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Hypersonic Plasma Analysis
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Upload geometry → set flight conditions → get detection report.
              Re-runs automatically on any input change.
            </p>
          </div>
          <LiveMockBadge source={source} />
        </div>

        {/* Step 1: Geometry */}
        <GeometryUpload geometry={geometry} onGeometryChange={setGeometry} />

        {/* Step 2: Flight conditions */}
        <div className="rounded-lg border border-border bg-card p-4 space-y-3">
          <div className="flex items-baseline justify-between">
            <h3 className="text-sm font-semibold">2. Flight conditions</h3>
            <span className="text-xs text-muted-foreground">
              M = {mach.toFixed(1)} · {alt} km altitude
            </span>
          </div>
          <FlightSelectors
            mach={mach}
            alt={alt}
            geometryName={geometry.name}
            onMachChange={setMach}
            onAltChange={setAlt}
          />
        </div>

        {source === "error" && <ErrorBanner message={errorMsg} />}

        {/* Step 3: Results — only when we have live or fallback data */}
        {source !== "loading" && data && <ResultsCard data={data} />}

        <div className="flex flex-wrap gap-3 items-center rounded-lg border border-border bg-card p-3">
          <span className="text-xs font-medium text-muted-foreground">
            Frequencies:
          </span>
          {data.frequencies.map((f, i) => {
            const visible = visibleFreqs.includes(i);
            return (
              <button
                key={f.label}
                type="button"
                aria-pressed={visible}
                aria-label={`Toggle ${f.label} ${visible ? "off" : "on"}`}
                onClick={() => toggleFreq(i)}
                className={[
                  "rounded-full px-3 py-1 text-xs font-medium transition-colors",
                  visible
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80",
                ].join(" ")}
              >
                {f.label}
              </button>
            );
          })}
          <div className="ml-auto flex items-center gap-2">
            <span id="uq-toggle-label" className="text-xs text-muted-foreground">
              UQ band
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={showUQ}
              aria-labelledby="uq-toggle-label"
              onClick={() => setShowUQ((v) => !v)}
              className={[
                "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
                showUQ ? "bg-primary" : "bg-muted",
              ].join(" ")}
            >
              <span
                aria-hidden="true"
                className={[
                  "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform",
                  showUQ ? "translate-x-4" : "translate-x-1",
                ].join(" ")}
              />
            </button>
          </div>
        </div>

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

        {/* (Top-line metrics now live in ResultsCard above the chart) */}

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
                POST {API_BASE_URL}{ANALYZE_PATH}
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

function LoadingSkeleton() {
  return (
    <div
      data-testid="loading-skeleton"
      className="flex h-[380px] items-center justify-center rounded-lg border border-border bg-card"
    >
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Fetching scan…
      </div>
    </div>
  );
}

function ErrorBanner({ message }: { message: string | null }) {
  return (
    <div
      data-testid="error-banner"
      role="alert"
      className="rounded-lg border border-red-900 bg-red-950/40 p-3 text-sm text-red-300"
    >
      <div className="font-medium">Failed to load scan</div>
      <div className="mt-1 font-mono text-xs">{message ?? "unknown error"}</div>
    </div>
  );
}
