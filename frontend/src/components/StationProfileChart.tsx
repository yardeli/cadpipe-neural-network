/**
 * StationProfileChart — log-y line plot of ne vs reflectometer station.
 *
 * Renders the 5-station axial profile from the SU2-NEMO post-processor:
 *   x-axis: zL (axial position normalized by vehicle length, 0..1)
 *   y-axis: max_ne_m3 (log scale, m⁻³)
 *
 * Same custom-SVG approach as LOSPolarPlot — no chart library needed.
 */
import { useMemo } from "react";
import type { StationEntry } from "@/types/los";

interface Props {
  stations: StationEntry[];
  width?: number;
  height?: number;
}

// Plot bounds on the data axes.
const X_MIN = 0;
const X_MAX = 1;
// Log10(ne) range — covers the full 12-decade span we ever see, from
// pre-shock background (~1e6) up to peak sheath density (~1e21).
const LOG_NE_MIN = 14;   // 1e14 m⁻³
const LOG_NE_MAX = 22;   // 1e22 m⁻³

// SVG inner padding (leaves room for axis labels).
const PAD_L = 56;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 36;

export function StationProfileChart({
  stations,
  width = 620,
  height = 240,
}: Props) {
  const innerW = width - PAD_L - PAD_R;
  const innerH = height - PAD_T - PAD_B;

  const xToPx = (zL: number) =>
    PAD_L + ((zL - X_MIN) / (X_MAX - X_MIN)) * innerW;
  const logNeToPx = (logNe: number) =>
    PAD_T + (1 - (logNe - LOG_NE_MIN) / (LOG_NE_MAX - LOG_NE_MIN)) * innerH;

  // Polyline points for max_ne — clamp ne <= 1 to a floor so log is finite.
  const pointsMax = useMemo(
    () =>
      stations
        .map((s) => {
          const ne = Math.max(s.max_ne_m3, 1);
          return `${xToPx(s.zL)},${logNeToPx(Math.log10(ne))}`;
        })
        .join(" "),
    [stations, innerW, innerH]   // eslint-disable-line react-hooks/exhaustive-deps
  );

  const pointsP99 = useMemo(
    () =>
      stations
        .map((s) => {
          const ne = Math.max(s.p99_ne_m3, 1);
          return `${xToPx(s.zL)},${logNeToPx(Math.log10(ne))}`;
        })
        .join(" "),
    [stations, innerW, innerH]   // eslint-disable-line react-hooks/exhaustive-deps
  );

  // Y-axis decade gridlines.
  const yTicks: number[] = [];
  for (let logNe = LOG_NE_MIN; logNe <= LOG_NE_MAX; logNe += 2) yTicks.push(logNe);

  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="mb-2 text-xs font-medium text-muted-foreground">
        Reflectometer station profile — n
        <sub>e</sub> (max + p99) along the body
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        role="img"
        aria-label="Electron density vs axial station"
      >
        {/* Y gridlines + labels (log decades) */}
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

        {/* X-axis baseline + station tick labels */}
        <line
          x1={PAD_L}
          x2={width - PAD_R}
          y1={height - PAD_B}
          y2={height - PAD_B}
          stroke="currentColor"
          strokeOpacity={0.25}
        />
        {stations.map((s) => (
          <g key={s.zL}>
            <line
              x1={xToPx(s.zL)}
              x2={xToPx(s.zL)}
              y1={height - PAD_B}
              y2={height - PAD_B + 4}
              stroke="currentColor"
              strokeOpacity={0.4}
            />
            <text
              x={xToPx(s.zL)}
              y={height - PAD_B + 18}
              textAnchor="middle"
              className="fill-muted-foreground"
              style={{ fontSize: 10 }}
            >
              {s.zL.toFixed(2)}
            </text>
          </g>
        ))}

        {/* p99 line (lighter) */}
        <polyline
          points={pointsP99}
          fill="none"
          stroke="#3b82f6"
          strokeOpacity={0.45}
          strokeWidth={1.5}
          strokeDasharray="4 3"
        />

        {/* max line (primary) */}
        <polyline
          points={pointsMax}
          fill="none"
          stroke="#3b82f6"
          strokeWidth={2}
        />
        {stations.map((s) => {
          const ne = Math.max(s.max_ne_m3, 1);
          return (
            <circle
              key={`pt-${s.zL}`}
              cx={xToPx(s.zL)}
              cy={logNeToPx(Math.log10(ne))}
              r={3}
              fill="#3b82f6"
            />
          );
        })}

        {/* Axis titles */}
        <text
          x={PAD_L + innerW / 2}
          y={height - 4}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: 11 }}
        >
          axial station z / L
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
        <g transform={`translate(${width - PAD_R - 130}, ${PAD_T + 2})`}>
          <line x1={0} x2={18} y1={4} y2={4} stroke="#3b82f6" strokeWidth={2} />
          <text x={22} y={4} dominantBaseline="middle"
                className="fill-muted-foreground" style={{ fontSize: 10 }}>
            max nₑ
          </text>
          <line
            x1={0} x2={18} y1={18} y2={18}
            stroke="#3b82f6" strokeWidth={1.5} strokeOpacity={0.45}
            strokeDasharray="4 3"
          />
          <text x={22} y={18} dominantBaseline="middle"
                className="fill-muted-foreground" style={{ fontSize: 10 }}>
            p99 nₑ
          </text>
        </g>
      </svg>
    </div>
  );
}
