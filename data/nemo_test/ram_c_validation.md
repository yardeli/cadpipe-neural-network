# RAM-C II NEMO validation — 22.5 Mach @ 61.0 km

## Stagnation

| Quantity | Value |
|---|---|
| T_tr (K) | 6064 |
| T_ve (K) | 5911 |
| p_stag (Pa) | 2.31e+05 |
| ne_stag (m^-3) | 5.64e+20 |

## Peak sheath ne vs published

| | Value | Source |
|---|---|---|
| NEMO prediction | 6.46e+20 m^-3 | this run |
| Published reference | 2.00e+19 m^-3 (range 1.0e+19-4.0e+19) | Jones & Cross 1972 |
| log10 error | +1.51 | |

## Reflectometer-frequency LOS attenuation

| Band | Freq (GHz) | Min-Max atten (dB) | NEMO worst | Published | Match |
|---|---|---|---|---|---|
| VHF_225 | 0.23 | 82.4-317.5 | BLACKOUT | BLACKOUT | OK |
| VHF_450 | 0.45 | 117.0-453.0 | BLACKOUT | BLACKOUT | OK |
| X_band | 9.20 | 572.7-2219.0 | BLACKOUT | BLACKOUT | OK |
| Ku_band | 12.00 | 654.3-2452.2 | BLACKOUT | - | MISS |