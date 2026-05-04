"""PlasmaNet v4 Streamlit UI.

A hypersonics engineer drops in flight conditions + picks reactions from
Park-47, hits Predict, and immediately sees:
    - Predicted log10(ne_peak) [m^-3]
    - Predicted ne_peak [m^-3]
    - S-band attenuation estimate (Appleton-Hartree)
    - Optional Cantera 0D ground-truth comparison
    - Predicted vs J&C 1972 RAM-C reference

Run locally:
    cd <repo-root>
    PYTHONPATH=. streamlit run apps/surrogate_ui/streamlit_app.py

Run on the VM (with port-forward):
    gcloud compute ssh openfoam-hgv --zone=us-central1-a -- -L 8501:localhost:8501
    cd /home/yarden/plasmanet
    PYTHONPATH=. streamlit run apps/surrogate_ui/streamlit_app.py

Configure model path:
    export SURROGATE_PATH=/path/to/surrogate_v4.pt
    (or use the sidebar text input / file uploader)
"""
from __future__ import annotations

import io
import math
import os
import tempfile
from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go
import streamlit as st

# Lazy torch import — fail clearly if missing.
try:
    import torch
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False
    torch = None

from plasmanet.mechanism_search import (
    PARK_47,
    BENCHMARKS,
    MechanismFingerprint,
    MechanismSurrogate,
    freestream_features,
    park_air5,
    park_air7,
    park_air11,
    score_candidate,
)
from plasmanet.mechanism_search.surrogate import (
    _us_standard_atmosphere_T,
    _us_standard_atmosphere_P,
)


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_SURROGATE_PATH = os.environ.get(
    "SURROGATE_PATH",
    "/home/yarden/mechanism_search_results/surrogate_v4.pt",
)

# v4 architecture (per training run)
HIDDEN_DIM = 512
N_LAYERS = 4
FREESTREAM_DIM = 4
MECHANISM_DIM = 47
MODEL_VAL_MAE_LOG10 = 0.183
MODEL_FACTOR = 1.52

# S-band test frequency for attenuation estimate.
S_BAND_HZ = 5.7e9

# RAM-C benchmark presets (pulled from BENCHMARKS, but display-friendly names).
PRESET_BENCHMARKS = {
    "(none)": None,
    "RAM-C 47 km / Mach 18.5": "ram_c_47km_M18.5",
    "RAM-C 61 km / Mach 22.5 (J&C 1972 anchor)": "ram_c_61km_M22.5",
    "RAM-C 71 km / Mach 23.6": "ram_c_71km_M23.6",
    "RAM-C 81 km / Mach 23.9": "ram_c_81km_M23.9",
}


# ──────────────────────────────────────────────────────────────────────────────
# Model loading (cached)
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Loading PlasmaNet v4 surrogate...")
def load_surrogate(path_or_bytes) -> "MechanismSurrogate":
    """Instantiate model + load state_dict from a path OR raw bytes.

    cache_resource ensures we only load once per session.
    """
    if not HAVE_TORCH:
        raise RuntimeError(
            "PyTorch is required. Install via `pip install torch`."
        )

    model = MechanismSurrogate(
        freestream_dim=FREESTREAM_DIM,
        mechanism_dim=MECHANISM_DIM,
        hidden_dim=HIDDEN_DIM,
        n_layers=N_LAYERS,
    )

    if isinstance(path_or_bytes, (bytes, bytearray)):
        state = torch.load(io.BytesIO(path_or_bytes), map_location="cpu")
    else:
        state = torch.load(path_or_bytes, map_location="cpu")

    # Some training scripts wrap the state_dict; unwrap if needed.
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    if isinstance(state, dict) and "model_state_dict" in state:
        state = state["model_state_dict"]

    model.load_state_dict(state)
    model.eval()
    return model


def count_params(model) -> int:
    return sum(p.numel() for p in model.parameters())


# ──────────────────────────────────────────────────────────────────────────────
# Inference helpers
# ──────────────────────────────────────────────────────────────────────────────

def predict_ne(
    model,
    altitude_km: float,
    mach: float,
    T_inf: float,
    P_inf: float,
    selected_rxn_ids: list[int],
) -> tuple[float, float]:
    """Run a single forward pass. Returns (log10_ne, ne_m3)."""
    fs = freestream_features(altitude_km, mach, T_inf=T_inf, P_inf=P_inf)
    fp = np.array(
        [1.0 if r.rxn_id in set(selected_rxn_ids) else 0.0
         for r in PARK_47.reactions],
        dtype=np.float32,
    )
    x = np.concatenate([fs, fp]).astype(np.float32)
    x_t = torch.from_numpy(x).unsqueeze(0)

    # BatchNorm with batch_size=1 in eval mode — uses running stats, fine.
    with torch.no_grad():
        log10_ne = float(model(x_t).squeeze().item())
    ne = 10.0 ** log10_ne
    return log10_ne, ne


def appleton_hartree_db(
    ne_m3: float,
    f_hz: float = S_BAND_HZ,
    sheath_path_m: float = 0.30,
    P_pa: float = 100.0,
) -> float:
    """S-band one-way attenuation (dB), Appleton-Hartree-style.

    Mirrors the form used in plasmanet/mechanism_search/cantera_evaluator.py:
        f_p = 8980 * sqrt(n_e[cm^-3])  [Hz]
        nu_collision ≈ 1e10 * (P/atm)  [Hz]
        if f < f_p:    fully evanescent → saturated 100 dB
        else:          alpha = 8.686 * omega_p^2 * nu / (2c (omega^2 + nu^2))
                       attenuation = alpha * path_length
    """
    if ne_m3 <= 0:
        return 0.0
    f_p_hz = 8980.0 * math.sqrt(max(ne_m3 * 1e-6, 0.0))
    if f_hz <= f_p_hz:
        return 100.0
    omega = 2 * math.pi * f_hz
    omega_p = 2 * math.pi * f_p_hz
    nu = 1e10 * (P_pa / 1.01325e5)
    alpha = 8.686 * (omega_p ** 2 * nu) / (
        2 * 3e8 * (omega ** 2 + nu ** 2)
    )
    return float(alpha * sheath_path_m)


# ──────────────────────────────────────────────────────────────────────────────
# Reaction tagging helpers for the multiselect grid
# ──────────────────────────────────────────────────────────────────────────────

def reaction_kind(r) -> str:
    if r.is_ionization:
        return "ionization"
    if r.is_dissociation:
        return "dissociation"
    if r.is_charge_transfer:
        return "charge_transfer"
    if r.is_exchange:
        return "exchange"
    return "other"


def kind_color(kind: str) -> str:
    return {
        "dissociation": "#ff7f0e",
        "ionization": "#d62728",
        "exchange": "#2ca02c",
        "charge_transfer": "#9467bd",
        "other": "#7f7f7f",
    }.get(kind, "#7f7f7f")


def air_subset_ids(mech) -> set[int]:
    return {r.rxn_id for r in mech.reactions}


def _btn_type_if_active(active: bool) -> str:
    """Streamlit's primary buttons render bright/red — use this to make
    the currently-active preset look 'depressed'."""
    return "primary" if active else "secondary"


def _matches_us_std(current: float, expected: float, rel_tol: float = 0.01) -> bool:
    """True if `current` is within rel_tol of `expected` (for US-Std auto-fill check)."""
    if expected == 0:
        return abs(current) < 1e-9
    return abs(current - expected) / abs(expected) < rel_tol


# ──────────────────────────────────────────────────────────────────────────────
# Streamlit page
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PlasmaNet v4 Surrogate",
    page_icon=None,
    layout="wide",
)

st.title("PlasmaNet v4 — Hypersonic Plasma ne Surrogate")
st.caption(
    f"4-layer x {HIDDEN_DIM}-hidden MLP   |   "
    f"input dim = {FREESTREAM_DIM} freestream + {MECHANISM_DIM} reactions = "
    f"{FREESTREAM_DIM + MECHANISM_DIM}   |   "
    f"val MAE = {MODEL_VAL_MAE_LOG10:.3f} log10  (factor of {MODEL_FACTOR:.2f}x)"
)


# ─── Sidebar: model + flight conditions + mechanism ──────────────────────────

with st.sidebar:
    st.header("Model")

    surrogate_path = st.text_input(
        "Surrogate checkpoint path",
        value=DEFAULT_SURROGATE_PATH,
        help="Path on the host running Streamlit. Set $SURROGATE_PATH to "
             "override the default. Ignored if you upload a .pt below.",
    )
    uploaded = st.file_uploader(
        "...or upload a .pt checkpoint",
        type=["pt", "pth"],
        help="For local use when the trained model lives on your machine.",
    )

    st.divider()
    st.header("Flight conditions")

    # ── One-time defaults (must come BEFORE any widget that uses these keys).
    # Streamlit forbids writing to a widget-bound session_state key from the
    # script body once that widget exists; only callbacks may. So we set
    # defaults via setdefault (no-op if already set) and use callbacks for
    # everything else.
    _DEFAULTS = {
        "altitude_km": 61.0, "mach": 22.5,
        "T_inf": 242.65, "P_inf": 253.71,
        "preset_label": list(PRESET_BENCHMARKS.keys())[2],   # 61km/M22.5 anchor
    }
    for _k, _v in _DEFAULTS.items():
        st.session_state.setdefault(_k, _v)

    def _apply_preset():
        """Triggered when the preset selectbox changes (on_change)."""
        label = st.session_state["preset_label"]
        key = PRESET_BENCHMARKS.get(label)
        bk = BENCHMARKS.get(key) if key else None
        if bk is not None:
            st.session_state["altitude_km"] = float(bk.altitude_km)
            st.session_state["mach"] = float(bk.mach)
            st.session_state["T_inf"] = float(bk.temperature_k)
            st.session_state["P_inf"] = float(bk.pressure_pa)

    def _set_T_to_us_std():
        st.session_state["T_inf"] = float(
            _us_standard_atmosphere_T(st.session_state["altitude_km"])
        )

    def _set_P_to_us_std():
        st.session_state["P_inf"] = float(
            _us_standard_atmosphere_P(st.session_state["altitude_km"])
        )

    st.selectbox(
        "Benchmark preset",
        options=list(PRESET_BENCHMARKS.keys()),
        key="preset_label",
        on_change=_apply_preset,
        help="RAM-C published flight points (Jones & Cross 1972, Grantham 1970).",
    )
    preset_label = st.session_state["preset_label"]
    preset_key = PRESET_BENCHMARKS[preset_label]
    preset_bk = BENCHMARKS.get(preset_key) if preset_key else None

    altitude_km = st.slider(
        "Altitude [km]", min_value=40.0, max_value=100.0,
        step=0.5, key="altitude_km",
    )
    st.caption(f"current altitude:  **{altitude_km:.1f} km**")

    mach = st.slider(
        "Mach", min_value=10.0, max_value=30.0,
        step=0.1, key="mach",
    )
    st.caption(f"current Mach:  **M = {mach:.2f}**")

    # US-Std targets at the *current* altitude (recomputed every rerun).
    _t_target = float(_us_standard_atmosphere_T(altitude_km))
    _p_target = float(_us_standard_atmosphere_P(altitude_km))

    cols_t = st.columns([3, 2])
    with cols_t[0]:
        T_inf = st.number_input(
            "T_inf [K]", min_value=100.0, max_value=400.0,
            step=1.0, key="T_inf", format="%.2f",
        )
    with cols_t[1]:
        t_match = _matches_us_std(T_inf, _t_target)
        st.button(
            "US-Std", key="us_std_T_btn",
            help=f"Auto-fill T_inf to US Std @ {altitude_km:.1f} km = {_t_target:.2f} K",
            use_container_width=True,
            type=_btn_type_if_active(t_match),
            on_click=_set_T_to_us_std,
        )
    st.caption(
        f"US-Std target @ {altitude_km:.1f} km:  **{_t_target:.2f} K**  "
        + ("✓ matches current" if t_match else "× current value differs")
    )

    cols_p = st.columns([3, 2])
    with cols_p[0]:
        P_inf = st.number_input(
            "P_inf [Pa]", min_value=0.1, max_value=200000.0,
            step=1.0, key="P_inf", format="%.3f",
        )
    with cols_p[1]:
        p_match = _matches_us_std(P_inf, _p_target)
        st.button(
            "US-Std ", key="us_std_P_btn",
            help=f"Auto-fill P_inf to US Std @ {altitude_km:.1f} km = {_p_target:.3f} Pa",
            use_container_width=True,
            type=_btn_type_if_active(p_match),
            on_click=_set_P_to_us_std,
        )
    st.caption(
        f"US-Std target @ {altitude_km:.1f} km:  **{_p_target:.3f} Pa**  "
        + ("✓ matches current" if p_match else "× current value differs")
    )

    st.divider()
    st.header("Mechanism (Park-47)")

    # Preset selection buttons — write rxn_id sets into session state.
    if "selected_rxn_ids" not in st.session_state:
        st.session_state["selected_rxn_ids"] = sorted(air_subset_ids(park_air7()))

    # Compute which preset matches the current selection so the active
    # button can render in 'primary' style ('depressed' look).
    _curr_set = set(st.session_state["selected_rxn_ids"])
    _air5_ids = air_subset_ids(park_air5())
    _air7_ids = air_subset_ids(park_air7())
    _air11_ids = air_subset_ids(park_air11())
    _all_valid_ids = {r.rxn_id for r in PARK_47.reactions if r.A > 0}
    is_air5  = (_curr_set == _air5_ids)
    is_air7  = (_curr_set == _air7_ids)
    is_air11 = (_curr_set == _air11_ids)
    is_all   = (_curr_set == _all_valid_ids)
    is_clear = (len(_curr_set) == 0)
    if is_air5:    active_label = "AIR-5"
    elif is_air7:  active_label = "AIR-7"
    elif is_air11: active_label = "AIR-11 (full Park-47)"
    elif is_all:   active_label = "All valid reactions"
    elif is_clear: active_label = "(empty)"
    else:          active_label = f"Custom ({len(_curr_set)} reactions)"

    presets_row1 = st.columns(3)
    if presets_row1[0].button("AIR-5", use_container_width=True,
                              type=_btn_type_if_active(is_air5)):
        st.session_state["selected_rxn_ids"] = sorted(_air5_ids)
        st.rerun()
    if presets_row1[1].button("AIR-7", use_container_width=True,
                              type=_btn_type_if_active(is_air7)):
        st.session_state["selected_rxn_ids"] = sorted(_air7_ids)
        st.rerun()
    if presets_row1[2].button("AIR-11", use_container_width=True,
                              type=_btn_type_if_active(is_air11)):
        st.session_state["selected_rxn_ids"] = sorted(_air11_ids)
        st.rerun()

    presets_row2 = st.columns(2)
    if presets_row2[0].button("Select all", use_container_width=True,
                              type=_btn_type_if_active(is_all)):
        st.session_state["selected_rxn_ids"] = sorted(_all_valid_ids)
        st.rerun()
    if presets_row2[1].button("Clear", use_container_width=True,
                              type=_btn_type_if_active(is_clear)):
        st.session_state["selected_rxn_ids"] = []
        st.rerun()

    st.caption(f"Active mechanism:  **{active_label}**")
    st.caption("Toggle individual reactions below to make a custom mix.")

    tres_label = st.selectbox(
        "Cantera 0D residence time",
        options=["1 us", "10 us", "100 us"],
        index=2,
        help="Used only for the optional Cantera ground-truth comparison.",
    )
    tres_s = {"1 us": 1e-6, "10 us": 1e-5, "100 us": 1e-4}[tres_label]


# ─── Mechanism reaction grid (in main, full width above the predict row) ─────

with st.expander(f"Park-47 reactions  —  {len(st.session_state['selected_rxn_ids'])} selected",
                 expanded=False):
    st.caption(
        "Tags: orange = dissociation, red = ionization, "
        "green = exchange, purple = charge_transfer, gray = other / placeholder"
    )
    grid_cols = st.columns(3)
    selected_set = set(st.session_state["selected_rxn_ids"])
    new_selected = set()
    for i, r in enumerate(PARK_47.reactions):
        col = grid_cols[i % 3]
        kind = reaction_kind(r)
        color = kind_color(kind)
        is_placeholder = r.A <= 0
        # Single-line label with rxn_id, formula, kind tag.
        label_html = (
            f"#{r.rxn_id:02d}  {r.formula}  "
            f"[{kind}]"
        )
        if is_placeholder:
            label_html += "  (placeholder — A=0)"
        checked = col.checkbox(
            label_html,
            value=(r.rxn_id in selected_set),
            key=f"rxn_chk_{r.rxn_id}",
            disabled=is_placeholder,
        )
        if checked and not is_placeholder:
            new_selected.add(r.rxn_id)
    # Sync only if user edited a checkbox (avoid clobbering preset clicks).
    if new_selected != selected_set:
        st.session_state["selected_rxn_ids"] = sorted(new_selected)
        st.rerun()


# ─── Mechanism summary card ──────────────────────────────────────────────────

selected_ids = list(st.session_state["selected_rxn_ids"])
selected_reactions = [r for r in PARK_47.reactions if r.rxn_id in set(selected_ids)]
n_dissoc = sum(1 for r in selected_reactions if r.is_dissociation)
n_ion = sum(1 for r in selected_reactions if r.is_ionization)
n_exch = sum(1 for r in selected_reactions if r.is_exchange)
n_chx = sum(1 for r in selected_reactions if r.is_charge_transfer)
n_other = len(selected_reactions) - n_dissoc - n_ion - n_exch - n_chx

card_cols = st.columns(5)
card_cols[0].metric("Reactions", len(selected_reactions))
card_cols[1].metric("Dissociation", n_dissoc)
card_cols[2].metric("Ionization", n_ion)
card_cols[3].metric("Exchange", n_exch)
card_cols[4].metric("Charge xfer", n_chx)


# ─── Current selection summary (visible regardless of whether Predict was clicked) ─

_t_target_now = float(_us_standard_atmosphere_T(altitude_km))
_p_target_now = float(_us_standard_atmosphere_P(altitude_km))
_t_match_now = _matches_us_std(T_inf, _t_target_now)
_p_match_now = _matches_us_std(P_inf, _p_target_now)
_preset_match = (
    preset_bk is not None
    and abs(altitude_km - preset_bk.altitude_km) < 0.1
    and abs(mach - preset_bk.mach) < 0.05
    and _t_match_now
    and _p_match_now
)

with st.container(border=True):
    st.markdown(
        f"**Current selection** &nbsp;&nbsp; "
        f"Conditions: `{altitude_km:.1f} km`, `M={mach:.2f}`, "
        f"`T={T_inf:.2f} K`, `P={P_inf:.3f} Pa` &nbsp;&nbsp; "
        + (f"✓ matches *{preset_label}*" if _preset_match
           else (f"× custom (does NOT match *{preset_label}*)"
                 if preset_bk is not None
                 else "  (no benchmark preset selected)"))
    )
    st.markdown(
        f"**Mechanism**: `{active_label}` &nbsp;&nbsp; "
        f"({len(selected_reactions)} rxns: "
        f"{n_dissoc} dissoc, {n_ion} ion, {n_exch} exch, "
        f"{n_chx} ch-xfer, {n_other} other)"
    )

# ─── Predict button ──────────────────────────────────────────────────────────

predict_clicked = st.button("Predict ne", type="primary", use_container_width=True)


# ─── Main 2-column layout ────────────────────────────────────────────────────

left, right = st.columns([1, 1])

# Load the model lazily — only when user actually needs it.
def _try_load_model():
    try:
        if uploaded is not None:
            return load_surrogate(uploaded.getvalue())
        return load_surrogate(surrogate_path)
    except FileNotFoundError:
        st.error(
            f"Surrogate checkpoint not found at `{surrogate_path}`. "
            "Either correct the path, set $SURROGATE_PATH, or upload a .pt file."
        )
    except Exception as exc:
        st.error(f"Failed to load surrogate: {exc}")
    return None


if predict_clicked:
    if not HAVE_TORCH:
        st.error("PyTorch is not installed. `pip install torch` and reload.")
    elif len(selected_ids) == 0:
        st.warning("Select at least one reaction to make a prediction.")
    else:
        model = _try_load_model()
        if model is not None:
            with st.spinner("Running surrogate forward pass..."):
                log10_ne, ne = predict_ne(
                    model, altitude_km, mach, T_inf, P_inf, selected_ids,
                )
            db_attn = appleton_hartree_db(ne, f_hz=S_BAND_HZ, P_pa=P_inf)

            with left:
                st.subheader("Prediction")
                st.metric(
                    "Predicted log10(ne_peak)  [m^-3]",
                    f"{log10_ne:+.3f}",
                )
                st.metric(
                    "Predicted ne_peak  [m^-3]",
                    f"{ne:.3e}",
                )
                st.metric(
                    f"S-band ({S_BAND_HZ/1e9:.1f} GHz) attenuation  [dB]",
                    f"{db_attn:.1f}",
                    help="Appleton-Hartree, 0.30 m sheath path, "
                         "collision freq scaled with P_inf.",
                )
                st.caption(
                    f"Surrogate val MAE = {MODEL_VAL_MAE_LOG10:.3f} log10  "
                    f"(factor of {MODEL_FACTOR:.2f}x). "
                    f"Model parameters: {count_params(model):,}."
                )

            # Save into session state so Cantera button can reuse it.
            st.session_state["last_prediction"] = {
                "log10_ne": log10_ne, "ne": ne, "db": db_attn,
                "altitude_km": altitude_km, "mach": mach,
                "T_inf": T_inf, "P_inf": P_inf,
                "selected_ids": selected_ids,
                "preset_key": preset_key,
                "tres_s": tres_s,
            }


# ─── Right column: comparison-vs-J&C bar chart ──────────────────────────────

last = st.session_state.get("last_prediction")
with right:
    st.subheader("Comparison vs published")
    if last is None:
        st.info("Hit **Predict ne** to populate this panel.")
    else:
        bar_categories = ["PlasmaNet v4 (predicted)"]
        bar_values = [last["ne"]]
        bar_colors = ["#1f77b4"]

        if last["preset_key"] is not None:
            bk = BENCHMARKS[last["preset_key"]]
            bar_categories.append(f"J&C 1972 (measured @ {bk.altitude_km:.0f} km)")
            bar_values.append(bk.ne_published_m3)
            bar_colors.append("#ff7f0e")

        fig = go.Figure(
            data=[go.Bar(
                x=bar_categories,
                y=bar_values,
                marker_color=bar_colors,
                text=[f"{v:.2e}" for v in bar_values],
                textposition="outside",
            )]
        )
        fig.update_yaxes(type="log", title="ne [m^-3]")
        fig.update_layout(
            margin=dict(t=20, l=0, r=0, b=0),
            height=380,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        if last["preset_key"] is not None:
            bk = BENCHMARKS[last["preset_key"]]
            ratio = last["ne"] / bk.ne_published_m3 if bk.ne_published_m3 > 0 else 0
            log10_diff = (math.log10(last["ne"]) - math.log10(bk.ne_published_m3)
                          if last["ne"] > 0 and bk.ne_published_m3 > 0
                          else float("nan"))
            st.write(
                f"**Ratio (pred / measured):** {ratio:.2f}x   |   "
                f"**log10 error:** {log10_diff:+.3f}   |   "
                f"**Source:** {bk.source}"
            )


# ─── Optional Cantera ground-truth panel ─────────────────────────────────────

st.divider()
with st.expander("Cantera 0D ground truth (slow, ~50 ms)", expanded=False):
    st.caption(
        "Calls plasmanet.mechanism_search.score_candidate(evaluator='cantera_0d'). "
        "Requires Cantera installed; falls back gracefully if not. Uses the "
        "currently-selected benchmark preset."
    )
    if last is None:
        st.info("Run **Predict ne** first.")
    elif last["preset_key"] is None:
        st.warning("Select a benchmark preset (e.g. RAM-C 61 km / Mach 22.5) "
                    "to enable Cantera comparison — Cantera evaluation is "
                    "anchored to a published flight condition.")
    else:
        run_cantera = st.button("Run Cantera 0D", type="secondary")
        if run_cantera:
            try:
                from plasmanet.mechanism_search.cantera_evaluator import HAVE_CANTERA
            except Exception:
                HAVE_CANTERA = False
            if not HAVE_CANTERA:
                st.error(
                    "Cantera is not installed in this environment. "
                    "Install via `pip install cantera` or run on the VM."
                )
            else:
                # Build the subset mechanism from selected reactions.
                subset_mech = PARK_47.subset(reaction_ids=last["selected_ids"])
                with st.spinner("Running Cantera 0D reactor..."):
                    try:
                        result = score_candidate(
                            mechanism_name="streamlit_subset",
                            evaluator="cantera_0d",
                            evaluator_input={
                                "mechanism": subset_mech,
                                "residence_time_s": last["tres_s"],
                            },
                            benchmark=last["preset_key"],
                        )
                    except Exception as exc:
                        st.error(f"Cantera evaluation failed: {exc}")
                        result = None

                if result is not None and result.per_benchmark:
                    br = result.per_benchmark[0]
                    ne_truth = br.ne_predicted_m3
                    log10_truth = (math.log10(ne_truth) if ne_truth > 0
                                   else float("nan"))
                    log10_err_v_truth = (
                        math.log10(last["ne"]) - log10_truth
                        if last["ne"] > 0 and ne_truth > 0
                        else float("nan")
                    )
                    factor = (last["ne"] / ne_truth if ne_truth > 0
                              else float("nan"))

                    cmp_cols = st.columns(3)
                    cmp_cols[0].metric(
                        "Cantera 0D truth ne [m^-3]",
                        f"{ne_truth:.3e}",
                    )
                    cmp_cols[1].metric(
                        "log10 error  (pred - truth)",
                        f"{log10_err_v_truth:+.3f}",
                    )
                    cmp_cols[2].metric(
                        "Factor (pred / truth)",
                        f"{factor:.2f}x" if factor == factor else "n/a",
                    )

                    fig2 = go.Figure(
                        data=[go.Bar(
                            x=["Surrogate v4", "Cantera 0D"],
                            y=[last["ne"], ne_truth],
                            marker_color=["#1f77b4", "#2ca02c"],
                            text=[f"{last['ne']:.2e}", f"{ne_truth:.2e}"],
                            textposition="outside",
                        )]
                    )
                    fig2.update_yaxes(type="log", title="ne [m^-3]")
                    fig2.update_layout(
                        margin=dict(t=20, l=0, r=0, b=0),
                        height=320, showlegend=False,
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                elif result is not None:
                    st.warning("Cantera returned no benchmark results.")
