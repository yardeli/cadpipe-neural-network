/**
 * GeometryUpload — drag-and-drop STEP/STL ingestion + preset fallback.
 *
 * The user can either pick one of the canonical sphere-cone presets or
 * drop their own STEP/STL/SU2 file. When a file is dropped, the backend
 * /api/plasma/parse_geometry endpoint extracts the bounding box and
 * derives nose-radius/half-angle/length estimates. While that endpoint
 * is being wired up, we accept the file but fall back to letting the
 * user pick the closest preset; the filename is shown so they know it
 * was received.
 */
import { useRef, useState } from "react";
import { GEOMETRY_PRESETS, type GeometryPreset } from "@/components/FlightSelectors";

interface Props {
  geometry: GeometryPreset;
  onGeometryChange: (g: GeometryPreset) => void;
}

export function GeometryUpload({ geometry, onGeometryChange }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [parseStatus, setParseStatus] = useState<{
    status: "ok" | "fallback" | "error";
    message: string;
  } | null>(null);

  function handleFile(file: File) {
    setFilename(file.name);
    setParseStatus({
      status: "fallback",
      message:
        "STEP/STL parser not yet wired to backend — pick the closest preset below for now.",
    });
    // TODO: when /api/plasma/parse_geometry is live, POST the file and
    // auto-set geometry from the extracted bbox.
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">1. Vehicle geometry</h3>
        <span className="text-xs text-muted-foreground">
          R<sub>n</sub> = {(geometry.nose_radius_m * 1000).toFixed(1)} mm
          &nbsp;·&nbsp; half = {geometry.half_angle_deg}°
          &nbsp;·&nbsp; L = {geometry.length_m.toFixed(2)} m
        </span>
      </div>

      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) handleFile(f);
        }}
        className={
          "cursor-pointer rounded-md border-2 border-dashed p-4 text-center transition-colors " +
          (isDragging
            ? "border-emerald-500 bg-emerald-950/20"
            : "border-border hover:border-muted-foreground")
        }
        role="button"
        aria-label="Drop geometry file or click to browse"
      >
        <div className="text-sm">
          {filename ? (
            <>
              <strong className="text-emerald-400">✓ {filename}</strong>
            </>
          ) : (
            <>
              <strong>Drop geometry file</strong> or click to browse
            </>
          )}
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          STEP · STL · SU2 (preset fallback below)
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".step,.stp,.stl,.su2,.msh"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) handleFile(f);
          }}
        />
      </div>

      {parseStatus && (
        <div
          className={
            "rounded p-2 text-xs " +
            (parseStatus.status === "ok"
              ? "border border-emerald-900 bg-emerald-950/30 text-emerald-300"
              : parseStatus.status === "error"
                ? "border border-red-900 bg-red-950/30 text-red-300"
                : "border border-amber-900 bg-amber-950/20 text-amber-300")
          }
        >
          {parseStatus.message}
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-medium text-muted-foreground">
          Or pick a preset:
        </div>
        <div className="grid grid-cols-3 gap-2">
          {GEOMETRY_PRESETS.map((g) => {
            const selected = g.name === geometry.name;
            return (
              <button
                key={g.name}
                onClick={() => {
                  onGeometryChange(g);
                  setParseStatus(null);
                  setFilename(null);
                }}
                className={
                  "rounded border px-2 py-2 text-left text-xs transition-colors " +
                  (selected
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background hover:bg-muted")
                }
              >
                <div className="font-medium">{g.label}</div>
                <div
                  className={
                    "mt-0.5 text-[10px] " +
                    (selected ? "opacity-80" : "text-muted-foreground")
                  }
                >
                  R<sub>n</sub>={(g.nose_radius_m * 1000).toFixed(0)}mm,{" "}
                  {g.half_angle_deg}°
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
