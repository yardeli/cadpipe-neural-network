/**
 * ResultsCard — consolidated post-analysis report.
 *
 * Inspired by cadpipe's /plasma report panel: the user runs the analysis
 * once and gets a single dense card showing the headline numbers
 * (stagnation T/p/ne, plasma frequency, per-band detection verdicts,
 * caveat notes). Replaces the previous "raw chart only" UX where the
 * user had to read meta.stagnation off the polar chart's small print.
 */
import type { LOSData } from "@/types/los";

interface Props {
  data: LOSData;
}

const BLACKOUT_THRESHOLD_DB = 20;
const DETECT_THRESHOLD_DB = 2;

export function ResultsCard({ data }: Props) {
  const stag = data.meta.stagnation;
  const blackoutThresholdNe = 1.787e18; // 12 GHz Ku-band cutoff

  const ratio_to_published = (() => {
    // RAM-C only — and only at the four anchor altitudes
    const refByAlt: Record<number, number> = {
      47: 2.0e19, 61: 2.0e19, 71: 1.0e19, 81: 2.0e18,
    };
    const ref = refByAlt[Math.round(data.meta.altitude_km)];
    if (!ref || data.meta.vehicle !== "ram_c") return null;
    return stag.ne_m3 / ref;
  })();

  // Worst-case attenuation per band, taken across all aspect angles
  const bandSummary = data.frequencies.map((f) => {
    const peak = f.aspect_scan.reduce(
      (acc, p) => (p.attenuation_db > acc.atten ? { atten: p.attenuation_db, angle: p.angle_deg } : acc),
      { atten: 0, angle: 0 }
    );
    let status: "DETECTABLE" | "DEGRADED" | "BLACKOUT";
    if (peak.atten >= BLACKOUT_THRESHOLD_DB) status = "BLACKOUT";
    else if (peak.atten >= DETECT_THRESHOLD_DB) status = "DEGRADED";
    else status = "DETECTABLE";
    return { ...f, peak, status };
  });

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">3. Results</h3>
        <span className="text-xs text-muted-foreground">
          Engine: <code className="rounded bg-muted px-1">{data.meta.engine}</code>
        </span>
      </div>

      {/* Top-line stagnation metrics */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric
          label="Stagnation T"
          value={stag.T_tr_K.toFixed(0)}
          unit="K"
          tone={stag.T_tr_K > 4000 ? "high" : "normal"}
        />
        <Metric
          label="Stagnation p"
          value={stag.p_Pa.toExponential(2)}
          unit="Pa"
        />
        <Metric
          label="Peak nₑ"
          value={stag.ne_m3.toExponential(2)}
          unit="m⁻³"
          tone={stag.ne_m3 > blackoutThresholdNe ? "high" : "normal"}
        />
        <Metric
          label="Plasma freq fₚ"
          value={stag.fp_GHz.toFixed(1)}
          unit="GHz"
          tone={stag.fp_GHz > 12 ? "high" : "normal"}
        />
      </div>

      {ratio_to_published !== null && (
        <div className="rounded border border-border bg-background p-2 text-xs">
          <span className="text-muted-foreground">vs J&amp;C 1972 published peak:</span>{" "}
          <span className={
            ratio_to_published > 5 || ratio_to_published < 0.2
              ? "text-amber-300"
              : "text-emerald-300"
          }>
            ratio = {ratio_to_published.toFixed(2)}× ({ratio_to_published > 1 ? "over" : "under"}-prediction)
          </span>
          {(ratio_to_published > 5 || ratio_to_published < 0.2) && (
            <div className="mt-1 text-muted-foreground">
              Equilibrium chemistry assumption — actual flight residence
              time (~10 µs) is shorter than equilibration; expect 5-50× drift
              from measured value at high-Mach low-altitude conditions.
            </div>
          )}
        </div>
      )}

      {/* Per-band detection table */}
      <div>
        <div className="mb-1 text-xs font-medium text-muted-foreground">
          Per-band peak attenuation &amp; detection verdict
        </div>
        <table className="w-full text-left text-xs">
          <thead className="border-b border-border text-muted-foreground">
            <tr>
              <th className="py-1">Band</th>
              <th className="py-1 text-right">Peak (dB)</th>
              <th className="py-1 text-right">@ aspect</th>
              <th className="py-1 text-right">Status</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {bandSummary.map((b) => (
              <tr key={b.label} className="border-b border-border/40">
                <td className="py-1.5">
                  <span
                    className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
                    style={{ background: b.color }}
                  />
                  {b.label}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {b.peak.atten.toFixed(1)}
                </td>
                <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                  {b.peak.angle}°
                </td>
                <td className="py-1.5 text-right">
                  <StatusBadge status={b.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded border border-border bg-background p-2 text-[11px] text-muted-foreground space-y-1">
        <div>
          <strong className="text-foreground">Note:</strong> stagnation
          chemistry is geometry-independent under perfect-gas Pitot
          (depends only on M, T<sub>∞</sub>, P<sub>∞</sub>). Geometry
          affects the LOS attenuation via the bow-shock standoff
          (Billig 1967, R<sub>n</sub> × exp(3.24/M²) × ρ<sub>frozen</sub>/ρ<sub>eq</sub>)
          and the analytical sheath profile in the per-aspect attenuation curves below.
        </div>
        <div>
          ne ≥ {blackoutThresholdNe.toExponential(1)} m⁻³ corresponds to
          12 GHz Ku-band blackout (f<sub>p</sub> ≥ f).
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  unit,
  tone = "normal",
}: {
  label: string;
  value: string;
  unit: string;
  tone?: "normal" | "high";
}) {
  const valueClass = tone === "high" ? "text-amber-300" : "text-foreground";
  return (
    <div className="rounded border border-border bg-background p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={`mt-0.5 font-mono text-sm tabular-nums ${valueClass}`}>
        {value}{" "}
        <span className="text-[10px] text-muted-foreground">{unit}</span>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: "DETECTABLE" | "DEGRADED" | "BLACKOUT" }) {
  const cls = {
    DETECTABLE: "bg-emerald-900/60 text-emerald-300",
    DEGRADED: "bg-amber-900/60 text-amber-300",
    BLACKOUT: "bg-red-900/60 text-red-300",
  }[status];
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>
      {status}
    </span>
  );
}
