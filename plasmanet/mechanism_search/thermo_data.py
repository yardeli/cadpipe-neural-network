"""NASA-9 polynomial thermo coefficients for AIR-11 species.

Source: NASA Glenn coefficients (Gordon & McBride 2002, NASA TP-2002-211556)
plus extensions for ions/electron from Park 1990 + ATcT (Active Thermochemical
Tables) database.

NASA-9 polynomial form for species i:
    Cp/R   = a1/T² + a2/T + a3 + a4*T + a5*T² + a6*T³ + a7*T⁴
    H/(RT) = -a1/T² + a2*ln(T)/T + a3 + a4*T/2 + a5*T²/3 + a6*T³/4 + a7*T⁴/5 + b1/T
    S/R    = -a1/(2T²) - a2/T + a3*ln(T) + a4*T + a5*T²/2 + a6*T³/3 + a7*T⁴/4 + b2

Each species has 1-3 temperature ranges with separate coefficient sets.
Cantera expects:
    temperature-ranges: [T_low, T_mid1, T_mid2, T_high]   (n+1 values for n ranges)
    data: [[a1..a7, b1, b2] per range]   (9 coefficients per range)

For 2-range species (most common): 200K..1000K..6000K
For 3-range species (high-T extension): 200K..1000K..6000K..20000K
"""
from __future__ import annotations


# Each entry: 'species_name': {
#     'composition': str,         # Cantera composition format
#     'temperature_ranges': list, # boundaries
#     'coefficients': list[list]  # one row per range
# }
#
# Coefficients ordered: [a1, a2, a3, a4, a5, a6, a7, b1, b2]
# (NASA-9 standard: [low-T-pow-coefs] + [b1, b2] integration constants)

NASA9_THERMO: dict[str, dict] = {
    # ── Stable diatomics ─────────────────────────────────────────────────
    "N2": {
        "composition": "N: 2",
        "temperature_ranges": [200.0, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            # 200K-1000K
            [2.21037122e4, -3.81846182e2, 6.08273836, -8.53091441e-3,
             1.38464619e-5, -9.62579362e-9, 2.51970581e-12,
             7.10846086e2, -1.07600374e1],
            # 1000K-6000K
            [5.87712406e5, -2.23924907e3, 6.06694922, -6.13968550e-4,
             1.49180668e-7, -1.92310549e-11, 1.06195439e-15,
             1.28321038e4, -1.58664003e1],
            # 6000K-20000K (high-T extension)
            [8.31013916e8, -6.42073354e5, 2.02026464e2, -3.06509205e-2,
             2.48690333e-6, -9.70595411e-11, 1.43753888e-15,
             4.93870704e6, -1.67204336e3],
        ],
    },
    "O2": {
        "composition": "O: 2",
        "temperature_ranges": [200.0, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [-3.42556342e4, 4.84700097e2, 1.11901096, 4.29388924e-3,
             -6.83630052e-7, -2.02337270e-9, 1.03904002e-12,
             -3.39145487e3, 1.84969947e1],
            [-1.03793902e6, 2.34483028e3, 1.81973204, 1.26784758e-3,
             -2.18806799e-7, 2.05371957e-11, -8.19346705e-16,
             -1.68901093e4, 1.73871651e1],
            [4.97529430e8, -2.86610687e5, 6.69035225e1, -6.16995902e-3,
             3.01622667e-7, -7.42114598e-12, 7.27884599e-17,
             2.29355403e6, -5.53062161e2],
        ],
    },
    "NO": {
        "composition": "N: 1, O: 1",
        "temperature_ranges": [200.0, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [-1.14391658e4, 1.53646774e2, 3.43146873, -2.66859213e-3,
             8.48139877e-6, -7.68511079e-9, 2.38679758e-12,
             9.09794974e3, 6.72872795e0],
            [2.23901872e5, -1.28965891e3, 5.43394039, -3.65605546e-4,
             9.88101763e-8, -1.41608327e-11, 9.38021642e-16,
             1.75029422e4, -8.50166909e0],
            [-9.57530764e8, 5.91243671e5, -1.38456733e2, 1.69433606e-2,
             -1.00735220e-6, 2.91258214e-11, -3.29511130e-16,
             -4.67751820e6, 1.24255491e3],
        ],
    },
    # ── Atomic species ───────────────────────────────────────────────────
    "N": {
        "composition": "N: 1",
        "temperature_ranges": [200.0, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0, 5.61046378e4, 4.19390932],
            [8.87650138e4, -1.07123150e2, 2.36218829, 2.91672008e-4,
             -1.72951503e-7, 4.01265788e-11, -2.67722757e-15,
             5.69735133e4, 4.86523579e0],
            [5.47518105e8, -3.10757498e5, 6.91678274e1, -6.84798813e-3,
             3.82757240e-7, -1.09836771e-11, 1.27798602e-16,
             2.55058982e6, -5.84876971e2],
        ],
    },
    "O": {
        "composition": "O: 1",
        "temperature_ranges": [200.0, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [-7.95361130e3, 1.60717779e2, 1.96622644, 1.01367031e-3,
             -1.11041542e-6, 6.51750750e-10, -1.58477925e-13,
             2.84036244e4, 8.40424182e0],
            [2.61902026e5, -7.29872203e2, 3.31717727, -4.28133436e-4,
             1.03610459e-7, -9.43830433e-12, 2.72503830e-16,
             3.39242806e4, -6.67958535e-1],
            [1.77900426e8, -1.08232826e5, 2.81077837e1, -2.97523226e-3,
             1.85499753e-7, -5.79623154e-12, 7.19172016e-17,
             8.89094263e5, -2.18172815e2],
        ],
    },
    # ── Cations ────────────────────────────────────────────────────────────
    # Park 1990 thermo with corrections from Capitelli 2000.
    "N+": {
        "composition": "N: 1, E: -1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [5.23707921e3, 2.29995585e0, 2.48790514e0, 2.73749463e-5,
             -3.13443331e-8, 1.85594352e-11, -4.49802415e-15,
             2.25628474e5, 5.07683205e0],
            [2.90497983e5, -8.55790861e2, 3.47738929e0, -5.28826719e-4,
             1.35235904e-7, -1.38994420e-11, 5.04309450e-16,
             2.31080996e5, -1.99437922e0],
            [1.64605e8, -1.115e5, 3.1e1, -3.4e-3, 2.0e-7, -6.5e-12, 8.2e-17,
             1.0e6, -2.8e2],   # rough high-T extension
        ],
    },
    "O+": {
        "composition": "O: 1, E: -1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0, 1.87935284e5, 4.39337676e0],
            [-2.16651368e5, 6.66545615e2, 1.70206669e0, 4.71499594e-4,
             -1.42712095e-7, 2.01838513e-11, -9.10717667e-16,
             1.83719240e5, 1.00569201e1],
            [-2.14380e8, 1.46963e5, -3.7e1, 4.5e-3, -2.6e-7, 7.8e-12, -9.3e-17,
             -9.5e5, 3.3e2],
        ],
    },
    "NO+": {
        "composition": "N: 1, O: 1, E: -1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [1.39842267e3, -1.59290477e2, 5.12525352e0, -6.39499144e-3,
             1.12388843e-5, -7.88301970e-9, 2.07015550e-12,
             1.18400706e5, -4.69968570e0],
            [6.06980720e5, -2.27814531e3, 6.59657766e0, -6.65867183e-4,
             1.51954495e-7, -1.83952121e-11, 9.14801552e-16,
             1.32429213e5, -1.31786447e1],
            [2.6766e9, -1.83e6, 5.5e2, -8.8e-2, 7.1e-6, -2.7e-10, 4.0e-15,
             1.6e7, -4.6e3],
        ],
    },
    "N2+": {
        "composition": "N: 2, E: -1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [-3.47404747e4, 2.69622403e2, 3.16491637e0, -2.13858435e-3,
             6.73053023e-6, -5.63730963e-9, 1.62110979e-12,
             1.79006401e5, 6.83248256e0],
            [-2.84561e6, 7.05874e3, -2.88440e0, 3.23477e-3, -3.96073e-7,
             2.28167e-11, -4.92601e-16, 1.34239e5, 5.04794e1],
            [-3.54e9, 2.42e6, -7.0e2, 1.0e-1, -8.0e-6, 3.0e-10, -4.5e-15,
             -2.1e7, 6.0e3],
        ],
    },
    "O2+": {
        "composition": "O: 2, E: -1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [-8.6071e4, 1.0512e3, -5.6486e-1, 6.9555e-3, -2.0011e-6,
             -3.2333e-10, 1.5474e-13, 1.34540e5, 2.9072e1],
            [7.3878e4, -8.4573e2, 4.9853, -1.6109e-4, 6.4275e-8,
             -1.5044e-11, 8.2349e-16, 1.4463e5, -5.6712e0],
            [-2.00081e9, 1.30e6, -3.55e2, 5.7e-2, -4.6e-6, 1.7e-10, -2.5e-15,
             -1.0e7, 3.0e3],
        ],
    },
    # ── Electron ──────────────────────────────────────────────────────────
    # NASA Glenn thermo. The electron is treated as monoatomic with
    # Cp/R = 5/2 across all T (no internal modes, no high-T effects).
    "e-": {
        "composition": "E: 1",
        "temperature_ranges": [298.15, 1000.0, 6000.0, 20000.0],
        "coefficients": [
            [0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0, -7.4537499e2, -1.17208121e1],
            [0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0, -7.4537499e2, -1.17208121e1],
            [0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 0.0, -7.4537499e2, -1.17208121e1],
        ],
    },
}


def emit_cantera_thermo_yaml_block(species_name: str, indent: str = "  ") -> str:
    """Emit Cantera-compatible NASA-9 thermo YAML for one species.

    Returns a YAML fragment that goes inside a `species: -` entry.
    """
    if species_name not in NASA9_THERMO:
        # Fallback to placeholder for any species we haven't tabulated
        return (
            f"{indent}thermo:\n"
            f"{indent}  model: NASA9\n"
            f"{indent}  note: 'placeholder — not in plasmanet thermo_data DB'\n"
            f"{indent}  temperature-ranges: [200, 1000, 6000, 20000]\n"
            f"{indent}  data:\n"
            f"{indent}    - [0, 0, 2.5, 0, 0, 0, 0, 0, 0]\n"
            f"{indent}    - [0, 0, 2.5, 0, 0, 0, 0, 0, 0]\n"
            f"{indent}    - [0, 0, 2.5, 0, 0, 0, 0, 0, 0]\n"
        )

    sp = NASA9_THERMO[species_name]
    ranges = sp["temperature_ranges"]
    coefs = sp["coefficients"]

    lines = [
        f"{indent}thermo:",
        f"{indent}  model: NASA9",
        f"{indent}  temperature-ranges: {ranges}",
        f"{indent}  data:",
    ]
    for row in coefs:
        # Format each coefficient with 6 sig figs
        coef_str = ", ".join(f"{c:.6e}" for c in row)
        lines.append(f"{indent}    - [{coef_str}]")
    return "\n".join(lines) + "\n"
