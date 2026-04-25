// ── Request types (mirrors plasmanet/mock_server.py Pydantic models) ──────────

export interface VehicleGeometry {
  nose_radius_m: number;
  half_angle_deg: number;
  length_m: number;
  name: string;
}

export interface FlightCondition {
  mach: number;
  altitude_km: number;
  sideslip_angle_deg?: number;
}

export interface RadarParams {
  frequency_hz: number;
  aspect_angles_deg?: number[] | null;
}

export interface UQConfig {
  enabled: boolean;
  n_samples?: number;
}

export interface PlasmaAnalysisParams {
  gas_model?: string;
  radar_frequency_hz?: number;
  aspect_angles?: number[] | null;
  include_uq?: boolean;
}

export interface PlasmaAnalyzeRequest {
  vehicle: VehicleGeometry;
  flight: FlightCondition;
  radar: RadarParams;
  uncertainty: UQConfig;
}

export interface PlasmaSubmitCFDRequest {
  mesh_id: string;
  flight: FlightCondition;
  plasma: PlasmaAnalysisParams;
  solver?: string;
}

/** Convenience multi-band request for POST /api/plasma/analyze_scan */
export interface MultiFreqScanRequest {
  vehicle?: VehicleGeometry;
  flight: FlightCondition;
  aspect_angles_deg?: number[] | null;
  uncertainty?: UQConfig;
}

// ── Response types ────────────────────────────────────────────────────────────

export interface AspectPoint {
  angle_deg: number;
  attenuation_db: number;
  status?: "DETECTABLE" | "DEGRADED" | "BLACKOUT";
}

export interface FrequencyBand {
  label: string;
  frequency_mhz: number;
  color: string;
  aspect_scan: AspectPoint[];
}

export interface UQBand {
  frequency_mhz: number;
  label: string;
  aspect_scan_p05: Array<{ angle_deg: number; attenuation_db: number }>;
  aspect_scan_p95: Array<{ angle_deg: number; attenuation_db: number }>;
}

export interface StagnationState {
  T_tr_K: number;
  T_ve_K?: number;
  p_Pa: number;
  ne_m3: number;
  fp_GHz: number;
}

export interface UQSummary {
  ne_P05_m3: number;
  ne_P50_m3: number;
  ne_P95_m3: number;
  log10_ne_std: number;
}

export interface StationEntry {
  zL: number;             // axial position normalized by length, 0..1
  z_m: number;            // axial position in meters
  r_wall_m: number;       // wall radius at this station
  max_ne_m3: number;      // peak ne in this axial band
  p99_ne_m3: number;      // 99th-percentile ne (less spiky than max)
  max_T_tr_K: number;     // peak translational temperature
}

export interface LOSMeta {
  mach: number;
  altitude_km: number;
  nose_radius_m: number;
  vehicle: string;
  engine: string;
  plasmanet_version: string;
  stagnation: StagnationState;
  uq: UQSummary;
  station_profile?: StationEntry[];   // 5 reflectometer stations along the body
}

export interface LOSData {
  meta: LOSMeta;
  frequencies: FrequencyBand[];
  uq_band?: UQBand;
}
