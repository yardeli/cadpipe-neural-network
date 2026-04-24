"""PlasmaNet Worker Stack — Layer B.

SU2-NEMO Batch EC2 worker for full two-temperature CFD runs.  Resources:
  - S3 bucket  plasmanet-simulations-{account}
      Lifecycle: tag-based — input objects expire after 30 d,
      output objects transition to Glacier after 90 d.
  - IAM role for the Batch job container (s3:Get/Put on that bucket only)
  - EC2 instance role + instance profile for the compute environment
  - Batch managed compute environments:
      Spot  (order 1, SPOT_CAPACITY_OPTIMIZED, c5.xlarge–c5.4xlarge, max 20 vCPU)
      OnDemand (order 2, fallback on Spot interruption, same instance fleet)
  - Job queue (Spot → OnDemand priority chain)
  - Job definition (16 vCPU / 32 GB, 6-hour timeout, 2 retry attempts)
  - CloudWatch log group for Batch jobs (30-day retention)
  - EventBridge rule: Batch Job State Change (SUCCEEDED | FAILED)
      → Lambda (lambda/simulation_complete/index.py) that POSTs to
        KhoriumBackend webhook. KHORIUM_BACKEND_URL env var set at deploy time.

Outputs: JobQueueName, JobDefinitionName, SimulationsBucketName

See docs/SIMOPS_INTEGRATION.md §2 (Layer B), §3 (artifact flow), §5 (S3 layout).
"""
from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_batch as batch,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct

# Path to the extracted Lambda handler directory.
_LAMBDA_DIR = Path(__file__).parent.parent / "lambda" / "simulation_complete"


class PlasmaNetWorkerStack(cdk.Stack):
    """Layer B: SU2-NEMO Batch EC2 worker."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        ecr_repo: ecr.IRepository,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 bucket ─────────────────────────────────────────────────────────
        # Name: plasmanet-simulations-{account} (CloudFormation resolves AccountId).
        # Lifecycle uses object tagging to distinguish inputs from outputs:
        #   the worker tags each upload with type=input or type=output.
        #   This is more flexible than prefix-based rules because the layout
        #   simulations/{jobId}/input/ can't be targeted by a prefix wildcard.
        simulation_bucket = s3.Bucket(
            self,
            "SimulationsBucket",
            bucket_name=cdk.Fn.join(
                "", ["plasmanet-simulations-", cdk.Aws.ACCOUNT_ID]
            ),
            removal_policy=cdk.RemovalPolicy.RETAIN,
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                # Expire input objects (tagged type=input) after 30 days.
                s3.LifecycleRule(
                    id="ExpireInputs",
                    tag_filters={"type": "input"},
                    expiration=cdk.Duration.days(30),
                ),
                # Archive output objects (tagged type=output) to Glacier after 90 days.
                s3.LifecycleRule(
                    id="ArchiveOutputs",
                    tag_filters={"type": "output"},
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=cdk.Duration.days(90),
                        )
                    ],
                ),
            ],
        )

        # ── IAM: worker job role ──────────────────────────────────────────────
        # Used by the *running container* — least-privilege: S3 only.
        worker_job_role = iam.Role(
            self,
            "WorkerJobRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name=f"plasmanet-worker-job-{env_name}",
            description="Batch job role for SU2-NEMO worker — S3 r/w on simulation bucket",
        )
        worker_job_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:PutObject", "s3:PutObjectTagging"],
                resources=[simulation_bucket.arn_for_objects("*")],
            )
        )
        worker_job_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:ListBucket"],
                resources=[simulation_bucket.bucket_arn],
            )
        )

        # ── IAM: execution role ───────────────────────────────────────────────
        # Used by the ECS agent *before* the container starts — pulls the image
        # from ECR and writes container stdout/stderr to CloudWatch Logs.
        # See https://docs.aws.amazon.com/batch/latest/userguide/execution-IAM-role.html
        # — must be distinct from the job role (which is for the container itself).
        execution_role = iam.Role(
            self,
            "WorkerExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name=f"plasmanet-worker-exec-{env_name}",
            description=(
                "Batch execution role for SU2-NEMO worker — ECR image pull "
                "and CloudWatch Logs write."
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                ),
            ],
        )

        # ── IAM: EC2 instance role + profile for Batch compute environment ────
        instance_role = iam.Role(
            self,
            "BatchInstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            managed_policies=[
                # Required by Batch for EC2 compute environments.
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonEC2ContainerServiceforEC2Role"
                ),
                # CloudWatch agent — so Batch nodes can ship metrics.
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "CloudWatchAgentServerPolicy"
                ),
            ],
        )
        instance_profile = iam.CfnInstanceProfile(
            self,
            "BatchInstanceProfile",
            roles=[instance_role.role_name],
        )

        # ── Security group for compute nodes ──────────────────────────────────
        compute_sg = ec2.SecurityGroup(
            self,
            "BatchComputeSG",
            vpc=vpc,
            description="PlasmaNet Batch compute nodes — outbound only",
            allow_all_outbound=True,
        )

        private_subnet_ids = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        ).subnet_ids

        # ── Batch compute environments ────────────────────────────────────────
        # Spot CE (order 1, preferred): SPOT_CAPACITY_OPTIMIZED reduces
        # interruption rate by picking the deepest capacity pool.
        spot_ce = batch.CfnComputeEnvironment(
            self,
            "NemoSpotCE",
            type="MANAGED",
            state="ENABLED",
            compute_environment_name=f"plasmanet-nemo-spot-{env_name}",
            compute_resources=batch.CfnComputeEnvironment.ComputeResourcesProperty(
                type="SPOT",
                allocation_strategy="SPOT_CAPACITY_OPTIMIZED",
                instance_role=instance_profile.attr_arn,
                instance_types=["c5.xlarge", "c5.2xlarge", "c5.4xlarge"],
                minv_cpus=0,
                maxv_cpus=20,
                subnets=private_subnet_ids,
                security_group_ids=[compute_sg.security_group_id],
            ),
        )

        # On-demand CE (order 2, fallback): engages on Spot interruption.
        od_ce = batch.CfnComputeEnvironment(
            self,
            "NemoOnDemandCE",
            type="MANAGED",
            state="ENABLED",
            compute_environment_name=f"plasmanet-nemo-od-{env_name}",
            compute_resources=batch.CfnComputeEnvironment.ComputeResourcesProperty(
                type="EC2",
                allocation_strategy="BEST_FIT_PROGRESSIVE",
                instance_role=instance_profile.attr_arn,
                instance_types=["c5.xlarge", "c5.2xlarge", "c5.4xlarge"],
                minv_cpus=0,
                maxv_cpus=20,
                subnets=private_subnet_ids,
                security_group_ids=[compute_sg.security_group_id],
            ),
        )

        # ── Job queue ─────────────────────────────────────────────────────────
        job_queue = batch.CfnJobQueue(
            self,
            "NemoJobQueue",
            job_queue_name=f"plasmanet-nemo-{env_name}",
            state="ENABLED",
            priority=100,
            compute_environment_order=[
                batch.CfnJobQueue.ComputeEnvironmentOrderProperty(
                    order=1,
                    compute_environment=spot_ce.ref,
                ),
                batch.CfnJobQueue.ComputeEnvironmentOrderProperty(
                    order=2,
                    compute_environment=od_ce.ref,
                ),
            ],
        )

        # ── CloudWatch log group for Batch jobs ───────────────────────────────
        batch_log_group = logs.LogGroup(
            self,
            "BatchLogGroup",
            log_group_name=f"/aws/batch/plasmanet-nemo/{env_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── Job definition ────────────────────────────────────────────────────
        # 16 vCPU / 32 GB → c5.4xlarge footprint.
        # Timeout: 6 hours (covers Mach 22+, large mesh CFD runs).
        # Retry: 2 attempts (handles transient Spot interruptions).
        job_def = batch.CfnJobDefinition(
            self,
            "NemoJobDef",
            type="container",
            job_definition_name=f"plasmanet-nemo-{env_name}",
            container_properties=batch.CfnJobDefinition.ContainerPropertiesProperty(
                image=cdk.Fn.join(
                    "", [ecr_repo.repository_uri, ":plasmanet-worker"]
                ),
                job_role_arn=worker_job_role.role_arn,
                execution_role_arn=execution_role.role_arn,
                resource_requirements=[
                    batch.CfnJobDefinition.ResourceRequirementProperty(
                        type="VCPU", value="16"
                    ),
                    batch.CfnJobDefinition.ResourceRequirementProperty(
                        type="MEMORY", value="32768"
                    ),
                ],
                environment=[
                    # These env vars are the container contract defined in
                    # docs/SIMOPS_INTEGRATION.md §3 (artifact flow).
                    # JOB_ID and INPUT_S3_KEY are injected by batch.submitJob().
                    batch.CfnJobDefinition.EnvironmentProperty(
                        name="S3_BUCKET",
                        value=simulation_bucket.bucket_name,
                    ),
                    batch.CfnJobDefinition.EnvironmentProperty(
                        name="OUTPUT_S3_PREFIX",
                        value="simulations",   # worker appends /{jobId}/output/
                    ),
                    batch.CfnJobDefinition.EnvironmentProperty(
                        name="MPP_DATA_DIRECTORY",
                        value="/opt/su2-nemo/mpp-data",
                    ),
                    batch.CfnJobDefinition.EnvironmentProperty(
                        name="LD_LIBRARY_PATH",
                        value="/opt/su2-nemo/lib",
                    ),
                ],
                log_configuration=batch.CfnJobDefinition.LogConfigurationProperty(
                    log_driver="awslogs",
                    options={
                        "awslogs-group": batch_log_group.log_group_name,
                        "awslogs-region": cdk.Aws.REGION,
                        "awslogs-stream-prefix": "nemo",
                    },
                ),
            ),
            timeout=batch.CfnJobDefinition.TimeoutProperty(
                attempt_duration_seconds=21600,  # 6 hours
            ),
            retry_strategy=batch.CfnJobDefinition.RetryStrategyProperty(
                attempts=2,
            ),
        )

        # ── EventBridge + Lambda webhook stub ─────────────────────────────────
        webhook_fn = lambda_.Function(
            self,
            "SimCompleteWebhook",
            function_name=f"plasmanet-simulation-complete-{env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_asset(str(_LAMBDA_DIR)),
            timeout=cdk.Duration.seconds(30),
            environment={
                # Set at deploy time — no secret value in CDK source.
                # Example: https://api.khorium.ai
                "KHORIUM_BACKEND_URL": "",
                "WEBHOOK_PATH": "/api/plasma/simulation_complete",
            },
            description=(
                "Stub: notifies KhoriumBackend on Batch job completion. "
                "Replace with real implementation at milestone I-2."
            ),
        )

        # Allow EventBridge to invoke the Lambda.
        webhook_fn.add_permission(
            "EventBridgeInvoke",
            principal=iam.ServicePrincipal("events.amazonaws.com"),
        )

        # Rule: fire on SUCCEEDED or FAILED state changes for this job queue.
        completion_rule = events.Rule(
            self,
            "BatchJobStateRule",
            rule_name=f"plasmanet-nemo-job-state-{env_name}",
            description=(
                "On SU2-NEMO Batch job completion, invoke webhook stub to "
                "notify KhoriumBackend /api/plasma/simulation_complete."
            ),
            event_pattern=events.EventPattern(
                source=["aws.batch"],
                detail_type=["Batch Job State Change"],
                detail={
                    "status": ["SUCCEEDED", "FAILED"],
                    "jobQueue": [job_queue.ref],
                },
            ),
        )
        completion_rule.add_target(targets.LambdaFunction(webhook_fn))

        # ── CloudFormation outputs ────────────────────────────────────────────
        cdk.CfnOutput(
            self,
            "JobQueueName",
            value=job_queue.job_queue_name,  # type: ignore[arg-type]
            description="Batch job queue name for SU2-NEMO submissions",
            export_name=f"PlasmaNetJobQueueName-{env_name}",
        )
        cdk.CfnOutput(
            self,
            "JobDefinitionName",
            value=job_def.job_definition_name,  # type: ignore[arg-type]
            description="Batch job definition name (pass to batch.submitJob)",
            export_name=f"PlasmaNetJobDefName-{env_name}",
        )
        cdk.CfnOutput(
            self,
            "SimulationsBucketName",
            value=simulation_bucket.bucket_name,
            description="S3 bucket for SU2-NEMO simulation artifacts",
            export_name=f"PlasmaNetSimBucket-{env_name}",
        )
