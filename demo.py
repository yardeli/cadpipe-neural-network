"""PlasmaNet SBIR Demo — self-contained launcher.

One-command demo for AFRL/defense presentations.
Starts PlasmaNet server and opens the demo page in the browser.

Usage:
    python demo.py
    python demo.py --port 8100
"""
import argparse
import math
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure we can import plasmanet
sys.path.insert(0, str(Path(__file__).parent))


DEMO_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PlasmaNet — Hypersonic Plasma Prediction</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0d1117; color: #f1f5f9; }
.header { background: linear-gradient(135deg, #1a1f2e 0%, #0d1117 100%); padding: 20px 40px; border-bottom: 2px solid #3b82f6; }
.header h1 { font-size: 28px; color: #3b82f6; }
.header p { color: #94a3b8; margin-top: 4px; }
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }
.controls { display: flex; gap: 24px; align-items: end; margin-bottom: 24px; flex-wrap: wrap; }
.control-group { display: flex; flex-direction: column; gap: 4px; }
.control-group label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; }
.control-group input[type=range] { width: 200px; accent-color: #3b82f6; }
.control-group .value { font-size: 24px; font-weight: bold; color: #3b82f6; min-width: 60px; }
.btn { padding: 10px 24px; background: #3b82f6; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 600; }
.btn:hover { background: #2563eb; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.card { background: #1a1f2e; border-radius: 12px; padding: 20px; border-top: 3px solid #3b82f6; }
.card h3 { font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
.hero-value { font-size: 36px; font-weight: bold; }
.hero-sub { font-size: 13px; color: #94a3b8; margin-top: 4px; }
.status-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; font-weight: 700; font-size: 18px; }
.status-BLACKOUT { background: #7f1d1d; color: #fca5a5; }
.status-ATTENUATED { background: #78350f; color: #fcd34d; }
.status-DETECTABLE { background: #064e3b; color: #6ee7b7; }
.envelope-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.envelope-table th, .envelope-table td { padding: 6px 8px; text-align: center; font-size: 12px; border: 1px solid #2d3748; }
.envelope-table th { background: #1e293b; color: #94a3b8; }
.env-B { background: #7f1d1d; color: #fca5a5; font-weight: bold; }
.env-A { background: #78350f; color: #fcd34d; font-weight: bold; }
.env-D { background: #064e3b; color: #6ee7b7; font-weight: bold; }
.species-bar { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.species-bar .name { width: 30px; font-size: 12px; color: #94a3b8; }
.species-bar .bar { height: 16px; background: #3b82f6; border-radius: 3px; transition: width 0.3s; }
.species-bar .pct { font-size: 11px; color: #64748b; }
.timing { font-size: 11px; color: #475569; margin-top: 8px; }
.footer { text-align: center; padding: 20px; color: #475569; font-size: 12px; }
</style>
</head>
<body>
<div class="header">
    <h1>PlasmaNet</h1>
    <p>Real-Time Hypersonic Plasma Prediction — Neural Surrogate (578 KB model, 0.01ms inference)</p>
</div>
<div class="container">
    <div class="controls">
        <div class="control-group">
            <label>Mach Number</label>
            <input type="range" id="mach" min="3" max="20" step="0.5" value="10">
            <div class="value" id="mach-val">10.0</div>
        </div>
        <div class="control-group">
            <label>Altitude (km)</label>
            <input type="range" id="alt" min="15" max="55" step="1" value="35">
            <div class="value" id="alt-val">35</div>
        </div>
        <div class="control-group">
            <label>Nose Radius (m)</label>
            <input type="range" id="nose" min="0.01" max="1.0" step="0.01" value="0.08">
            <div class="value" id="nose-val">0.08</div>
        </div>
        <div class="control-group">
            <label>&nbsp;</label>
            <button class="btn" onclick="analyze()">Analyze</button>
        </div>
    </div>

    <div class="grid" id="results">
        <div class="card" style="grid-column: span 2;">
            <h3>Slide the controls above and click Analyze</h3>
            <p style="color: #64748b">PlasmaNet predicts electron density, plasma frequency, and radar detection status in real-time.</p>
        </div>
    </div>
</div>
<div class="footer">
    Khorium Technologies — PlasmaNet v1.0 — Powered by 45,000 Cantera simulations + active learning
</div>

<script>
const BASE = window.location.origin;

document.getElementById('mach').addEventListener('input', e => {
    document.getElementById('mach-val').textContent = parseFloat(e.target.value).toFixed(1);
    analyze();
});
document.getElementById('alt').addEventListener('input', e => {
    document.getElementById('alt-val').textContent = e.target.value;
    analyze();
});
document.getElementById('nose').addEventListener('input', e => {
    document.getElementById('nose-val').textContent = parseFloat(e.target.value).toFixed(2);
    analyze();
});

let debounceTimer;
async function analyze() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
        const mach = parseFloat(document.getElementById('mach').value);
        const alt = parseFloat(document.getElementById('alt').value);
        const nose = parseFloat(document.getElementById('nose').value);

        const t0 = performance.now();
        const resp = await fetch(`${BASE}/predict?mach=${mach}&altitude_km=${alt}&nose_radius_m=${nose}`);
        const data = await resp.json();
        const roundtrip = (performance.now() - t0).toFixed(0);

        // Also get envelope
        const envResp = await fetch(`${BASE}/predict_envelope`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({machs: [5,8,10,12,15,20], altitudes: [20,25,30,35,40,45,50], nose_radius_m: nose})
        });
        const envData = await envResp.json();

        renderResults(data, envData, roundtrip);
    }, 150);
}

function renderResults(data, envData, roundtrip) {
    const statusClass = 'status-' + data.status;
    const species = data.species || {};
    const maxPct = Math.max(...Object.values(species), 0.01) * 100;

    let speciesHTML = '';
    for (const [name, frac] of Object.entries(species).sort((a,b) => b[1]-a[1])) {
        const pct = (frac * 100).toFixed(2);
        const width = Math.max(2, frac / Math.max(...Object.values(species)) * 100);
        speciesHTML += `<div class="species-bar">
            <span class="name">${name}</span>
            <div class="bar" style="width: ${width}%"></div>
            <span class="pct">${pct}%</span>
        </div>`;
    }

    // Envelope table
    const machs = envData.machs || [];
    const alts = envData.altitudes || [];
    const grid = envData.grid || {};
    let envHTML = '<table class="envelope-table"><tr><th></th>';
    for (const a of alts) envHTML += `<th>${a} km</th>`;
    envHTML += '</tr>';
    for (const m of machs) {
        envHTML += `<tr><th>M ${m}</th>`;
        const row = grid[String(m)] || [];
        for (const cell of row) {
            const s = cell.status === 'BLACKOUT' ? 'B' : cell.status === 'ATTENUATED' ? 'A' : 'D';
            envHTML += `<td class="env-${s}">${s} (${cell.fp_GHz})</td>`;
        }
        envHTML += '</tr>';
    }
    envHTML += '</table>';

    document.getElementById('results').innerHTML = `
        <div class="card">
            <h3>Detection Status</h3>
            <div class="${statusClass} status-badge">${data.status}</div>
            <div class="hero-sub" style="margin-top:12px">Plasma freq: ${data.fp_GHz} GHz vs 12 GHz StarLink</div>
        </div>
        <div class="card">
            <h3>Stagnation Temperature</h3>
            <div class="hero-value">${Math.round(data.T_stag_K).toLocaleString()} K</div>
            <div class="hero-sub">Real-gas corrected (dissociation cooling)</div>
        </div>
        <div class="card">
            <h3>Electron Density</h3>
            <div class="hero-value">${data.ne_m3}</div>
            <div class="hero-sub">m<sup>-3</sup> (Saha + non-equilibrium correction)</div>
        </div>
        <div class="card">
            <h3>Species Composition</h3>
            ${speciesHTML}
        </div>
        <div class="card" style="grid-column: span 2;">
            <h3>Detection Envelope (Mach x Altitude)</h3>
            ${envHTML}
            <div class="timing">D = Detectable | A = Attenuated | B = Blackout | Values in GHz</div>
        </div>
        <div class="card">
            <h3>Performance</h3>
            <div class="hero-value">${data.inference_ms} ms</div>
            <div class="hero-sub">Server inference time</div>
            <div class="hero-sub" style="margin-top:8px">Round-trip: ${roundtrip} ms | Model: 578 KB | No GPU</div>
        </div>
    `;
}

// Auto-run on load
setTimeout(analyze, 500);
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="PlasmaNet SBIR Demo")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    # Find best model
    ckpt_dir = Path(__file__).parent / "checkpoints"
    model_path = None
    for name in ["plasmanet_best.pt", "plasmanet_v4_deep.pt", "plasmanet_v3.pt", "plasmanet_v1.pt"]:
        p = ckpt_dir / name
        if p.exists():
            model_path = str(p)
            break

    if model_path is None:
        print("No model checkpoint found. Run training first:")
        print("  python -m plasmanet.generate_data")
        print("  python -m plasmanet.model --data data/training_data.npz")
        sys.exit(1)

    print(f"PlasmaNet SBIR Demo")
    print(f"  Model: {model_path}")
    print(f"  Port:  {args.port}")

    # Create the app with an extra /demo route serving the HTML
    from plasmanet.serve import create_app
    from fastapi.responses import HTMLResponse

    app = create_app(model_path)

    @app.get("/demo", response_class=HTMLResponse)
    async def demo_page():
        return DEMO_HTML

    # Redirect root to demo
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/demo")

    # Open browser after short delay
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{args.port}/demo")
        threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    print(f"\n  Demo: http://localhost:{args.port}/demo")
    print(f"  API:  http://localhost:{args.port}/predict?mach=10&altitude_km=35")
    print(f"\n  Press Ctrl+C to stop\n")
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
