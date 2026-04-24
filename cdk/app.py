#!/usr/bin/env python3
"""PlasmaNet CDK application.

Deploys two stacks that implement the two-layer architecture from
docs/SIMOPS_INTEGRATION.md §2:

  PlasmaNetServiceStack-{env}  — Layer A: Fargate always-on inference service
  PlasmaNetWorkerStack-{env}   — Layer B: SU2-NEMO Batch EC2 worker

Deploy order: Service stack first (creates ECR repo + VPC), then Worker.

Usage
-----
    # From the cdk/ directory:
    cdk synth
    cdk deploy PlasmaNetServiceStack-dev
    cdk deploy PlasmaNetWorkerStack-dev

    # Or from the repo root:
    cdk synth --app "python cdk/app.py"

Context keys (pass with --context or in cdk.json)
--------------------------------------------------
    env      Deployment environment. Default: dev.
    account  AWS account ID. Falls back to CDK_DEFAULT_ACCOUNT env var.
    region   AWS region. Falls back to CDK_DEFAULT_REGION env var.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import aws_cdk as cdk
from plasmanet_service_stack import PlasmaNetServiceStack
from plasmanet_worker_stack import PlasmaNetWorkerStack

app = cdk.App()

env_name: str = app.node.try_get_context("env") or "dev"

aws_env = cdk.Environment(
    account=(
        app.node.try_get_context("account")
        or os.environ.get("CDK_DEFAULT_ACCOUNT")
    ),
    region=(
        app.node.try_get_context("region")
        or os.environ.get("CDK_DEFAULT_REGION")
        or "us-east-1"
    ),
)

# Tags applied to every resource in every stack.
# Follows the KhoriumCDK convention: project / env / owner / managed-by.
TAGS: dict[str, str] = {
    "project": "plasmanet",
    "env": env_name,
    "owner": "khorium-infra",
    "managed-by": "cdk",
    "repo": "yardeli/plasmanet",
}

# ── Layer A ────────────────────────────────────────────────────────────────────
service_stack = PlasmaNetServiceStack(
    app,
    f"PlasmaNetServiceStack-{env_name}",
    env_name=env_name,
    env=aws_env,
    description=(
        "PlasmaNet Fargate always-on inference service (Layer A) "
        "— docs/SIMOPS_INTEGRATION.md §2"
    ),
)

# ── Layer B ────────────────────────────────────────────────────────────────────
worker_stack = PlasmaNetWorkerStack(
    app,
    f"PlasmaNetWorkerStack-{env_name}",
    env_name=env_name,
    ecr_repo=service_stack.ecr_repo,
    vpc=service_stack.vpc,
    env=aws_env,
    description=(
        "PlasmaNet SU2-NEMO Batch EC2 worker (Layer B) "
        "— docs/SIMOPS_INTEGRATION.md §2"
    ),
)
# Worker needs the ECR repo + VPC from the service stack.
worker_stack.add_dependency(service_stack)

for stack in (service_stack, worker_stack):
    for key, value in TAGS.items():
        cdk.Tags.of(stack).add(key, value)

app.synth()
