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
| NEMO prediction (robust, top-50 mean) | 2.41e+20 m^-3 | this run |
| NEMO single-cell max | 6.46e+20 m^-3 (spike 2.68x) | this run |
| Published reference | 2.00e+19 m^-3 (range 1.0e+19-4.0e+19) | Jones & Cross 1972 |
| log10 error (robust) | +1.08 | |

## ne profile along reflectometer stations

| z/L | z (m) | r_wall (m) | sheath cells | nonzero ne | max ne | p99 ne | max T_tr |
|---|---|---|---|---|---|---|---|
| 0.14 | 0.356 | 0.186 | 7 | 4 | 9.29e+08 | 9.05e+08 | 1916 |
| 0.32 | 0.813 | 0.259 | 3 | 0 | 0.00e+00 | 0.00e+00 | 1317 |
| 0.48 | 1.219 | 0.323 | 6 | 0 | 0.00e+00 | 0.00e+00 | 1063 |
| 0.67 | 1.702 | 0.400 | 4 | 0 | 0.00e+00 | 0.00e+00 | 866 |
| 0.88 | 2.235 | 0.484 | 3 | 0 | 0.00e+00 | 0.00e+00 | 773 |

## Reflectometer-frequency LOS attenuation

| Band | Freq (GHz) | Min-Max atten (dB) | NEMO worst | Published | Match |
|---|---|---|---|---|---|
| VHF_225 | 0.23 | 82.4-317.5 | BLACKOUT | BLACKOUT | OK |
| VHF_450 | 0.45 | 117.0-453.0 | BLACKOUT | BLACKOUT | OK |
| X_band | 9.20 | 572.7-2219.0 | BLACKOUT | BLACKOUT | OK |
| Ku_band | 12.00 | 654.3-2452.2 | BLACKOUT | - | MISS |