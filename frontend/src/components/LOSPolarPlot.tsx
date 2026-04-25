/**
 * LOSPolarPlot — Line-of-sight radar attenuation polar chart.
 *
 * Renders a semicircular polar plot (0–180°) where:
 *   - Angular axis: antenna look angle from vehicle nose
 *   - Radial axis: attenuation in dB (0 at rim, max at center)
 *   - Lines: one per radar frequency band
 *   - Shaded band: P05–P95 UQ envelope for one selected frequency
 *   - Background zones: DETECTABLE / DEGRADED / BLACKOUT thresholds
 *
 * Props accept the mock_los.json shape directly. No backend wiring needed.
 */

import { useMemo } from "react";
import type { LOSData, FrequencyBand } from "@/types/los";

// ── Geometry helpers ──────────────────────────────────────────────────────────

const DEG = Math.PI / 180;

/**
 * Convert (angle_deg from nose, attenuation_dB, chart params) → SVG x,y.
 *
 * The semicircle spans 180° left to right (0° = right = nose direction,
 * 90° = straight up = side-on, 180° = left = aft).
 * The angular offset rotates 0° to the right: SVG angle = 180° - angle_deg.
 */
function polarToXY(
  angleDeg: number,
  attenuationDb: number,
  cx: number,
  cy: number,
  maxRadius: number,
  maxDb: number
): [number, number] {
  const r = ((maxDb - attenuationDb) / maxDb) * maxRadius;
  const theta = (180 - angleDeg) * DEG;
  return [cx + r * Math.cos(theta), cy - r * Math.sin(theta)];
}

function linePath(
  points: Array<[number, number]>,
  closePath = false
): string {
  if (points.length === 0) return "";
  const d = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  return closePath ? d + " Z" : d;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DETECTABLE_THRESHOLD = 2;   // dB — below this = DETECTABLE
const DEGRADED_THRESHOLD = 20;    // dB — above this = BLACKOUT
const ANGLE_STEPS = [0, 30, 60, 90, 120, 150, 180];
const DB_RINGS = [5, 10, 20, 40];

const STATUS_COLORS: Record<string, string> = {
  DETECTABLE: "#16a34a",
  DEGRADED: "#ca8a04",
  BLACKOUT: "#dc2626",
};

// ── Sub-components ────────────────────────────────────────────────────────────

interface GridProps {
  cx: number;
  cy: number;
  maxRadius: number;
  maxDb: number;
}

function PolarGrid({ cx, cy, maxRadius, maxDb }: GridProps) {
  const rings = DB_RINGS.filter((r) => r <= maxDb);

  return (
    <g className="polar-grid" opacity={0.35}>
      {/* Background zone fills */}
      {/* DETECTABLE zone — outer rim */}
      <path
        d={`M ${cx - maxRadius} ${cy} A ${maxRadius} ${maxRadius} 0 0 1 ${cx + maxRadius} ${cy} Z`}
        fill="#16a34a"
        opacity={0.06}
      />
      {/* DEGRADED zone */}
      {(() => {
        const rDeg = (DEGRADED_THRESHOLD / maxDb) * maxRadius;
        return (
          <path
            d={`M ${cx - rDeg} ${cy} A ${rDeg} ${rDeg} 0 0 1 ${cx + rDeg} ${cy} Z`}
            fill="#ca8a04"
            opacity={0.10}
          />
        );
      })()}
      {/* BLACKOUT zone */}
      {(() => {
        const rBl = (DETECTABLE_THRESHOLD / maxDb) * maxRadius;
        return (
          <path
            d={`M ${cx - rBl} ${cy} A ${rBl} ${rBl} 0 0 1 ${cx + rBl} ${cy} Z`}
            fill="#dc2626"
            opacity={0.15}
          />
        );
      })()}

      {/* dB rings */}
      {rings.map((db) => {
        const r = ((maxDb - db) / maxDb) * maxRadius;
        return (
          <g key={db}>
            <path
              d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
              fill="none"
              stroke="#6b7280"
              strokeWidth={0.5}
              strokeDasharray="3,3"
            />
            <text
              x={cx + 4}
              y={cy - r + 12}
              fontSize={9}
              fill="#9ca3af"
              textAnchor="start"
            >
              {db} dB
            </text>
          </g>
        );
      })}

      {/* Spoke lines + angle labels */}
      {ANGLE_STEPS.map((angle) => {
        const theta = (180 - angle) * DEG;
        const x2 = cx + maxRadius * Math.cos(theta);
        const y2 = cy - maxRadius * Math.sin(theta);
        const lx = cx + (maxRadius + 18) * Math.cos(theta);
        const ly = cy - (maxRadius + 18) * Math.sin(theta);
        return (
          <g key={angle}>
            <line
              x1={cx}
              y1={cy}
              x2={x2}
              y2={y2}
              stroke="#6b7280"
              strokeWidth={0.5}
              strokeDasharray="3,3"
            />
            <text
              x={lx}
              y={ly + 4}
              fontSize={10}
              fill="#9ca3af"
              textAnchor="middle"
            >
              {angle === 0 ? "0° Nose" : angle === 90 ? "90° Side" : angle === 180 ? "180° Aft" : `${angle}°`}
            </text>
          </g>
        );
      })}

      {/* Baseline */}
      <line
        x1={cx - maxRadius}
        y1={cy}
        x2={cx + maxRadius}
        y2={cy}
        stroke="#6b7280"
        strokeWidth={1}
      />

      {/* Origin dot */}
      <circle cx={cx} cy={cy} r={3} fill="#6b7280" />
      <text x={cx + 4} y={cy + 14} fontSize={9} fill="#9ca3af">
        0 dB
      </text>
    </g>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface LOSPolarPlotProps {
  data: LOSData;
  width?: number;
  height?: number;
  /** Which frequency indices to show (default: all) */
  visibleFreqs?: number[];
  /** Show UQ band (default: true) */
  showUQ?: boolean;
}

export function LOSPolarPlot({
  data,
  width = 640,
  height = 380,
  visibleFreqs,
  showUQ = true,
}: LOSPolarPlotProps) {
  const cx = width / 2;
  const cy = height - 60;
  const maxRadius = Math.min(cx - 60, cy - 40);

  // Choose a sensible max dB for the chart scale
  const allDb = data.frequencies.flatMap((f) =>
    f.aspect_scan.map((p) => p.attenuation_db)
  );
  const rawMax = Math.max(...allDb, data.uq_band?.aspect_scan_p95?.[0]?.attenuation_db ?? 0);
  const maxDb = rawMax <= 10 ? 10 : rawMax <= 25 ? 25 : rawMax <= 50 ? 50 : 60;

  const visible = useMemo(
    () =>
      visibleFreqs
        ? data.frequencies.filter((_, i) => visibleFreqs.includes(i))
        : data.frequencies,
    [data, visibleFreqs]
  );

  // Build SVG path for each frequency line
  function freqPath(band: FrequencyBand): string {
    const pts = band.aspect_scan.map((p) =>
      polarToXY(p.angle_deg, p.attenuation_db, cx, cy, maxRadius, maxDb)
    );
    return linePath(pts);
  }

  // UQ filled band (P05 → P95 → reversed P05)
  const uqPath = useMemo(() => {
    if (!showUQ || !data.uq_band) return null;
    const p05 = data.uq_band.aspect_scan_p05;
    const p95 = data.uq_band.aspect_scan_p95;
    const top = p95.map((p) =>
      polarToXY(p.angle_deg, p.attenuation_db, cx, cy, maxRadius, maxDb)
    );
    const bottom = [...p05]
      .reverse()
      .map((p) =>
        polarToXY(p.angle_deg, p.attenuation_db, cx, cy, maxRadius, maxDb)
      );
    return linePath([...top, ...bottom], true);
  }, [data.uq_band, cx, cy, maxRadius, maxDb, showUQ]);

  const { meta } = data;

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      {/* Header */}
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            LOS Radar Attenuation — Polar
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {meta.vehicle} · Mach {meta.mach} · {meta.altitude_km} km ·{" "}
            {meta.engine}
          </p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>
            n<sub>e,stag</sub> = {meta.stagnation.ne_m3.toExponential(1)} m⁻³
          </div>
          <div>
            f<sub>p</sub> = {meta.stagnation.fp_GHz.toFixed(1)} GHz
          </div>
        </div>
      </div>

      {/* SVG chart */}
      <svg
        width={width}
        height={height}
        className="overflow-visible"
        style={{ maxWidth: "100%" }}
      >
        <PolarGrid cx={cx} cy={cy} maxRadius={maxRadius} maxDb={maxDb} />

        {/* UQ shaded band (behind frequency lines) */}
        {uqPath && (
          <path
            d={uqPath}
            fill="#a855f7"
            fillOpacity={0.12}
            stroke="#a855f7"
            strokeOpacity={0.3}
            strokeWidth={0.5}
            strokeDasharray="3,2"
          />
        )}

        {/* Frequency lines */}
        {visible.map((band) => (
          <path
            key={band.label}
            data-testid="freq-line"
            data-band-label={band.label}
            d={freqPath(band)}
            fill="none"
            stroke={band.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* Dots at each data point */}
        {visible.map((band) =>
          band.aspect_scan.map((p) => {
            const [x, y] = polarToXY(
              p.angle_deg,
              p.attenuation_db,
              cx,
              cy,
              maxRadius,
              maxDb
            );
            return (
              <circle
                key={`${band.label}-${p.angle_deg}`}
                cx={x}
                cy={y}
                r={3}
                fill={band.color}
                opacity={0.85}
              />
            );
          })
        )}

        {/* Title annotations */}
        <text x={cx} y={16} textAnchor="middle" fontSize={11} fill="#9ca3af">
          ← More attenuated (toward nose) · Less attenuated (toward aft) →
        </text>
      </svg>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
        {data.frequencies.map((band) => (
          <div key={band.label} className="flex items-center gap-1.5">
            <div
              className="h-0.5 w-6 rounded-full"
              style={{ backgroundColor: band.color }}
            />
            <span className="text-xs text-muted-foreground">{band.label}</span>
          </div>
        ))}
        {showUQ && data.uq_band && (
          <div className="flex items-center gap-1.5">
            <div className="h-3 w-6 rounded-sm bg-purple-500/20 border border-purple-500/30" />
            <span className="text-xs text-muted-foreground">
              {data.uq_band.label} UQ
            </span>
          </div>
        )}
      </div>

      {/* Status zone legend */}
      <div className="mt-2 flex gap-4">
        {Object.entries(STATUS_COLORS).map(([status, color]) => (
          <div key={status} className="flex items-center gap-1.5">
            <div
              className="h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: color, opacity: 0.7 }}
            />
            <span className="text-xs text-muted-foreground">{status}</span>
          </div>
        ))}
        <span className="text-xs text-muted-foreground ml-2">
          (&lt;2 dB · 2–20 dB · &gt;20 dB)
        </span>
      </div>
    </div>
  );
}
