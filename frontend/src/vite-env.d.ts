/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Backend base URL — set at build time via `VITE_API_URL=...` to point
   * the production / staging build at a real PlasmaNet service. Unset in
   * dev: src/config.ts defaults to http://localhost:8200.
   */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
