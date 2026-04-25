/**
 * Tanstack Router setup — code-based (no file plugin / codegen).
 *
 * The route components live under src/routes/* by convention; this module
 * just wires them into a router instance that main.tsx mounts via
 * <RouterProvider />.
 */
import {
  createRootRoute,
  createRoute,
  createRouter,
  createMemoryHistory,
} from "@tanstack/react-router";

import { RootLayout } from "@/routes/__root";
import HomePage from "@/routes/index";
import BenchmarkPage from "@/routes/benchmark";

const rootRoute = createRootRoute({
  component: RootLayout,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const benchmarkRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/benchmark",
  component: BenchmarkPage,
});

const routeTree = rootRoute.addChildren([indexRoute, benchmarkRoute]);

export const router = createRouter({ routeTree });

/**
 * Build a self-contained router for tests/Storybook so we don't need a
 * window.history mock or to share state across stories.
 */
export function createTestRouter(initialPath: string = "/") {
  return createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
