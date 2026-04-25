"""Integration tests for lambda/simulation_complete/index.py.

Exercises the simulation_id resolver added in efa515e:

  (a) UUID jobName             → fast path; zero AWS calls
  (b) Non-UUID + parameters    → DescribeJobs fallback finds simulation_id
  (c) Non-UUID + no metadata   → fallback returns None; webhook posts null
  (d) Non-UUID + tags          → fallback finds simulation_id in tags
  (e) DescribeJobs raises      → graceful → simulation_id=null, status 200
  (f) Missing jobId in detail  → early return; zero AWS calls

Mocks
-----
moto.mock_aws         Blocks all real AWS API calls. Used to stand up a
                      minimal Batch environment for tests (b)/(c)/(d).
                      Skipped for (e)/(f) — those test paths that don't
                      need a real Batch backend.
boto3.client tracker  Wraps boto3.client at runtime to (1) log which
                      services the Lambda touches and (2) reject any
                      service other than "batch" — Lambda must not call
                      S3 or SSM.
pytest-httpserver     In-process HTTP server fixture (httpserver) captures
                      the webhook POST so we can assert the payload
                      shape and simulation_id value.
"""
from __future__ import annotations

import json
import sys
import uuid as uuid_lib
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# Make the Lambda handler importable.  "lambda" is a Python keyword so we
# can't use a normal package import; sys.path insert is the standard pattern.
LAMBDA_DIR = Path(__file__).parent.parent / "lambda" / "simulation_complete"
sys.path.insert(0, str(LAMBDA_DIR))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def lambda_handler():
    """Force-reimport so each test gets a fresh module (no cached boto3 client)."""
    sys.modules.pop("index", None)
    import index  # type: ignore[import-not-found]
    return index.handler


@pytest.fixture
def webhook_server(httpserver):
    """pytest-httpserver fixture pre-configured to accept the webhook POST."""
    httpserver.expect_request(
        "/api/plasma/simulation_complete", method="POST"
    ).respond_with_json({"ok": True})
    return httpserver


@pytest.fixture
def webhook_env(webhook_server, monkeypatch):
    """Point the Lambda at the in-process server.

    Also sets AWS_DEFAULT_REGION (which the Lambda runtime injects in prod
    as AWS_REGION + AWS_DEFAULT_REGION) so the Lambda's bare
    boto3.client("batch") call resolves a region.
    """
    monkeypatch.setenv("KHORIUM_BACKEND_URL", webhook_server.url_for("").rstrip("/"))
    monkeypatch.setenv("WEBHOOK_PATH", "/api/plasma/simulation_complete")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")


def _install_boto3_tracker(monkeypatch) -> list[str]:
    """Wrap boto3.client: log service names; reject S3 / SSM.

    Call this *after* any test setup that itself uses boto3 (e.g. moto Batch
    bootstrap), so the log captures only Lambda's own AWS calls.
    """
    calls: list[str] = []
    original = boto3.client

    def tracked(service: str, *args, **kwargs):
        calls.append(service)
        if service in ("s3", "ssm"):
            raise AssertionError(
                f"Lambda must not touch {service!r} — only 'batch' is allowed"
            )
        return original(service, *args, **kwargs)

    monkeypatch.setattr(boto3, "client", tracked)
    return calls


def _captured_post_body(webhook_server) -> dict:
    """Decode the JSON body of the single webhook POST captured by the server."""
    log = webhook_server.log
    assert len(log) == 1, f"expected 1 webhook POST, got {len(log)}: {log!r}"
    request, _response = log[0]
    return json.loads(request.get_data())


def _setup_batch_and_submit_job(*, region: str, job_name: str,
                                parameters: dict | None,
                                tags: dict | None = None) -> str:
    """Bootstrap minimal Batch infra in moto, submit one job, return its jobId.

    Returns the moto-assigned jobId so the test can pass it through the
    EventBridge event detail to the Lambda's DescribeJobs fallback path.
    """
    iam = boto3.client("iam", region_name=region)
    role = iam.create_role(
        RoleName="batch-svc",
        AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "batch.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }),
    )
    # Batch's compute-environment validator requires the instance profile to
    # actually exist in IAM (moto enforces this).
    iam.create_role(
        RoleName="ecsInstanceRole",
        AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }),
    )
    profile = iam.create_instance_profile(InstanceProfileName="ecsInstanceRole")
    iam.add_role_to_instance_profile(
        InstanceProfileName="ecsInstanceRole",
        RoleName="ecsInstanceRole",
    )
    instance_profile_arn = profile["InstanceProfile"]["Arn"]

    ec2 = boto3.client("ec2", region_name=region)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.0.0/24")["Subnet"]["SubnetId"]
    sg = ec2.create_security_group(GroupName="sg", Description="sg", VpcId=vpc)["GroupId"]

    batch = boto3.client("batch", region_name=region)
    ce = batch.create_compute_environment(
        computeEnvironmentName="test-ce",
        type="MANAGED",
        state="ENABLED",
        computeResources={
            "type": "EC2",
            "minvCpus": 0,
            "maxvCpus": 1,
            "instanceTypes": ["c5.large"],
            "subnets": [subnet],
            "securityGroupIds": [sg],
            "instanceRole": instance_profile_arn,
        },
        serviceRole=role["Role"]["Arn"],
    )
    queue = batch.create_job_queue(
        jobQueueName="test-queue",
        state="ENABLED",
        priority=1,
        computeEnvironmentOrder=[
            {"order": 1, "computeEnvironment": ce["computeEnvironmentArn"]}
        ],
    )
    jd = batch.register_job_definition(
        jobDefinitionName="test-jd",
        type="container",
        containerProperties={"image": "alpine", "vcpus": 1, "memory": 256},
    )
    submit_kwargs: dict = dict(
        jobName=job_name,
        jobQueue=queue["jobQueueArn"],
        jobDefinition=jd["jobDefinitionArn"],
    )
    if parameters:
        submit_kwargs["parameters"] = parameters
    if tags:
        submit_kwargs["tags"] = tags
    return batch.submit_job(**submit_kwargs)["jobId"]


# ── (a) UUID jobName → fast path, zero AWS calls ─────────────────────────────

@mock_aws
def test_uuid_jobname_skips_describejobs(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    sim_id = str(uuid_lib.uuid4())
    boto3_calls = _install_boto3_tracker(monkeypatch)

    event = {
        "detail": {
            "jobName": sim_id,
            "jobId": "irrelevant-not-used-on-uuid-fast-path",
            "status": "SUCCEEDED",
            "statusReason": "OK",
        }
    }
    result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] == sim_id
    assert body["status"] == "SUCCEEDED"
    assert body["batch_job_id"] == "irrelevant-not-used-on-uuid-fast-path"
    # Fast path: zero boto3.client invocations.
    assert boto3_calls == [], f"unexpected AWS calls: {boto3_calls!r}"


# ── (b) Non-UUID jobName + parameters[simulation_id] → DescribeJobs path ─────

@mock_aws
def test_non_uuid_jobname_resolves_via_describejobs_parameters(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    sim_id = str(uuid_lib.uuid4())
    job_id = _setup_batch_and_submit_job(
        region="us-east-1",
        job_name="submit-foo-123",
        parameters={"simulation_id": sim_id},
    )

    # Install tracker AFTER bootstrap so setup calls don't pollute the log.
    boto3_calls = _install_boto3_tracker(monkeypatch)

    event = {
        "detail": {
            "jobName": "submit-foo-123",
            "jobId": job_id,
            "status": "SUCCEEDED",
            "statusReason": "OK",
        }
    }
    result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] == sim_id
    # Fallback path: exactly one boto3.client('batch') invocation.
    assert boto3_calls == ["batch"], f"unexpected AWS calls: {boto3_calls!r}"


# ── (c) Non-UUID jobName + no metadata → POST simulation_id=null ─────────────

@mock_aws
def test_non_uuid_jobname_no_metadata_posts_null(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    job_id = _setup_batch_and_submit_job(
        region="us-east-1",
        job_name="submit-bar-456",
        parameters=None,            # no simulation_id anywhere
    )

    boto3_calls = _install_boto3_tracker(monkeypatch)

    event = {
        "detail": {
            "jobName": "submit-bar-456",
            "jobId": job_id,
            "status": "FAILED",
            "statusReason": "Spot interrupted",
        }
    }
    result = lambda_handler(event, None)

    # Webhook still fires; KhoriumBackend gets the completion event with
    # simulation_id=null so an operator can correlate via batch_job_id.
    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] is None
    assert body["status"] == "FAILED"
    assert body["reason"] == "Spot interrupted"
    assert body["batch_job_id"] == job_id
    assert boto3_calls == ["batch"], f"unexpected AWS calls: {boto3_calls!r}"


# ── (d) Non-UUID jobName + tags[simulation_id] → tag fallback ────────────────

@mock_aws
def test_tags_fallback_path(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    sim_id = str(uuid_lib.uuid4())
    job_id = _setup_batch_and_submit_job(
        region="us-east-1",
        job_name="submit-tagged-789",
        parameters=None,                              # nothing in parameters
        tags={"simulation_id": sim_id, "env": "dev"}, # only in tags
    )

    boto3_calls = _install_boto3_tracker(monkeypatch)

    event = {
        "detail": {
            "jobName": "submit-tagged-789",
            "jobId": job_id,
            "status": "SUCCEEDED",
            "statusReason": "OK",
        }
    }
    result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] == sim_id
    assert boto3_calls == ["batch"], f"unexpected AWS calls: {boto3_calls!r}"


# ── (e) DescribeJobs raises → webhook still fires with simulation_id=null ────

def test_describe_jobs_exception(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    """boto3 client is mocked directly — no moto bootstrap needed; the goal is
    to exercise the except-branch in _resolve_simulation_id deterministically.
    """
    from unittest.mock import MagicMock
    from botocore.exceptions import ClientError

    boto3_calls: list[str] = []
    mock_batch = MagicMock()
    mock_batch.describe_jobs.side_effect = ClientError(
        error_response={
            "Error": {"Code": "ServiceUnavailable", "Message": "Batch is down"}
        },
        operation_name="DescribeJobs",
    )

    def fake_client(service: str, *args, **kwargs):
        boto3_calls.append(service)
        if service in ("s3", "ssm"):
            raise AssertionError(
                f"Lambda must not touch {service!r} — only 'batch' is allowed"
            )
        return mock_batch

    monkeypatch.setattr(boto3, "client", fake_client)

    event = {
        "detail": {
            "jobName": "submit-broken-aws",
            "jobId": "fake-job-id-12345",
            "status": "FAILED",
            "statusReason": "Spot interrupted",
        }
    }
    result = lambda_handler(event, None)

    # Webhook still fires — Lambda is robust to AWS-side failures.
    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] is None
    assert body["status"] == "FAILED"
    assert body["reason"] == "Spot interrupted"
    assert body["batch_job_id"] == "fake-job-id-12345"
    # Lambda did call DescribeJobs once before the exception was raised.
    mock_batch.describe_jobs.assert_called_once_with(jobs=["fake-job-id-12345"])
    assert boto3_calls == ["batch"]


# ── (f) Missing jobId → early return; zero AWS calls ─────────────────────────

def test_missing_jobid_in_detail(
    monkeypatch, lambda_handler, webhook_env, webhook_server
):
    """No jobId in event detail → resolver bails before any AWS call."""
    boto3_calls = _install_boto3_tracker(monkeypatch)

    event = {
        "detail": {
            "jobName": "submit-no-jobid",
            # jobId deliberately omitted
            "status": "SUCCEEDED",
            "statusReason": "OK",
        }
    }
    result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = _captured_post_body(webhook_server)
    assert body["simulation_id"] is None
    assert body["batch_job_id"] is None      # detail.get("jobId") → None
    assert body["status"] == "SUCCEEDED"
    assert boto3_calls == [], f"unexpected AWS calls: {boto3_calls!r}"
