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
  // Clamp r to [0, maxRadius]: at hypersonic conditions attenuation can
  // exceed maxDb by orders of magnitude (e.g. 5000 dB at M22.5/47km VHF).
  // Without the clamp, r goes negative and points wrap to the opposite
  // side of the chart — produced the zig-zag rendering bug.
  const rRaw = ((maxDb - attenuationDb) / maxDb) * maxRadius;
  const r = Math.max(0, Math.min(maxRadius, rRaw));
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

/**
 * Smooth path using Catmull-Rom converted to cubic Bézier.
 *
 * Each segment between consecutive points is rendered as a cubic Bézier
 * curve whose control points are derived from the neighboring points'
 * tangent. This produces visually smooth curves even when the underlying
 * data has minor noise / sampling artifacts — the curve passes exactly
 * through every input point but the line between them is shaped like a
 * natural spline rather than a straight segment.
 *
 * Tension parameter (0=Catmull-Rom uniform, 0.5=centripetal-ish) controls
 * overshoot. We use 0.5 — gentle smoothing without large excursions.
 */
function smoothPath(
  points: Array<[number, number]>,
  closePath = false
): string {
  if (points.length === 0) return "";
  if (points.length === 1) {
    const [x, y] = points[0];
    return `M ${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  if (points.length === 2) {
    return linePath(points, closePath);
  }
  const tension = 0.5;
  const path: string[] = [];
  const [x0, y0] = points[0];
  path.push(`M ${x0.toFixed(1)} ${y0.toFixed(1)}`);
  for (let i = 0; i < points.length - 1; i++) {
    const [px, py] = points[Math.max(i - 1, 0)];
    const [cx, cy] = points[i];
    const [nx, ny] = points[i + 1];
    const [n2x, n2y] = points[Math.min(i + 2, points.length - 1)];
    const cp1x = cx + ((nx - px) / 6) * tension * 2;
    const cp1y = cy + ((ny - py) / 6) * tension * 2;
    const cp2x = nx - ((n2x - cx) / 6) * tension * 2;
    const cp2y = ny - ((n2y - cy) / 6) * tension * 2;
    path.push(
      `C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${nx.toFixed(1)} ${ny.toFixed(1)}`
    );
  }
  return closePath ? path.join(" ") + " Z" : path.join(" ");
}

// ── Constants ─────────────────────────────────────────────────────────────────

const DETECTABLE_THRESHOLD = 2;   // dB — below this = DETECTABLE
const DEGRADED_THRESHOLD = 20;    // dB — above this = BLACKOUT
const ANGLE_STEPS = [0, 30, 60, 90, 120, 150, 180];
// Picked at runtime based on maxDb — keeps DETECTABLE/DEGRADED/BLACKOUT
// transitions visible across all scaling tiers.
const DB_RINGS_BY_TIER: Record<number, number[]> = {
  10:  [2, 5, 10],
  25:  [2, 5, 10, 20],
  50:  [2, 10, 20, 40],
  100: [2, 20, 50, 100],
  250: [20, 50, 100, 250],
  500: [20, 100, 250, 500],
};
const DB_RINGS_FALLBACK = [5, 10, 20, 40];

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
  const rings = (DB_RINGS_BY_TIER[maxDb] ?? DB_RINGS_FALLBACK).filter(
    (r) => r <= maxDb
  );

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

  // Choose a sensible max dB for the chart scale.
  // Tiers extend beyond 60 dB because hypersonic blackout produces
  // 100-5000 dB at VHF/X. When the data exceeds the largest tier, points
  // saturate at chart center (clamped by polarToXY) and we annotate with
  // a "saturated" badge below.
  const allDb = data.frequencies.flatMap((f) =>
    f.aspect_scan.map((p) => p.attenuation_db)
  );
  const rawMax = Math.max(...allDb, data.uq_band?.aspect_scan_p95?.[0]?.attenuation_db ?? 0);
  const maxDb =
    rawMax <= 10 ? 10 :
    rawMax <= 25 ? 25 :
    rawMax <= 50 ? 50 :
    rawMax <= 100 ? 100 :
    rawMax <= 250 ? 250 :
    500;
  const isSaturated = rawMax > maxDb;

  const visible = useMemo(
    () =>
      visibleFreqs
        ? data.frequencies.filter((_, i) => visibleFreqs.includes(i))
        : data.frequencies,
    [data, visibleFreqs]
  );

  // Build SVG path for each frequency line.
  //
  // Strategy: split the data into contiguous "in-band" runs (skipping
  // saturated >= maxDb and near-zero <= MIN_VISIBLE_DB points), then
  // render each run as a single Catmull-Rom-to-Bézier smooth curve.
  // The Bézier is shaped by the four-point neighborhood at each segment,
  // so the curve naturally smooths out minor data noise (e.g. the
  // 30-dB dips that appear when the LOS sampler grazes the sheath
  // boundary at oblique angles) without overshooting the data points.
  //
  // Saturated/near-zero points break the curve — connecting them to
  // interior points produces long diagonals from rim to center that don't
  // reflect the underlying physics (those angles are "off the scale" or
  // "no LOS through plasma" respectively).
  const MIN_VISIBLE_DB = 0.1;

  function isOffScale(atten: number): boolean {
    return atten >= maxDb || atten < MIN_VISIBLE_DB;
  }

  function freqPath(band: FrequencyBand): string {
    const sortedScan = [...band.aspect_scan].sort(
      (a, b) => a.angle_deg - b.angle_deg
    );
    const segments: string[] = [];
    let run: Array<[number, number]> = [];

    function flushRun() {
      if (run.length >= 2) {
        segments.push(smoothPath(run));
      }
      run = [];
    }

    for (const p of sortedScan) {
      if (isOffScale(p.attenuation_db)) {
        flushRun();
        continue;
      }
      run.push(polarToXY(p.angle_deg, p.attenuation_db, cx, cy, maxRadius, maxDb));
    }
    flushRun();
    return segments.join(" ");
  }

  // UQ filled band (P05 → P95 → reversed P05). Renders as a closed
  // shape — top edge is the P95 curve, bottom edge is the P05 curve
  // traversed in reverse. Both edges use the same Catmull-Rom smoothing
  // so the band has consistent curvature with the frequency lines.
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
    return smoothPath([...top, ...bottom], true);
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
          {isSaturated && (
            <p
              className="mt-1 text-[10px] text-red-400 font-medium"
              title={`Peak attenuation ${rawMax.toExponential(2)} dB exceeds chart cap of ${maxDb} dB; saturated bands shown clamped at chart center.`}
            >
              ⚠ saturated — peak {rawMax.toFixed(0)} dB &gt; chart max {maxDb} dB
            </p>
          )}
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
        role="img"
        aria-label={
          `Line-of-sight radar attenuation polar plot. ` +
          `${visible.length} of ${data.frequencies.length} frequency bands shown ` +
          `between 0 and 180 degrees aspect angle. ` +
          `Stagnation electron density ${meta.stagnation.ne_m3.toExponential(1)} m^-3, ` +
          `plasma frequency ${meta.stagnation.fp_GHz.toFixed(1)} GHz.`
        }
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

        {/* Dots at each in-chart data point.
            Saturated points (atten >= maxDb) are skipped here — instead
            we render a single small "saturated" marker per band at the
            center (below) to avoid 13 stacked dots looking like a blob. */}
        {visible.map((band) =>
          band.aspect_scan
            .filter((p) => p.attenuation_db < maxDb)
            .map((p) => {
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

        {/* Saturated-cluster marker per band — shows up as a small
            filled square at center, slightly offset per band so multiple
            saturated bands don't perfectly overlap. */}
        {visible.map((band, i) => {
          const satCount = band.aspect_scan.filter(
            (p) => p.attenuation_db >= maxDb
          ).length;
          if (satCount === 0) return null;
          // Tiny per-band offset so 4-band saturation shows 4 markers,
          // not one 4-stack hidden under itself.
          const dx = (i - 1.5) * 6;
          const dy = -2;
          return (
            <g key={`sat-${band.label}`}>
              <rect
                x={cx + dx - 4}
                y={cy + dy - 4}
                width={8}
                height={8}
                fill={band.color}
                opacity={0.85}
                stroke="#fff"
                strokeOpacity={0.4}
                strokeWidth={0.5}
              >
                <title>
                  {band.label}: {satCount}/{band.aspect_scan.length} aspects
                  saturated (&gt;{maxDb} dB)
                </title>
              </rect>
            </g>
          );
        })}

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
