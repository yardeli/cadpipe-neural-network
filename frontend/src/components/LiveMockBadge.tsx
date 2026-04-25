/**
 * LiveMockBadge — pill that signals where the rendered data came from.
 *
 *   "loading" → muted spinner badge ("connecting…")
 *   "live"    → green LIVE pill (data fetched from the live PlasmaNet service)
 *   "mock"    → muted MOCK pill (server unreachable; static fallback rendered)
 *   "error"   → red ERROR pill (server returned a malformed response)
 */
import { Loader2 } from "lucide-react";

export type DataSource = "loading" | "live" | "mock" | "error";

interface Props {
  source: DataSource;
}

export function LiveMockBadge({ source }: Props) {
  if (source === "loading") {
    return (
      <span
        data-testid="live-mock-badge"
        data-source="loading"
        className="mt-1 flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs text-muted-foreground"
      >
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        connecting…
      </span>
    );
  }
  if (source === "live") {
    return (
      <span
        data-testid="live-mock-badge"
        data-source="live"
        className="mt-1 flex items-center gap-1.5 rounded-full border border-emerald-700 bg-emerald-950 px-2.5 py-0.5 text-xs font-medium text-emerald-400"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        LIVE
      </span>
    );
  }
  if (source === "error") {
    return (
      <span
        data-testid="live-mock-badge"
        data-source="error"
        className="mt-1 flex items-center gap-1.5 rounded-full border border-red-700 bg-red-950 px-2.5 py-0.5 text-xs font-medium text-red-400"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
        ERROR
      </span>
    );
  }
  return (
    <span
      data-testid="live-mock-badge"
      data-source="mock"
      className="mt-1 flex items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
      MOCK
    </span>
  );
}
