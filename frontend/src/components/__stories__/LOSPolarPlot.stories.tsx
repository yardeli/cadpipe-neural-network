import type { Meta, StoryObj } from "@storybook/react-vite";
import { LOSPolarPlot } from "../LOSPolarPlot";
import staticMock from "../../data/mock_los.json";
import type { LOSData } from "../../types/los";

const data = staticMock as unknown as LOSData;

const meta = {
  title: "Components/LOSPolarPlot",
  component: LOSPolarPlot,
  parameters: { layout: "centered" },
} satisfies Meta<typeof LOSPolarPlot>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  name: "Default (4 frequencies + UQ)",
  args: {
    data,
    visibleFreqs: data.frequencies.map((_, i) => i),
    showUQ: true,
    width: 620,
    height: 380,
  },
};

export const Empty: Story = {
  name: "Empty (no frequencies enabled)",
  args: {
    data,
    visibleFreqs: [],
    showUQ: false,
    width: 620,
    height: 380,
  },
};

export const SingleFrequency: Story = {
  name: "Single frequency (X-band only)",
  args: {
    data,
    // X-band 9.2 GHz is at index 2 in the canonical band list
    // (VHF 225, VHF 450, X-band, Ku-band).
    visibleFreqs: [2],
    showUQ: false,
    width: 620,
    height: 380,
  },
};

export const NoUQBand: Story = {
  name: "All frequencies, UQ band hidden",
  args: {
    data,
    visibleFreqs: data.frequencies.map((_, i) => i),
    showUQ: false,
    width: 620,
    height: 380,
  },
};
