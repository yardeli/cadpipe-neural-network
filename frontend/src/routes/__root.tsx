/**
 * Root route — top nav + <Outlet /> for child routes.
 *
 * The dashboard has two pages:
 *   /            Home: live LOS detectability dashboard (the original App.tsx)
 *   /benchmark   J&C 1972 RAM-C II validation table
 *
 * Both share this thin shell: a sticky header with the project title and
 * tab links, then the active route renders below.
 */
import { Outlet, Link } from "@tanstack/react-router";

export function RootLayout() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto max-w-3xl flex items-center gap-6 px-6 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-base font-bold tracking-tight">
              PlasmaNet
            </span>
            <span className="text-xs text-muted-foreground">
              Detection Dashboard
            </span>
          </div>
          <nav className="flex gap-1 text-sm" aria-label="Primary">
            <NavLink to="/">Analyze</NavLink>
            <NavLink to="/benchmark">Benchmark</NavLink>
          </nav>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="rounded px-3 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      activeProps={{
        className:
          "rounded px-3 py-1 bg-primary text-primary-foreground font-medium",
      }}
      activeOptions={{ exact: true }}
    >
      {children}
    </Link>
  );
}
