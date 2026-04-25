/**
 * BenchmarkChart — log-y line plot of predicted vs reference n_e by altitude.
 *
 * Matches StationProfileChart's custom-SVG pattern (no chart library). One
 * point per unique altitude — for each altitude, predicted and reference
 * ne are plotted on a log y-axis spanning 1e16–1e22 m^-3.
 */
import { useMemo } from "react";
import type { RamCCase } from "@/types/los";

interface Props {
  cases: RamCCase[];
  width?: number;
  height?: number;
}

const Y_MIN_LOG = 16;
const Y_MAX_LOG = 22;
const X_PAD_KM = 4;

const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 36;

export function BenchmarkChart({ cases, width = 620, height = 240 }: Props) {
  const innerW = width - PAD_L - PAD_R;
  const innerH = height - PAD_T - PAD_B;

  // Collapse the (alt, mach, freq) cases to one point per altitude — the
  // ne_predicted/ne_reference values are altitude-keyed in our backend, so
  // any case at a given altitude carries the same ne values.
  const points = useMemo(() => {
    const byAlt = new Map<number, RamCCase>();
    for (const c of cases) {
      if (!byAlt.has(c.altitude_km)) byAlt.set(c.altitude_km, c);
    }
    return Array.from(byAlt.values()).sort(
      (a, b) => a.altitude_km - b.altitude_km
    );
  }, [cases]);

  const altMin = points.length
    ? Math.min(...points.map((p) => p.altitude_km)) - X_PAD_KM
    : 40;
  const altMax = points.length
    ? Math.max(...points.map((p) => p.altitude_km)) + X_PAD_KM
    : 90;

  const xToPx = (km: number) =>
    PAD_L + ((km - altMin) / (altMax - altMin)) * innerW;
  const logNeToPx = (logNe: number) =>
    PAD_T + (1 - (logNe - Y_MIN_LOG) / (Y_MAX_LOG - Y_MIN_LOG)) * innerH;

  const predPath = points
    .map((p) => `${xToPx(p.altitude_km)},${logNeToPx(Math.log10(Math.max(p.ne_predicted_m3, 1)))}`)
    .join(" ");
  const refPath = points
    .map((p) => `${xToPx(p.altitude_km)},${logNeToPx(Math.log10(Math.max(p.ne_reference_m3, 1)))}`)
    .join(" ");

  const yTicks: number[] = [];
  for (let logNe = Y_MIN_LOG; logNe <= Y_MAX_LOG; logNe += 2) yTicks.push(logNe);

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-2 text-xs font-medium text-muted-foreground">
        Predicted vs Jones &amp; Cross 1972 reference n
        <sub>e</sub> by altitude
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label={
          `Benchmark trajectory plot. Predicted vs published n_e at ${points.length} altitudes` +
          ` (${points.map((p) => p.altitude_km + " km").join(", ")}).`
        }
      >
        {/* Y gridlines + decade labels */}
        {yTicks.map((logNe) => {
          const y = logNeToPx(logNe);
          return (
            <g key={logNe}>
              <line
                x1={PAD_L}
                x2={width - PAD_R}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={0.08}
              />
              <text
                x={PAD_L - 6}
                y={y}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-muted-foreground"
                style={{ fontSize: 10 }}
              >
                10
                <tspan baselineShift="super" fontSize={7}>
                  {logNe}
                </tspan>
              </text>
            </g>
          );
        })}

        {/* X-axis baseline + altitude tick labels */}
        <line
          x1={PAD_L}
          x2={width - PAD_R}
          y1={height - PAD_B}
          y2={height - PAD_B}
          stroke="currentColor"
          strokeOpacity={0.25}
        />
        {points.map((p) => (
          <g key={p.altitude_km}>
            <line
              x1={xToPx(p.altitude_km)}
              x2={xToPx(p.altitude_km)}
              y1={height - PAD_B}
              y2={height - PAD_B + 4}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <text
              x={xToPx(p.altitude_km)}
              y={height - PAD_B + 18}
              textAnchor="middle"
              className="fill-muted-foreground"
              style={{ fontSize: 10 }}
            >
              {p.altitude_km}
            </text>
          </g>
        ))}

        {/* Reference line (dashed) */}
        <polyline
          points={refPath}
          fill="none"
          stroke="#64748b"
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />
        {points.map((p) => (
          <circle
            key={`ref-${p.altitude_km}`}
            cx={xToPx(p.altitude_km)}
            cy={logNeToPx(Math.log10(Math.max(p.ne_reference_m3, 1)))}
            r={3}
            fill="#64748b"
          />
        ))}

        {/* Predicted line (color-tinted by pass/fail) */}
        <polyline
          points={predPath}
          fill="none"
          stroke="#3b82f6"
          strokeWidth={2}
        />
        {points.map((p) => (
          <circle
            key={`pred-${p.altitude_km}`}
            cx={xToPx(p.altitude_km)}
            cy={logNeToPx(Math.log10(Math.max(p.ne_predicted_m3, 1)))}
            r={4}
            fill={p.within_uncertainty ? "#10b981" : "#ef4444"}
            stroke="#fff"
            strokeWidth={1}
          />
        ))}

        {/* Axis titles */}
        <text
          x={PAD_L + innerW / 2}
          y={height - 4}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: 11 }}
        >
          altitude (km)
        </text>
        <text
          x={14}
          y={PAD_T + innerH / 2}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: 11 }}
          transform={`rotate(-90 14 ${PAD_T + innerH / 2})`}
        >
          n_e (m⁻³, log)
        </text>

        {/* Legend */}
        <g transform={`translate(${width - PAD_R - 160}, ${PAD_T + 2})`}>
          <line x1={0} x2={18} y1={4} y2={4} stroke="#3b82f6" strokeWidth={2} />
          <text x={22} y={4} dominantBaseline="middle"
                className="fill-muted-foreground" style={{ fontSize: 10 }}>
            predicted
          </text>
          <line
            x1={0} x2={18} y1={18} y2={18}
            stroke="#64748b" strokeWidth={1.5} strokeDasharray="4 3"
          />
          <text x={22} y={18} dominantBaseline="middle"
                className="fill-muted-foreground" style={{ fontSize: 10 }}>
            J&amp;C 1972 reference
          </text>
        </g>
      </svg>
    </div>
  );
}
