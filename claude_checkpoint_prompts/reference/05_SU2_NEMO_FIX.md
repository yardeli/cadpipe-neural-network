# SU2-NEMO + Mutation++ Fix

**Date:** 2026-04-23
**Status:** AIR-5 (built-in NEMO) confirmed working. AIR-11 (Mutation++) validation running.
**Closes:** Audit task C-1 (resolve SU2-NEMO segfault)

## TL;DR

Three missing config options were causing SU2 NEMO to segfault in `CNEMOGas::SetTDStatePTTv` during solver preprocessing:

1. **`FLUID_MODEL= SU2_NONEQ`** (or `MUTATIONPP`) — without this, the solver factory instantiated the wrong fluid class with unallocated NEMO-specific arrays. This was the primary bug.
2. **`GAS_COMPOSITION`** species order — SU2 built-in `AIR-5` uses the order `(N2, O2, NO, N, O)`. The Mutation++ `air_5` mixture uses `(N, O, NO, N2, O2)`. These are not interchangeable.
3. **Mutation++ data files** — `/opt/su2-nemo/mpp-data/` was empty. Mutation++ requires mixture XML files loaded from `$MPP_DATA_DIRECTORY` at runtime.

Plus two environment-level fixes for the binary to load at all:
- `LD_LIBRARY_PATH` must include `/opt/su2-nemo/lib` (where `libmutation__.so` lives)
- `MPP_DATA_DIRECTORY` must point to the data directory

Plus one Mutation++-specific limitation:
- `TIME_DISCRE_FLOW= EULER_IMPLICIT` is **not supported** with `FLUID_MODEL= MUTATIONPP` in SU2 v7.5.1. Use `EULER_EXPLICIT` instead.

## How The Bug Manifested

Running with the config used by the previous debugging attempt:

```
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.767, 0.233, 0.0, 0.0, 0.0)
MACH_NUMBER= 10.0
FREESTREAM_PRESSURE= 1171.87
FREESTREAM_TEMPERATURE= 226.65
FREESTREAM_TEMPERATURE_VE= 226.65
MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
```

Got as far as solver preprocessing, then segfault. Stack trace:

```
#0 CNEMOGas::SetTDStatePTTv(double, double const*, double, double)
#1 CNEMOEulerSolver::SetNondimensionalization(CConfig*, unsigned short)
#2 CNEMOEulerSolver::CNEMOEulerSolver(CGeometry*, CConfig*, ...)
```

## Diagnosis

Reading `SU2_CFD/src/fluid/CNEMOGas.cpp:59-81` shows the function is a simple array copy:

```cpp
void CNEMOGas::SetTDStatePTTv(su2double val_pressure, const su2double *val_massfrac,
                              su2double val_temperature, su2double val_temperature_ve) {
  for (iSpecies = 0; iSpecies < nSpecies; iSpecies++)
    MassFrac[iSpecies] = val_massfrac[iSpecies];
  Pressure = val_pressure;
  ...
}
```

A SEGV here means either `MassFrac` was not allocated or `val_massfrac` is invalid. Neither can happen if the correct `CNEMOGas` subclass (`CSU2TCLib` or `CMutationTCLib`) is instantiated by the solver factory.

Searching the binary for config options, found the following strings that were missing from our config:

```
INIT_OPTION
FREESTREAM_OPTION
INLET_GAS_COMPOSITION
TRANSPORT_COEFF_MODEL
MIXING_VISCOSITY_MODEL
NONEQUILIBRIUM_WALL_MODEL
```

And more importantly, a reference working config from `TestCases/nonequilibrium/invwedge/invwedge_lax.cfg` in the SU2 v7.5.1 source tree. Diffing my config against it revealed:

- Missing: `FLUID_MODEL= SU2_NONEQ`
- Missing: `SIDESLIP_ANGLE= 0.0` (probably not critical)
- Different numerics (WEIGHTED_LEAST_SQUARES vs GREEN_GAUSS)

Adding `FLUID_MODEL= SU2_NONEQ` resolved the segfault. The solver then ran 50 iterations to completion, wrote a ParaView VTU, and produced physically-sensible two-temperature fields:

- T_tr max: 5669 K (perfect-gas Euler would give 12,806 K at the same Mach)
- T_ve max: 3948 K
- T_tr – T_ve ≈ 1700 K — the thermal nonequilibrium signature
- Species: MassFrac_0 (N2, 77%), MassFrac_1 (O2, 23%), MassFrac_4 (O atoms, peak 1%), MassFrac_3 (N atoms, peak 0.004%), MassFrac_2 (NO, peak 0.4%)

## Root Cause Explanation

When `FLUID_MODEL` is not specified, SU2's config parser falls back to the default, which is `STANDARD_AIR` (a perfect-gas single-species class `CIdealGas`). This is compatible with `SOLVER= EULER` but **not** with `SOLVER= NEMO_EULER`. The `NEMO_EULER` solver's `SetNondimensionalization()` expects the fluid class to be a `CNEMOGas` subclass, which allocates `MassFrac[nSpecies]` and similar NEMO-specific arrays at construction. The `CIdealGas` class does not allocate these, so the pointer is null / garbage, and the first memory access segfaults.

The bug was silent because:
- `SOLVER= NEMO_EULER` is accepted without error
- `GAS_MODEL= AIR-5` with `FLUID_MODEL= STANDARD_AIR` is not flagged as a contradiction
- The mismatch only surfaces at runtime inside the solver factory

## The Working Config (AIR-5, Built-In NEMO)

```ini
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0)   # order: N2, O2, NO, N, O
MATH_PROBLEM= DIRECT
RESTART_SOL= NO

MACH_NUMBER= 10.0
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 1171.87
FREESTREAM_TEMPERATURE= 226.65
FREESTREAM_TEMPERATURE_VE= 226.65

FLUID_MODEL= SU2_NONEQ             # THE KEY LINE

MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )

NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= 1.0
ITER= 500
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.05
TIME_DISCRE_FLOW= EULER_IMPLICIT   # built-in AIR-5 supports implicit

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_RESIDUAL_MINVAL= -8
CONV_STARTITER= 10

MESH_FILENAME= mesh.su2
MESH_FORMAT= SU2
CONV_FILENAME= history_nemo
VOLUME_FILENAME= flow_nemo
OUTPUT_WRT_FREQ= 100
OUTPUT_FILES= (RESTART, PARAVIEW)
```

Species order for AIR-5 (from MassFrac_0..4 in the VTU output): `N2, O2, NO, N, O`. This is the **SU2 built-in** order, different from the Mutation++ `air_5` mixture which uses `N, O, NO, N2, O2`.

## Environment Setup (One-Time)

```bash
export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
```

Mutation++ data files (mixtures, mechanisms, thermo, transfer, transport) were installed from:

```bash
cd /tmp
git clone --depth 1 https://github.com/mutationpp/Mutationpp.git mutationpp-src
sudo mkdir -p /opt/su2-nemo/mpp-data
sudo cp -r /tmp/mutationpp-src/data/* /opt/su2-nemo/mpp-data/
sudo chmod -R a+r /opt/su2-nemo/mpp-data/
```

## AIR-11 (Mutation++) Config

For plasma prediction with electrons (our actual use case), switch to Mutation++ and the `air_11` mixture:

```ini
SOLVER= NEMO_EULER
GAS_MODEL= air_11                                                     # lowercase, XML file name
GAS_COMPOSITION= (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.77, 0.23)
#                 e-   N+   O+   NO+  N2+  O2+  N    O    NO   N2    O2
FLUID_MODEL= MUTATIONPP

TIME_DISCRE_FLOW= EULER_EXPLICIT   # MUTATIONPP does not support IMPLICIT in v7.5.1
CFL_NUMBER= 0.3                    # explicit — keep CFL low for stability
ITER= 1000                         # explicit is slow, need more iters
```

Species order for `air_11.xml` (from Mutation++): `e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2`.

## Next Steps

1. Validate `AIR-11 + MUTATIONPP` run converges and produces ne field (running now).
2. Compare NEMO ne_stag to published RAM-C II measurements (target validation case at 61 km, Mach 22.5).
3. Port the 40-case SU2 Euler batch to NEMO with AIR-11.
4. Wire NEMO output into `plasmanet/cfd_field.py::extract_cfd_field()` so `line_of_sight` integration uses real coupled-chemistry data.
5. Update the roadmap doc with timeline now that C-1 is closed.

## References

- SU2 v7.5.1 source tree: `/tmp/SU2-7.5.1` (re-downloadable from github.com/su2code/SU2/archive/refs/tags/v7.5.1.tar.gz)
- Reference working config: `TestCases/nonequilibrium/invwedge/invwedge_lax.cfg`
- Working config saved at: `openfoam-hgv:/tmp/nemo_test/nemo_m10.cfg`
- Mutation++ repo: github.com/mutationpp/Mutationpp (master branch `data/` used)
