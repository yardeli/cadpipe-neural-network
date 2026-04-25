"""KhoriumBackend webhook — notifies /api/plasma/simulation_complete on job end.

Triggered by EventBridge on Batch Job State Change (SUCCEEDED | FAILED).

Resolution of simulation_id (self-healing — no firm caller contract required):

  1. If detail["jobName"] matches the canonical UUID format
     (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx), use it directly. Fast path —
     zero AWS calls. This matches the recommended caller convention where
     KhoriumBackend.submit_cfd passes the plasma_analyses.id as both
     jobName and parameters["simulation_id"].

  2. Otherwise, call batch.describe_jobs(jobs=[detail["jobId"]]) and look
     for "simulation_id" in the job's parameters dict, then in tags.
     This handles legacy callers, manual batch.submitJob calls, or job
     names like "submit-foo-123" / "retry-<n>".

  3. If neither path resolves a UUID, log a warning and POST with
     simulation_id=null. KhoriumBackend will record the completion event
     so an operator can correlate by hand from the batch_job_id.

Dependencies
------------
boto3 is bundled with the AWS Lambda python3.11 managed runtime — no
requirements.txt change needed. The import is deferred to the fallback
path so the UUID fast path stays import-cheap.

Environment variables
---------------------
KHORIUM_BACKEND_URL   Base URL of KhoriumBackend, e.g. https://api.khorium.ai.
                      If empty the function logs a warning and exits
                      successfully (allows deploy before the backend
                      endpoint exists).
WEBHOOK_PATH          Path to POST to. Default: /api/plasma/simulation_complete
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

# Canonical 8-4-4-4-12 UUID regex (case-insensitive, no version constraint
# beyond format).  We match conservatively — anything else triggers the
# DescribeJobs fallback.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _resolve_simulation_id(detail: dict) -> str | None:
    """Return the plasma_analyses UUID for this Batch job, or None.

    Order:
      jobName (if UUID-shaped) → batch.describe_jobs → parameters → tags → None.
    """
    job_name = detail.get("jobName") or ""
    if _UUID_RE.match(job_name):
        return job_name

    job_id = detail.get("jobId")
    if not job_id:
        print(
            "[webhook] no jobId in event detail; cannot fall back to "
            "DescribeJobs — POSTing with simulation_id=null"
        )
        return None

    print(
        f"[webhook] jobName {job_name!r} is not a UUID — calling "
        f"batch:DescribeJobs(jobs=[{job_id!r}]) for simulation_id"
    )
    try:
        import boto3  # provided by the Lambda python3.11 runtime
        batch = boto3.client("batch")
        resp = batch.describe_jobs(jobs=[job_id])
    except Exception as exc:  # noqa: BLE001 — webhook must always fire
        print(f"[webhook] DescribeJobs failed for jobId={job_id!r}: {exc}")
        return None

    jobs = resp.get("jobs", [])
    if not jobs:
        print(f"[webhook] DescribeJobs returned no jobs for jobId={job_id!r}")
        return None

    job = jobs[0]
    params = job.get("parameters") or {}
    if "simulation_id" in params:
        return params["simulation_id"]

    tags = job.get("tags") or {}
    if "simulation_id" in tags:
        return tags["simulation_id"]

    print(
        f"[webhook] no simulation_id in parameters or tags for "
        f"jobId={job_id!r} — POSTing with simulation_id=null"
    )
    return None


def handler(event: dict, context: object) -> dict:
    base_url = os.environ.get("KHORIUM_BACKEND_URL", "").rstrip("/")
    path = os.environ.get("WEBHOOK_PATH", "/api/plasma/simulation_complete")

    if not base_url:
        print(
            "KHORIUM_BACKEND_URL is not set — skipping webhook (stub mode). "
            "Set the env var on the Lambda function to enable notifications."
        )
        return {"statusCode": 200, "skipped": True}

    detail = event.get("detail", {})
    simulation_id = _resolve_simulation_id(detail)

    payload = json.dumps(
        {
            "simulation_id": simulation_id,   # may be None
            "batch_job_id": detail.get("jobId"),
            "status": detail.get("status"),
            "reason": detail.get("statusReason", ""),
        }
    ).encode()

    req = urllib.request.Request(
        f"{base_url}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            print(f"Webhook OK: HTTP {resp.status} — {body[:200]}")
            return {"statusCode": resp.status}
    except urllib.error.HTTPError as exc:
        print(f"Webhook HTTP error: {exc.code} {exc.reason}")
        raise
    except Exception as exc:
        print(f"Webhook error: {exc}")
        raise
