# PlasmaNet v4 — Hypersonic Plasma ne Surrogate UI

Streamlit web UI for the trained PlasmaNet v4 mechanism-conditioned surrogate.
A hypersonics engineer drops in flight conditions + picks reactions from
Park-47, hits **Predict**, and gets:

- Predicted `log10(ne_peak)` and `ne_peak` (m^-3)
- S-band (5.7 GHz) attenuation estimate via Appleton-Hartree
- Predicted vs J&C 1972 RAM-C reference (when a benchmark preset is active)
- Optional Cantera 0D ground-truth comparison + factor-of-X log10 error

## Files

| File | Purpose |
| --- | --- |
| `streamlit_app.py` | Main UI |
| `requirements.txt` | Pip pins (no Cantera; UI degrades gracefully if absent) |
| `README.md` | This file |

## Architecture

The app reuses the live `plasmanet.mechanism_search` module. It does **not**
redefine the model architecture. It instantiates:

```python
MechanismSurrogate(freestream_dim=4, mechanism_dim=47,
                   hidden_dim=512, n_layers=4)
```

then calls `load_state_dict(...)` on the v4 checkpoint. The 51-d input vector
is built via `freestream_features(...)` + `MechanismFingerprint(...).to_array()`
exactly like the training pipeline.

## Run locally

```bash
cd <repo-root>            # the directory that contains the `plasmanet/` package
pip install -r apps/surrogate_ui/requirements.txt
PYTHONPATH=. streamlit run apps/surrogate_ui/streamlit_app.py
```

If your trained checkpoint is local, either:

- set `SURROGATE_PATH=/abs/path/to/surrogate_v4.pt` in the environment, or
- paste the path in the sidebar text field, or
- upload the `.pt` file directly via the sidebar uploader.

## Run on the GCP VM (with port-forward)

The trained v4 model lives at `/home/yarden/mechanism_search_results/surrogate_v4.pt`
on `openfoam-hgv` (us-central1-a). Forward port 8501 to your laptop:

```bash
gcloud compute ssh openfoam-hgv --zone=us-central1-a -- -L 8501:localhost:8501
```

Inside the VM session:

```bash
cd /home/yarden/plasmanet
PYTHONPATH=. streamlit run apps/surrogate_ui/streamlit_app.py
```

Then open `http://localhost:8501` on your laptop.

To detach cleanly so the Streamlit server keeps running after you log out
(see `reference_gcloud_ssh_background.md`):

```bash
setsid bash -c "cd /home/yarden/plasmanet && PYTHONPATH=. \
    nohup streamlit run apps/surrogate_ui/streamlit_app.py \
    > ~/streamlit.log 2>&1 < /dev/null &"
```

## Configuring the model path

| Method | How |
| --- | --- |
| Env var | `export SURROGATE_PATH=/home/yarden/mechanism_search_results/surrogate_v4.pt` |
| Sidebar text | Override at runtime in the "Surrogate checkpoint path" field |
| File upload | Drop a `.pt` into the "...or upload a .pt checkpoint" widget |

The app loads the model exactly once per session via `@st.cache_resource`. The
checkpoint loader unwraps `state_dict` / `model_state_dict` if the file was
saved as a wrapped dict.

## Mechanism selection

The Park-47 grid lives in a collapsible `Park-47 reactions` panel. Each
reaction is a checkbox with `[kind]` tag (dissociation / ionization / exchange
/ charge_transfer / other). Reactions 41-47 are placeholder (A=0) and disabled
in the UI. The sidebar has preset buttons for AIR-5 / AIR-7 / AIR-11 /
Select all / Clear that overwrite the active set.

## Cantera ground-truth (optional)

Click "Run Cantera 0D" inside the bottom expander to call
`score_candidate(evaluator='cantera_0d', ...)` on the currently-selected
mechanism subset against the active benchmark preset. The UI shows surrogate
vs Cantera ne side-by-side and reports the log10 error. If Cantera is not
installed locally the button is gated with a friendly error.

## Caveats

- `BatchNorm1d` uses running statistics in `eval()` mode, so single-sample
  inference is well-defined. Don't switch the model back to `train()`.
- The Appleton-Hartree S-band estimate uses a fixed 0.30 m sheath path; for a
  real attenuation prediction use the full `score_candidate` path with a
  `VehicleGeometry`.
- Cantera evaluation is anchored to a published flight condition (it goes
  through `score_candidate(benchmark=...)`), so the Cantera button is only
  enabled when a benchmark preset is selected.
- v4 metadata (`val MAE = 0.183 log10`, factor of 1.52x, ~530K params) is
  hard-coded in the subtitle; update if you retrain.
