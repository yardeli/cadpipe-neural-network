import type { Meta, StoryObj } from "@storybook/react-vite";
import { StationProfileChart } from "../StationProfileChart";
import type { StationEntry } from "../../types/los";

const meta = {
  title: "Components/StationProfileChart",
  component: StationProfileChart,
  parameters: { layout: "centered" },
} satisfies Meta<typeof StationProfileChart>;

export default meta;
type Story = StoryObj<typeof meta>;

// The synthetic station_profile baked into mock_los.json (M10 @ 35 km).
const SYNTHETIC_STATIONS: StationEntry[] = [
  { zL: 0.14, z_m: 0.1813,  r_wall_m: 0.1864834, max_ne_m3: 1.5744e+18, p99_ne_m3: 1.4485e+18, max_T_tr_K: 4523.8 },
  { zL: 0.32, z_m: 0.4144,  r_wall_m: 0.2588968, max_ne_m3: 6.8726e+17, p99_ne_m3: 6.3228e+17, max_T_tr_K: 3384.6 },
  { zL: 0.48, z_m: 0.6216,  r_wall_m: 0.3232642, max_ne_m3: 3.2894e+17, p99_ne_m3: 3.0263e+17, max_T_tr_K: 2615.2 },
  { zL: 0.67, z_m: 0.86765, r_wall_m: 0.3997005, max_ne_m3: 1.3713e+17, p99_ne_m3: 1.2616e+17, max_T_tr_K: 1925.3 },
  { zL: 0.88, z_m: 1.1396,  r_wall_m: 0.4841828, max_ne_m3: 5.2134e+16, p99_ne_m3: 4.7963e+16, max_T_tr_K: 1372.5 },
];

// Real NEMO data for M22.5 @ 61 km (from data/nemo_test/ram_c_validation.json).
// ne values are very different at this trajectory point — much higher peak,
// drops to zero past zL=0.32 because the sheath thins.
const NEMO_STATIONS: StationEntry[] = [
  { zL: 0.14, z_m: 0.3556,  r_wall_m: 0.1864834, max_ne_m3: 9.287e+08, p99_ne_m3: 9.049e+08, max_T_tr_K: 1915.5 },
  { zL: 0.32, z_m: 0.8128,  r_wall_m: 0.2588968, max_ne_m3: 0.0,       p99_ne_m3: 0.0,       max_T_tr_K: 1316.9 },
  { zL: 0.48, z_m: 1.2192,  r_wall_m: 0.3232642, max_ne_m3: 0.0,       p99_ne_m3: 0.0,       max_T_tr_K: 1062.6 },
  { zL: 0.67, z_m: 1.7018,  r_wall_m: 0.3997005, max_ne_m3: 0.0,       p99_ne_m3: 0.0,       max_T_tr_K: 866.0 },
  { zL: 0.88, z_m: 2.2352,  r_wall_m: 0.4841828, max_ne_m3: 0.0,       p99_ne_m3: 0.0,       max_T_tr_K: 773.2 },
];

export const SyntheticDecay: Story = {
  name: "Synthetic decay (offline / low-altitude path)",
  args: {
    stations: SYNTHETIC_STATIONS,
    width: 620,
    height: 240,
  },
};

export const NemoRealData: Story = {
  name: "Real NEMO data (M22.5 @ 61 km, J&C primary)",
  args: {
    stations: NEMO_STATIONS,
    width: 620,
    height: 240,
  },
};

export const Empty: Story = {
  name: "Empty (no stations)",
  args: {
    stations: [],
    width: 620,
    height: 240,
  },
};
