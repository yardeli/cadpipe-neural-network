import type { Meta, StoryObj } from "@storybook/react-vite";
import { LiveMockBadge } from "../LiveMockBadge";

const meta = {
  title: "Components/LiveMockBadge",
  component: LiveMockBadge,
  parameters: { layout: "centered" },
  argTypes: {
    source: {
      control: "select",
      options: ["loading", "live", "mock", "error"],
    },
  },
} satisfies Meta<typeof LiveMockBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Loading: Story = { args: { source: "loading" } };
export const Live: Story = { args: { source: "live" } };
export const Mock: Story = { args: { source: "mock" } };
export const Error: Story = { args: { source: "error" } };
