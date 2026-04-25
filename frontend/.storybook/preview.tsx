import type { Preview } from "@storybook/react-vite";
import React from "react";

// Bring the production Tailwind layers + dark-theme CSS variables into every
// story so components render with the same look as in App.tsx.
import "../src/index.css";

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    backgrounds: {
      default: "dark",
      values: [
        { name: "dark", value: "hsl(224 71% 4%)" },
        { name: "light", value: "#ffffff" },
      ],
    },
    a11y: {
      // 'todo' shows a11y violations in the test UI only
      test: "todo",
    },
  },
  decorators: [
    (Story) => (
      // The shipped dashboard uses CSS-variable-driven dark colours via the
      // bg-background / text-foreground utility classes — apply them at the
      // story root so individual stories don't have to.
      <div className="bg-background text-foreground p-6 min-h-screen">
        <Story />
      </div>
    ),
  ],
};

export default preview;
