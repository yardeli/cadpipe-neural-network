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

// Pill-row options. Bigger range than the RAM-C trajectory anchors so
// the user can sweep Mach 5-25 and altitude 25-90 km, not just the four
// J&C 1972 reflectometer points. RAM-C anchors are still in the list
// (marked by being identical to a TrajectoryPoint mach/alt) so the
// /benchmark page's per-point analysis still hits exact matches.
export const MACH_OPTIONS: number[] = [
  5, 8, 10, 12, 15, 18.5, 22.5, 23.6, 23.9, 25,
];

export const ALTITUDE_OPTIONS_KM: number[] = [
  30, 40, 47, 55, 61, 71, 81, 90,
];

// RAM-C anchor altitudes/Machs — used by the /benchmark page to
// auto-fetch the canonical comparison.
export const RAM_C_TRAJECTORY_POINTS: TrajectoryPoint[] = POINTS;

// Vehicle geometry presets — sphere-cone parameters from
// data/cfd_cases/*/<name>.json. nose_radius_m + half_angle_deg + length_m
// are the three dimensions VehicleGeometry on the backend takes; the rest
// of the JSON files (r_base_m, bbox) are derived. Range deliberately
// spans 15x in nose radius (sharp_narrow 0.02 m -> capsule 0.30 m) to
// expose any geometry sensitivity in the LOS attenuation.
export interface GeometryPreset {
  name: string;
  label: string;
  nose_radius_m: number;
  half_angle_deg: number;
  length_m: number;
}

export const GEOMETRY_PRESETS: GeometryPreset[] = [
  { name: "ram_c",        label: "RAM-C",        nose_radius_m: 0.1524, half_angle_deg: 9.0,  length_m: 1.295 },
  { name: "sharp_narrow", label: "Sharp narrow", nose_radius_m: 0.02,   half_angle_deg: 7.0,  length_m: 0.50 },
  { name: "medium_cone",  label: "Medium cone",  nose_radius_m: 0.05,   half_angle_deg: 15.0, length_m: 0.50 },
  { name: "blunt_cone",   label: "Blunt cone",   nose_radius_m: 0.08,   half_angle_deg: 15.0, length_m: 0.50 },
  { name: "blunt_wide",   label: "Blunt wide",   nose_radius_m: 0.15,   half_angle_deg: 25.0, length_m: 0.60 },
  { name: "capsule",      label: "Capsule",      nose_radius_m: 0.30,   half_angle_deg: 30.0, length_m: 0.80 },
];

interface Props {
  mach: number;
  alt: number;
  geometryName?: string;
  onMachChange: (mach: number) => void;
  onAltChange: (alt: number) => void;
  onGeometryChange?: (geometry: GeometryPreset) => void;
}

export function FlightSelectors({
  mach,
  alt,
  geometryName,
  onMachChange,
  onAltChange,
  onGeometryChange,
}: Props) {
  return (
    <div
      data-testid="flight-selectors"
      className="flex flex-wrap gap-4 rounded-lg border border-border bg-card p-3"
    >
      {onGeometryChange && (
        <StringSelectorRow
          label="Vehicle"
          value={geometryName ?? "ram_c"}
          options={GEOMETRY_PRESETS.map((g) => ({ value: g.name, label: g.label }))}
          onChange={(name) => {
            const preset = GEOMETRY_PRESETS.find((g) => g.name === name);
            if (preset) onGeometryChange(preset);
          }}
        />
      )}
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

interface StringSelectorOption {
  value: string;
  label: string;
}

interface StringSelectorRowProps {
  label: string;
  value: string;
  options: StringSelectorOption[];
  onChange: (v: string) => void;
}

function StringSelectorRow({
  label,
  value,
  options,
  onChange,
}: StringSelectorRowProps) {
  return (
    <div className="flex items-center gap-2" role="radiogroup" aria-label={label}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex gap-1">
        {options.map((opt) => {
          const selected = opt.value === value;
          return (
            <button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(opt.value)}
              className={[
                "rounded px-2 py-1 text-xs font-medium transition-colors",
                selected
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              ].join(" ")}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
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
