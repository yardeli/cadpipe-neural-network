# SU2 v8.4.0 `flow.meta` Warning — Investigation and Fix

## TL;DR
The `Warning: There is no restart file (flow.meta)` message is **informational, not fatal**. It does NOT block the actual flow restart from being read. The NaN-on-iter-0 you're seeing on warm-restart is **not** caused by the missing `flow.meta` — it has a different root cause (likely a v7→v8 binary restart-format incompatibility, or species/dimension mismatch on the NEMO solver). The cfg has no key to "enable" `flow.meta` writing — v8 only writes it under two specific solver modes that are irrelevant to a NEMO inviscid Mach-22.5 cold start.

## What `flow.meta` actually is
- **Format**: ASCII text. Plain `key= value` lines.
- **Fields written** (only when written): `ITER=`, `AOA=`, `SIDESLIP_ANGLE=`, `DCD_DCL_VALUE=`, `DCMX_DCL_VALUE=`, `DCMY_DCL_VALUE=`, `DCMZ_DCL_VALUE=`, `INITIAL_BCTHRUST=`, `SENS_AOA=` (adjoint only), `STREAMWISE_PERIODIC_PRESSURE_DROP=` (streamwise periodic only).
- **Writer**: `CFlowOutput::WriteMetaData(const CConfig*)` at `/tmp/SU2-v8/SU2_CFD/src/output/CFlowOutput.cpp:2446`.
- **Reader**: `CSolver::Read_SU2_Restart_Metadata(...)` at `/tmp/SU2-v8/SU2_CFD/src/solvers/CSolver.cpp:3351`. The warning string is at line 3370 of that file.

## When does v8 write `flow.meta`?
`WriteMetaData(...)` is invoked from exactly two sites, both in `CFlowOutput.cpp`:

1. `CFlowOutput::WriteAdditionalFiles(...)` — line 2433. Triggered ONLY when:
   ```cpp
   if (config->GetFixed_CL_Mode() ||
       (config->GetKind_Streamwise_Periodic() == ENUM_STREAMWISE_PERIODIC::MASSFLOW)) {
     WriteMetaData(config);
   }
   ```
2. The Fixed-CL finite-difference branch — line 4134, also gated by `Fixed_CL_Mode`.

**There is no `OUTPUT_TYPE::META` or general "write meta" cfg switch.** Inspection of `OUTPUT_TYPE` (`/tmp/SU2-v8/Common/include/option_structure.hpp:2181`) shows the only restart entries are `RESTART_BINARY` and `RESTART_ASCII`. Inspection of `OUTPUT_FILES` registration (`Common/src/CConfig.cpp:3027`) confirms `META` is not a valid token. So nothing in the cfg can be flipped to make a NEMO Euler M22.5 case write `flow.meta` — the writer is statically gated.

## What the missing `flow.meta` actually does
Looking at `Read_SU2_Restart_Metadata` (`CSolver.cpp:3351-3500`):
- The function opens the file. If `restart_file.fail()`, it prints the warning and **falls through to the "load metadata" block using the local defaults that were initialized from `config->GetAoA()`, `config->GetAoS()`, `config->GetInitial_BCThrust()`, etc.**
- These defaults equal whatever is already in your cfg (`AOA= 0.0`, etc.).
- The function then re-applies them to the config (no-op when they match).
- **The function never touches the conserved/primitive flow field.** Field data is read separately by `Read_SU2_Restart_Binary` / `Read_SU2_Restart_ASCII` (`CSolver.cpp:2754, 2916`).
- The CIncNSSolver source even has a comment confirming the design intent at `/tmp/SU2-v8/SU2_CFD/src/solvers/CIncNSSolver.cpp:59`: `// Note during restarts, the flow.meta is read first. But that sets the cfg-value so we are good here.`

So: the missing `flow.meta` cannot zero out or NaN-out your field. It only loses you AoA-offset / BCThrust / streamwise pressure-drop continuity, all of which are zero / inactive in your inviscid AIR-7 case.

## The 1-line cfg patch
**There is no clean cfg patch that gets v8 to write `flow.meta` for a plain NEMO Euler case** — the writer is hard-gated to `FIXED_CL_MODE= YES` or `KIND_STREAMWISE_PERIODIC= MASSFLOW`. Both are wrong for an external hypersonic blunt-body run.

If you want to suppress the warning purely cosmetically, hand-create a stub `flow.meta` next to `solution.dat`:
```
ITER= 0
AOA= 0.0
SIDESLIP_ANGLE= 0.0
INITIAL_BCTHRUST= 0.0
```
Then the reader takes the "found" branch and silently re-applies these (which match your cfg already). No SU2 source modification needed.

## What the actual NaN root cause likely is
Since `flow.meta` is a red herring, look elsewhere:
1. **v7→v8 restart binary format mismatch.** `Read_SU2_Restart_Binary` (`CSolver.cpp:2916`) reads a header containing `nFields`, `nPointDomain`, MPI partition count, etc. If the v7 file's field layout doesn't match what v8's NEMO solver expects (e.g., different species count, primitive ordering, vibrational-energy variable position), values will load into the wrong slots and integration on iter 0 produces NaN.
2. **AIR-7 species ordering changed**: per project memory, v8's NEMO uses 7-species `[e-, N2, O2, NO, N, O, NO+]` order. If the source restart was from v7 (AIR-11) or had a different species composition, the conserved-variable vector layout is incompatible.
3. **Action**: dump the binary header of the source `restart.dat` (first 5 ints + `nFields*nPointDomain` doubles) and compare to what v8 NEMO expects (`nVar = nSpecies + nDim + 2 = 7 + 3 + 2 = 12` for 3D AIR-7). If `nFields` doesn't match, the restart is incompatible and you must run cold or re-export with v8.

## Action items
1. **Ignore the `flow.meta` warning.** It is benign and does not cause NaN.
2. **Inspect the source `restart.dat` header** to verify `nFields == 12` (3D AIR-7) and `nPointDomain` matches the new mesh.
3. **If species/dim mismatch**, the warm-restart is fundamentally impossible from the v7 file — must run cold (which you're already doing in `/home/yarden/ram_c_runs/v8_air7_M22_5/`) and warm-restart future runs from this v8 `restart.dat`.
4. **Optional cosmetic fix**: drop a stub `flow.meta` in the run directory to silence the warning (content shown above).

## File references (all on GCP VM `openfoam-hgv:/tmp/SU2-v8/`)
- `SU2_CFD/src/output/CFlowOutput.cpp:2433` — write trigger (Fixed_CL or streamwise massflow only)
- `SU2_CFD/src/output/CFlowOutput.cpp:2446` — `WriteMetaData` body
- `SU2_CFD/src/solvers/CSolver.cpp:3351` — `Read_SU2_Restart_Metadata` body
- `SU2_CFD/src/solvers/CSolver.cpp:3370` — the warning print
- `SU2_CFD/src/solvers/CIncNSSolver.cpp:59` — confirming comment
- `SU2_CFD/src/solvers/CNEMOEulerSolver.cpp:87` — NEMO caller
- `Common/include/option_structure.hpp:2181` — `OUTPUT_TYPE` enum (no META entry)
- `Common/src/CConfig.cpp:3027` — `OUTPUT_FILES` registration
- `Common/src/CConfig.cpp:1477` — `FIXED_CL_MODE` cfg key
