/**
 * FlightSelectors — Mach + altitude pill rows that drive the analyze_scan
 * fetch in App.tsx.
 *
 * The option set is fixed to the four RAM-C II reflectometer trajectory
 * points (Jones & Cross 1972). Defaults at the call site should pick the
 * J&C primary validation point (M22.5 / 61 km).
 */

// RAM-C II Jones & Cross 1972 instrumentation grid — same numbers used by
// the /report PDF's CANONICAL_RAMC_POINTS.
export const ALTITUDE_OPTIONS_KM = [47, 61, 71, 81] as const;
export const MACH_OPTIONS = [18.5, 22.5, 23.6, 23.9] as const;

export type AltitudeKm = (typeof ALTITUDE_OPTIONS_KM)[number];
export type MachOption = (typeof MACH_OPTIONS)[number];

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
