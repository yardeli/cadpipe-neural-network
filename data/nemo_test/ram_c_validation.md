# RAM-C II NEMO validation — 22.5 Mach @ 61.0 km

## Stagnation

| Quantity | Value |
|---|---|
| T_tr (K) | 6395 |
| T_ve (K) | 6248 |
| p_stag (Pa) | 2.31e+05 |
| ne_stag (m^-3) | 7.47e+20 |

## Peak sheath ne vs published

| | Value | Source |
|---|---|---|
| **NEMO sheath peak (best station, z/L=0.14)** | **5.17e+17 m^-3** | **apples-to-apples vs J&C** |
| Published reference (J&C 1972 reflectometer) | 2.00e+19 m^-3 (range 1.0e+19-4.0e+19) | Jones & Cross 1972 |
| **log10 error (sheath peak vs J&C)** | **-1.59** | |
| (diagnostic) NEMO domain peak — at stagnation, not what J&C measured | 1.71e+21 m^-3 (top-50 mean) | informational only |
| (diagnostic) NEMO domain single-cell max | 3.37e+21 m^-3 | informational only |

## ne profile along reflectometer stations

| z/L | z (m) | r_wall (m) | sheath cells | nonzero ne | max ne | p99 ne | max T_tr |
|---|---|---|---|---|---|---|---|
| 0.14 | 0.356 | 0.186 | 2433 | 1717 | 6.96e+17 | 5.17e+17 | 4043 |
| 0.32 | 0.813 | 0.259 | 1810 | 1042 | 2.46e+14 | 1.88e+14 | 2824 |
| 0.48 | 1.219 | 0.323 | 2117 | 993 | 5.40e+11 | 3.92e+11 | 2323 |
| 0.67 | 1.702 | 0.400 | 5028 | 0 | 0.00e+00 | 0.00e+00 | 1847 |
| 0.88 | 2.235 | 0.484 | 2968 | 0 | 0.00e+00 | 0.00e+00 | 1443 |

## Reflectometer-frequency LOS attenuation

| Band | Freq (GHz) | Min-Max atten (dB) | NEMO worst | Published | Match |
|---|---|---|---|---|---|
| VHF_225 | 0.23 | 86.1-657.4 | BLACKOUT | BLACKOUT | OK |
| VHF_450 | 0.45 | 122.3-932.3 | BLACKOUT | BLACKOUT | OK |
| X_band | 9.20 | 605.4-4271.2 | BLACKOUT | BLACKOUT | OK |
| Ku_band | 12.00 | 693.9-4908.1 | BLACKOUT | - | MISS |