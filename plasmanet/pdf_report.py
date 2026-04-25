"""One-page A4 detectability report PDF.

Composes a printable summary that an SBIR reviewer or non-technical reader
can absorb without opening the live dashboard. Layout:

    Header band      "Khorium PlasmaNet — Detectability Analysis"
    Flight row       vehicle, Mach, altitude, engine
    Stagnation box   T_tr, T_ve, p, n_e, f_p
    Polar chart      LOS attenuation across 4 frequency bands (left)
    Station chart    n_e(z/L) along reflectometer stations, log-y (right)
    Status table     per-band Min/Max dB + worst status (cell-tinted)
    UQ band          P05/P50/P95 n_e + log10 std
    Footer           generation timestamp + plasmanet version + references

Charts: matplotlib with the Agg backend (lazy-imported inside helpers so
this module's top-level import stays cheap).
Page:   reportlab canvas, A4 (595×842 pt).

build_pdf returns the bytes; the FastAPI route streams them with
Content-Type: application/pdf.
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone
from typing import Optional

PLASMANET_VERSION = "0.3.0"


# ── Canonical RAM-C II trajectory points ──────────────────────────────────────
# Published peak n_e (electrons/m³) from Jones & Cross 1972 (NASA TN D-6617)
# at the four reflectometer instrumentation altitudes. Used by /api/plasma/report
# to auto-populate the Validation section when the request flight condition
# is within tolerance of one of these points.
#
# Key: (mach, altitude_km) → reference peak n_e (m⁻³)
CANONICAL_RAMC_POINTS: dict[tuple[float, float], float] = {
    (23.9, 81.0): 2.0e18,
    (23.6, 71.0): 1.0e19,
    (22.5, 61.0): 2.0e19,
    (18.5, 47.0): 2.0e19,
}


def find_canonical_match(
    mach: float,
    altitude_km: float,
    *,
    mach_tol: float = 0.1,
    alt_tol_km: float = 1.0,
) -> tuple[float, float] | None:
    """Return the closest canonical RAM-C trajectory point within tolerance.

    Returns None when (mach, altitude_km) is outside ±0.1 Mach and ±1 km of
    every canonical entry — caller should pass benchmark_log10_error=None
    so the PDF's Validation section stays hidden.
    """
    for (m, a) in CANONICAL_RAMC_POINTS:
        if abs(m - mach) <= mach_tol and abs(a - altitude_km) <= alt_tol_km:
            return (m, a)
    return None


# ── Chart helpers ─────────────────────────────────────────────────────────────

def _polar_chart_png(frequencies: list[dict]) -> bytes:
    """Render the multi-band polar attenuation chart as PNG bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(
        figsize=(3.6, 3.0),
        subplot_kw={"projection": "polar"},
        dpi=120,
    )
    ax.set_thetamin(0)
    ax.set_thetamax(180)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    max_db = 5.0
    for band in frequencies:
        scan = band.get("aspect_scan", [])
        if not scan:
            continue
        thetas = [math.radians(p["angle_deg"]) for p in scan]
        dbs = [max(float(p["attenuation_db"]), 0.5) for p in scan]
        max_db = max(max_db, max(dbs))
        ax.plot(
            thetas,
            dbs,
            label=band.get("label", ""),
            color=band.get("color", "#3b82f6"),
            linewidth=1.5,
        )

    ax.set_rticks([2, 20, 100, max(max_db, 100)])
    ax.set_rlabel_position(135)
    ax.tick_params(labelsize=7)
    ax.set_title("LOS attenuation (dB) vs aspect angle", fontsize=9, pad=8)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.05), fontsize=6, frameon=False)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    return buf.getvalue()


def _station_chart_png(stations: list[dict]) -> bytes:
    """Render the n_e(z/L) reflectometer-station profile as PNG bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(3.6, 3.0), dpi=120)
    zls = [s["zL"] for s in stations]
    nes_max = [max(s.get("max_ne_m3", 1.0), 1.0) for s in stations]
    nes_p99 = [max(s.get("p99_ne_m3", 1.0), 1.0) for s in stations]

    ax.semilogy(zls, nes_max, "o-", color="#3b82f6", linewidth=1.5, label="max nₑ")
    ax.semilogy(zls, nes_p99, "s--", color="#3b82f6", alpha=0.5,
                linewidth=1.0, label="p99 nₑ")

    ax.set_xlabel("z / L  (axial station)", fontsize=8)
    ax.set_ylabel("n_e (m⁻³)", fontsize=8)
    ax.set_xlim(0, 1)
    ax.grid(True, which="both", alpha=0.2)
    ax.legend(loc="upper right", fontsize=7, frameon=False)
    ax.set_title("Reflectometer-station n_e profile", fontsize=9, pad=8)
    ax.tick_params(labelsize=7)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    return buf.getvalue()


# ── Detection-status helpers ──────────────────────────────────────────────────

def _detection_status(atten_db: float) -> str:
    if atten_db < 2.0:
        return "DETECTABLE"
    if atten_db < 20.0:
        return "DEGRADED"
    return "BLACKOUT"


def _status_color(status: str) -> str:
    return {
        "DETECTABLE": "#d1fae5",   # mint
        "DEGRADED":   "#fef3c7",   # amber
        "BLACKOUT":   "#fecaca",   # rose
    }.get(status, "#e5e7eb")


# ── PDF composer ──────────────────────────────────────────────────────────────

def build_pdf(
    *,
    meta: dict,
    frequencies: list[dict],
    station_profile: Optional[list[dict]],
    benchmark_log10_error: Optional[float] = None,
) -> bytes:
    """Compose the one-page PDF and return its bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import HexColor, black, white
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    page_w, page_h = A4   # 595, 842 pt

    pdf_buf = io.BytesIO()
    c = canvas.Canvas(pdf_buf, pagesize=A4)
    c.setTitle("Khorium PlasmaNet — Detectability Analysis")
    c.setAuthor("Khorium / PlasmaNet")

    # ── Header band ────────────────────────────────────────────────────────
    c.setFillColor(HexColor("#1e3a8a"))
    c.rect(0, page_h - 50, page_w, 50, fill=True, stroke=False)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 30, "Khorium PlasmaNet — Detectability Analysis")
    c.setFont("Helvetica", 9)
    c.drawString(40, page_h - 44, "Aspect-resolved LOS radar attenuation report")

    y = page_h - 70

    # ── Flight condition row ───────────────────────────────────────────────
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "Flight condition")
    c.setFont("Helvetica", 9)
    flight_text = (
        f"Vehicle: {meta.get('vehicle', '?')}     "
        f"Mach: {meta.get('mach', 0):.2f}     "
        f"Altitude: {meta.get('altitude_km', 0):.1f} km     "
        f"Engine: {meta.get('engine', '?')}"
    )
    c.drawString(120, y, flight_text)
    y -= 18

    # ── Stagnation box ─────────────────────────────────────────────────────
    s = meta.get("stagnation", {}) or {}
    box_h = 50
    c.setStrokeColor(HexColor("#cbd5e1"))
    c.setFillColor(HexColor("#f8fafc"))
    c.roundRect(40, y - box_h, page_w - 80, box_h, 4, fill=True, stroke=True)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, y - 14, "Stagnation state (SU2-NEMO)" if s.get("T_ve_K")
                              else "Stagnation state")
    c.setFont("Helvetica", 9)
    line1 = (
        f"T_tr = {s.get('T_tr_K', 0):,.0f} K     "
        f"T_ve = {(s.get('T_ve_K') or 0):,.0f} K     "
        f"p = {s.get('p_Pa', 0):,.0f} Pa"
    )
    line2 = (
        f"n_e = {s.get('ne_m3', 0):.2e} m⁻³     "
        f"f_p = {s.get('fp_GHz', 0):.1f} GHz"
    )
    c.drawString(50, y - 28, line1)
    c.drawString(50, y - 42, line2)
    y -= box_h + 10

    # ── Charts (side-by-side) ──────────────────────────────────────────────
    chart_h = 200
    chart_w = (page_w - 80 - 10) / 2     # two charts + 10pt gutter, 40pt margins
    polar_png = _polar_chart_png(frequencies)
    c.drawImage(
        ImageReader(io.BytesIO(polar_png)),
        40, y - chart_h, width=chart_w, height=chart_h,
        preserveAspectRatio=True, anchor="c",
    )
    if station_profile:
        station_png = _station_chart_png(station_profile)
        c.drawImage(
            ImageReader(io.BytesIO(station_png)),
            40 + chart_w + 10, y - chart_h,
            width=chart_w, height=chart_h,
            preserveAspectRatio=True, anchor="c",
        )
    y -= chart_h + 12

    # ── Detection status table ─────────────────────────────────────────────
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "Detection status by frequency")
    y -= 12

    cols = [40, 175, 245, 305, 405]
    headers = ["Band", "Min dB", "Max dB", "Worst status", "Plasma freq (GHz)"]
    c.setFillColor(HexColor("#e5e7eb"))
    c.rect(40, y - 4, page_w - 80, 14, fill=True, stroke=False)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    for cx, h in zip(cols, headers):
        c.drawString(cx + 4, y + 2, h)
    y -= 14

    fp_GHz = s.get("fp_GHz", 0)
    c.setFont("Helvetica", 8)
    for band in frequencies:
        scan = band.get("aspect_scan", [])
        if not scan:
            continue
        dbs = [float(p["attenuation_db"]) for p in scan]
        mn, mx = min(dbs), max(dbs)
        worst = _detection_status(mx)

        # Tint the status cell.
        c.setFillColor(HexColor(_status_color(worst)))
        c.rect(cols[3], y - 4, cols[4] - cols[3], 14, fill=True, stroke=False)
        c.setFillColor(black)

        row = [
            str(band.get("label", "?"))[:24],
            f"{mn:.1f}",
            f"{mx:.1f}",
            worst,
            f"{fp_GHz:.1f}",
        ]
        for cx, val in zip(cols, row):
            c.drawString(cx + 4, y + 2, val)
        y -= 14
    y -= 6

    # ── UQ band ────────────────────────────────────────────────────────────
    uq = meta.get("uq")
    if uq:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, "Uncertainty band (Monte-Carlo, 64-sample LHS)")
        y -= 12
        c.setFont("Helvetica", 9)
        uq_text = (
            f"n_e:  P05 = {uq.get('ne_P05_m3', 0):.2e}   "
            f"P50 = {uq.get('ne_P50_m3', 0):.2e}   "
            f"P95 = {uq.get('ne_P95_m3', 0):.2e}  m⁻³   "
            f"(σ_log10 = {uq.get('log10_ne_std', 0):.2f})"
        )
        c.drawString(40, y, uq_text)
        y -= 16

    # ── Validation snippet (if benchmark_log10_error provided) ─────────────
    if benchmark_log10_error is not None:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, "Validation")
        y -= 12
        c.setFont("Helvetica", 9)
        bench = (
            f"log10(n_e_pred / n_e_ref) vs Jones & Cross 1972 = "
            f"{benchmark_log10_error:+.2f}   "
            f"({'within ±0.5 (PASS)' if abs(benchmark_log10_error) < 0.5 else 'outside ±0.5 (FAIL)'})"
        )
        c.drawString(40, y, bench)

    # ── Footer ─────────────────────────────────────────────────────────────
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    c.setFillColor(HexColor("#64748b"))
    c.setFont("Helvetica", 7)
    footer = (
        f"Generated {ts}  |  plasmanet v{meta.get('plasmanet_version', PLASMANET_VERSION)}  |  "
        f"References: Jones & Cross 1972 (NASA TN D-6617), Grantham 1970 (NASA TN D-6062)"
    )
    c.drawString(40, 24, footer)

    c.showPage()
    c.save()
    return pdf_buf.getvalue()
