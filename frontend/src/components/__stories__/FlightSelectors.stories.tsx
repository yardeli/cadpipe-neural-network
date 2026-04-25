import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { FlightSelectors } from "../FlightSelectors";

const meta = {
  title: "Components/FlightSelectors",
  component: FlightSelectors,
  parameters: { layout: "padded" },
} satisfies Meta<typeof FlightSelectors>;

export default meta;
type Story = StoryObj<typeof meta>;

// Stateful wrapper so the buttons feel real in Storybook (clicking a pill
// flips the selection live, mirroring App.tsx's useState).
function Interactive({
  initialMach = 22.5,
  initialAlt = 61,
}: {
  initialMach?: number;
  initialAlt?: number;
}) {
  const [mach, setMach] = useState(initialMach);
  const [alt, setAlt] = useState(initialAlt);
  return (
    <FlightSelectors
      mach={mach}
      alt={alt}
      onMachChange={setMach}
      onAltChange={setAlt}
    />
  );
}

// `args` are required by the Story type but ignored — the Interactive
// wrapper owns the state and passes its own props through.
const placeholderArgs = {
  mach: 22.5,
  alt: 61,
  onMachChange: () => {},
  onAltChange: () => {},
};

export const Default: Story = {
  name: "Default (M22.5 @ 61 km — J&C primary)",
  args: placeholderArgs,
  render: () => <Interactive initialMach={22.5} initialAlt={61} />,
};

export const LowAltitude: Story = {
  name: "Low altitude (M18.5 @ 47 km)",
  args: placeholderArgs,
  render: () => <Interactive initialMach={18.5} initialAlt={47} />,
};

export const HighAltitude: Story = {
  name: "High altitude (M23.9 @ 81 km)",
  args: placeholderArgs,
  render: () => <Interactive initialMach={23.9} initialAlt={81} />,
};
