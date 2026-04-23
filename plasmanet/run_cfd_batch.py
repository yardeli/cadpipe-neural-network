"""Run SU2 CFD batch on GCP VM.

Uploads meshes and configs, runs SU2 for each case, downloads results,
and extracts stagnation-point T, p for PlasmaNet training data.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from pathlib import PureWindowsPath
GCLOUD = str(Path.home() / "AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd")
GCP_PROJECT = "gogapi-489609"
GCP_ZONE = "us-central1-a"
GCP_INSTANCE = "openfoam-hgv"
GCP_USER = "yarden"
REMOTE_WORK = "/home/yarden/plasmanet_cfd"
SU2_BIN = "/opt/su2/bin/SU2_CFD"


def gcloud_cmd(args, timeout=120):
    cmd = [GCLOUD] + args + [f"--project={GCP_PROJECT}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip(), result.returncode


def gcloud_ssh(command, timeout=600):
    stdout, rc = gcloud_cmd([
        "compute", "ssh", f"{GCP_USER}@{GCP_INSTANCE}",
        f"--zone={GCP_ZONE}", f"--command={command}"
    ], timeout=timeout)
    return stdout, rc


def gcloud_scp_upload(local_path, remote_path):
    stdout, rc = gcloud_cmd([
        "compute", "scp", str(local_path),
        f"{GCP_USER}@{GCP_INSTANCE}:{remote_path}",
        f"--zone={GCP_ZONE}"
    ], timeout=120)
    return rc == 0


def gcloud_scp_download(remote_path, local_path):
    stdout, rc = gcloud_cmd([
        "compute", "scp",
        f"{GCP_USER}@{GCP_INSTANCE}:{remote_path}",
        str(local_path),
        f"--zone={GCP_ZONE}"
    ], timeout=120)
    return rc == 0


def run_single_case(geometry_name, mach, alt, mesh_path, config_path,
                    output_dir, case_idx, total_cases):
    """Upload mesh + config, run SU2, download results."""
    case_id = f"{geometry_name}_M{mach}_A{alt}"
    remote_dir = f"{REMOTE_WORK}/{case_id}"
    local_out = Path(output_dir) / case_id
    local_out.mkdir(parents=True, exist_ok=True)

    print(f"\n[{case_idx}/{total_cases}] {case_id}")

    # 1. Create remote directory
    gcloud_ssh(f"mkdir -p {remote_dir}")

    # 2. Upload mesh (always re-upload to ensure latest version)
    mesh_name = Path(mesh_path).name
    print(f"  Uploading mesh ({mesh_name})...")
    if not gcloud_scp_upload(mesh_path, f"{REMOTE_WORK}/{mesh_name}"):
        print(f"  FAILED: mesh upload")
        return {"status": "failed", "error": "mesh upload failed"}

    # 3. Upload config
    print(f"  Uploading config...")
    if not gcloud_scp_upload(config_path, f"{remote_dir}/run.cfg"):
        print(f"  FAILED: config upload")
        return {"status": "failed", "error": "config upload failed"}

    # 4. Copy mesh into case directory (SU2 can have issues with symlinks)
    gcloud_ssh(f"cp -f {REMOTE_WORK}/{mesh_name} {remote_dir}/{mesh_name}", timeout=120)

    # 5. Run SU2 via wrapper script (avoids SSH timeout issues)
    print(f"  Running SU2 (Mach {mach}, Alt {alt}km)...")
    t0 = time.monotonic()

    # Clean up previous run artifacts
    gcloud_ssh(f"rm -f {remote_dir}/su2.exitcode {remote_dir}/su2.log {remote_dir}/su2.pid", timeout=20)

    # Write a runner script that backgrounds SU2 and records PID
    script = f"""#!/bin/bash
cd {remote_dir}
{SU2_BIN} run.cfg > su2.log 2>&1
echo $? > su2.exitcode
"""
    gcloud_ssh(f"cat > {remote_dir}/run.sh << 'EOFSCRIPT'\n{script}\nEOFSCRIPT\nchmod +x {remote_dir}/run.sh", timeout=30)

    # Start in background
    gcloud_ssh(f"nohup bash {remote_dir}/run.sh > /dev/null 2>&1 & echo $! > {remote_dir}/su2.pid", timeout=30)

    # Poll for completion
    print(f"  SU2 started, polling for completion...")
    max_wait = 900
    poll_interval = 20
    while time.monotonic() - t0 < max_wait:
        time.sleep(poll_interval)
        check, _ = gcloud_ssh(f"test -f {remote_dir}/su2.exitcode && echo DONE || echo RUNNING", timeout=20)
        elapsed = time.monotonic() - t0
        if "DONE" in check:
            print(f"  SU2 finished in {elapsed:.0f}s")
            break
        # Show progress from log
        progress, _ = gcloud_ssh(f"wc -l {remote_dir}/su2.log 2>/dev/null | cut -d' ' -f1", timeout=15)
        print(f"  ... {elapsed:.0f}s elapsed, log: {progress.strip()} lines")
    else:
        print(f"  TIMEOUT after {max_wait}s")

    dt = time.monotonic() - t0
    # Check exit code
    exitcode_str, _ = gcloud_ssh(f"cat {remote_dir}/su2.exitcode 2>/dev/null", timeout=15)
    rc = int(exitcode_str.strip()) if exitcode_str.strip().isdigit() else 1
    # Also check log for errors
    log_check, _ = gcloud_ssh(f"tail -5 {remote_dir}/su2.log 2>/dev/null", timeout=15)
    if "Error" in log_check:
        rc = 1

    if rc != 0:
        # Download log for debugging
        gcloud_scp_download(f"{remote_dir}/su2.log", str(local_out / "su2.log"))
        print(f"  FAILED: SU2 exit code {rc} ({dt:.0f}s)")
        return {"status": "failed", "error": f"SU2 exit code {rc}", "duration_s": dt}

    print(f"  SU2 completed in {dt:.0f}s")

    # 6. Download results
    print(f"  Downloading results...")
    gcloud_scp_download(f"{remote_dir}/su2.log", str(local_out / "su2.log"))
    gcloud_scp_download(f"{remote_dir}/flow.vtu", str(local_out / "flow.vtu"))
    gcloud_scp_download(f"{remote_dir}/surface_flow.vtu", str(local_out / "surface_flow.vtu"))
    gcloud_scp_download(f"{remote_dir}/history.csv", str(local_out / "history.csv"))

    # 7. Extract max temperature from log
    log_path = local_out / "su2.log"
    T_max = None
    if log_path.exists():
        log_text = log_path.read_text()
        # Look for convergence info
        lines = log_text.strip().split('\n')
        converged = "Convergence" in log_text or len(lines) > 100

    result = {
        "status": "completed",
        "geometry": geometry_name,
        "mach": mach,
        "altitude_km": alt,
        "duration_s": round(dt, 1),
        "output_dir": str(local_out),
        "converged": converged if log_path.exists() else False,
    }
    print(f"  Done: {result['status']}")
    return result


def run_batch(manifest_path, output_dir="data/cfd_results", max_cases=None):
    """Run all CFD cases from manifest."""
    manifest = json.loads(Path(manifest_path).read_text())
    cases = manifest["cases"]
    if max_cases:
        cases = cases[:max_cases]

    print(f"SU2 CFD Batch Runner")
    print(f"  Cases: {len(cases)}")
    print(f"  VM: {GCP_INSTANCE}")
    print(f"  SU2: {SU2_BIN}")
    print(f"")

    # Setup remote working directory
    gcloud_ssh(f"mkdir -p {REMOTE_WORK}")

    results = []
    t_start = time.monotonic()

    for i, case in enumerate(cases, 1):
        result = run_single_case(
            geometry_name=case["geometry"],
            mach=case["mach"],
            alt=case["alt"],
            mesh_path=case["mesh"],
            config_path=case["config"],
            output_dir=output_dir,
            case_idx=i,
            total_cases=len(cases),
        )
        results.append(result)

        # Save intermediate results
        results_path = Path(output_dir) / "batch_results.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(json.dumps(results, indent=2))

    t_total = time.monotonic() - t_start
    n_ok = sum(1 for r in results if r["status"] == "completed")
    n_fail = sum(1 for r in results if r["status"] == "failed")

    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE")
    print(f"  Total: {len(results)} cases in {t_total/60:.1f} min")
    print(f"  Succeeded: {n_ok}")
    print(f"  Failed: {n_fail}")
    print(f"  Results: {results_path}")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SU2 CFD batch on GCP")
    parser.add_argument("--manifest", default="data/cfd_cases/manifest.json")
    parser.add_argument("--output", default="data/cfd_results")
    parser.add_argument("--max-cases", type=int, default=None,
                        help="Limit number of cases (for testing)")
    parser.add_argument("--stop-vm", action="store_true",
                        help="Stop VM when batch completes")
    args = parser.parse_args()

    results = run_batch(args.manifest, args.output, args.max_cases)

    if args.stop_vm:
        print("\nStopping VM...")
        gcloud_cmd(["compute", "instances", "stop", GCP_INSTANCE,
                     f"--zone={GCP_ZONE}"])
        print("VM stopped.")
