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

export interface LOSMeta {
  mach: number;
  altitude_km: number;
  nose_radius_m: number;
  vehicle: string;
  engine: string;
  plasmanet_version: string;
  stagnation: StagnationState;
  uq: UQSummary;
}

export interface LOSData {
  meta: LOSMeta;
  frequencies: FrequencyBand[];
  uq_band?: UQBand;
}
