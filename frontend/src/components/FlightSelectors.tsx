/**
 * FlightSelectors — Mach + altitude pill rows that drive the analyze_scan
 * fetch in App.tsx.
 *
 * Option grids are derived from frontend/src/data/ram_c_trajectory.json,
 * which is auto-generated from plasmanet/ram_c_trajectory.py by
 * scripts/sync_trajectory_json.py — single source of truth shared with
 * the PDF report and the benchmark route.
 */

import trajectoryData from "@/data/ram_c_trajectory.json";

export interface TrajectoryPoint {
  altitude_km: number;
  mach: number;
  ne_peak_m3_published: number;
  source: string;
}

const POINTS: TrajectoryPoint[] = trajectoryData.points;

// Distinct, ascending values — matches plasmanet.ram_c_trajectory.trajectory_*().
export const ALTITUDE_OPTIONS_KM: number[] = Array.from(
  new Set(POINTS.map((p) => p.altitude_km))
).sort((a, b) => a - b);

export const MACH_OPTIONS: number[] = Array.from(
  new Set(POINTS.map((p) => p.mach))
).sort((a, b) => a - b);

interface Props {
  mach: number;
  alt: number;
  onMachChange: (mach: number) => void;
  onAltChange: (alt: number) => void;
}

export function FlightSelectors({ mach, alt, onMachChange, onAltChange }: Props) {
  return (
    <div
      data-testid="flight-selectors"
      className="flex flex-wrap gap-4 rounded-lg border border-border bg-card p-3"
    >
      <SelectorRow
        label="Mach"
        value={mach}
        options={MACH_OPTIONS}
        format={(v) => v.toFixed(1)}
        onChange={onMachChange}
      />
      <SelectorRow
        label="Altitude"
        value={alt}
        options={ALTITUDE_OPTIONS_KM}
        format={(v) => `${v} km`}
        onChange={onAltChange}
      />
    </div>
  );
}

interface SelectorRowProps {
  label: string;
  value: number;
  options: number[];
  format: (v: number) => string;
  onChange: (v: number) => void;
}

function SelectorRow({
  label,
  value,
  options,
  format,
  onChange,
}: SelectorRowProps) {
  return (
    <div className="flex items-center gap-2" role="radiogroup" aria-label={label}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex gap-1">
        {options.map((opt) => {
          const selected = opt === value;
          return (
            <button
              key={opt}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(opt)}
              className={[
                "rounded px-2 py-1 text-xs font-medium transition-colors tabular-nums",
                selected
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              ].join(" ")}
            >
              {format(opt)}
            </button>
          );
        })}
      </div>
    </div>
  );
}
