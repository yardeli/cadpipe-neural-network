# Legacy components

These are kept for reference but **superseded** by the current architecture.

## `demo.py` + `serve.py` — pre-React SBIR demo path

These were the standalone demo before `frontend/` and `mock_server.py` existed.

- `demo.py` — one-command launcher that opened a browser with a static UI
- `serve.py` — FastAPI app exposing `/predict`, `/predict_batch`, `/predict_envelope`,
  `/uncertainty` against a trained PlasmaNet checkpoint

**Replaced by:**
- `frontend/` (React + Vite + Tailwind UI)
- `plasmanet/mock_server.py` (canonical FastAPI under `/api/plasma/*`)
- `plasmanet/agent_tools.py` (LLM-callable tools for KhoriumAgents)

If you need a quick standalone demo without the React frontend running,
`python legacy/demo.py` should still work — it imports `legacy.serve`.
For everything else, use the current path.
