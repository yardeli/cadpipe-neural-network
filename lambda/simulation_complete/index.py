"""KhoriumBackend webhook — notifies /api/plasma/simulation_complete on job end.

Triggered by EventBridge on Batch Job State Change (SUCCEEDED | FAILED).
Uses stdlib only (urllib.request) — no external dependencies.

Environment variables
---------------------
KHORIUM_BACKEND_URL   Base URL of KhoriumBackend, e.g. https://api.khorium.ai.
                      If empty the function logs a warning and exits successfully
                      (allows deployment before the backend endpoint exists).
WEBHOOK_PATH          Path to POST to. Default: /api/plasma/simulation_complete
"""
from __future__ import annotations

import json
import os
import urllib.request


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
    payload = json.dumps(
        {
            "simulation_id": detail.get("jobName"),
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
