/**
 * Single source of truth for backend URL + endpoint paths.
 *
 * Resolution
 *   Production / staging:  set VITE_API_URL at build time. Vite injects
 *                           it into import.meta.env at compile time, so
 *                           it lands as a literal in the bundled JS.
 *   Local dev:              VITE_API_URL unset → default to
 *                           http://localhost:8200, which matches
 *                           `python -m plasmanet.mock_server`.
 *   Test (vitest):          tests mock fetch directly via vi.spyOn so the
 *                           URL value is never network-resolved; default
 *                           is fine.
 *
 * Trailing-slash normalization
 *   Strips trailing slashes so callers can safely concatenate
 *   `${API_BASE_URL}${ANALYZE_PATH}` without producing `//`.
 */
export const API_BASE_URL = (
  import.meta.env.VITE_API_URL ?? "http://localhost:8200"
).replace(/\/+$/, "");

export const ANALYZE_PATH = "/api/plasma/analyze_scan";
export const BENCHMARK_PATH = "/api/plasma/benchmark/ram_c";
