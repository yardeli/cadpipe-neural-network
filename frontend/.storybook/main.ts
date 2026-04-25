import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  addons: [
    "@storybook/addon-docs",
    "@storybook/addon-a11y",
  ],
  framework: "@storybook/react-vite",
  // Storybook's docgen / TS handling is fine without explicit config.
};
export default config;
