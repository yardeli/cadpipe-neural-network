"""PlasmaNet Service Stack — Layer A.

Fargate always-on inference service.  Resources:
  - ECR repository (shared with worker: plasmanet-service / plasmanet-worker tags)
  - VPC (2 AZs, public + private).  PRODUCTION: swap for Vpc.from_lookup()
    pointing at the shared KhoriumVpc.
  - ECS cluster with Container Insights enabled
  - Fargate task: 0.25 vCPU / 512 MB (Fargate minimum for 256 CPU units)
    Note: the doc specifies "256 MB"; Fargate's hard minimum for 0.25 vCPU
    is 512 MB.  Memory limit matches task reservation.
  - Service: desired_count=1, always-on, rolling update (100/200 %)
  - ALB with path-based routing: /api/plasma/* → this service, priority 10
  - CloudWatch log group with 30-day retention

Outputs: ServiceUrl, EcrRepoUri, LogGroupName

See docs/SIMOPS_INTEGRATION.md §2 (Layer A) and §6 (CDK changes table).
"""
from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class PlasmaNetServiceStack(cdk.Stack):
    """Layer A: Fargate always-on PlasmaNet inference service."""

    #: Shared ECR repo exposed to PlasmaNetWorkerStack.
    ecr_repo: ecr.Repository
    #: VPC exposed to PlasmaNetWorkerStack so Batch CE lands in the same network.
    vpc: ec2.Vpc

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── ECR ──────────────────────────────────────────────────────────────
        # One repo, two tags:
        #   :plasmanet-service  — lightweight inference image (this stack)
        #   :plasmanet-worker   — SU2-NEMO worker image (worker stack)
        self.ecr_repo = ecr.Repository(
            self,
            "PlasmaNetRepo",
            repository_name="plasmanet",
            removal_policy=cdk.RemovalPolicy.RETAIN,
            lifecycle_rules=[
                ecr.LifecycleRule(
                    tag_prefix_list=["plasmanet-"],
                    max_image_count=10,
                    description="Retain last 10 images per tag prefix",
                ),
            ],
        )

        # ── VPC ───────────────────────────────────────────────────────────────
        # 2-AZ: public subnets for ALB, private-with-egress for Fargate tasks.
        # PRODUCTION: replace with:
        #   self.vpc = ec2.Vpc.from_lookup(self, "KhoriumVpc",
        #       vpc_name="KhoriumVpc-{env_name}")
        # (requires a concrete account in aws_env).
        self.vpc = ec2.Vpc(
            self,
            "PlasmaNetVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ── ECS cluster ───────────────────────────────────────────────────────
        cluster = ecs.Cluster(
            self,
            "PlasmaNetCluster",
            cluster_name=f"plasmanet-{env_name}",
            vpc=self.vpc,
            container_insights_v2=ecs.ContainerInsights.ENABLED,
        )

        # ── CloudWatch log group ───────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "ServiceLogGroup",
            log_group_name=f"/ecs/plasmanet-service/{env_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # ── Task IAM role ─────────────────────────────────────────────────────
        # Least-privilege: only read the model checkpoint from S3.
        task_role = iam.Role(
            self,
            "TaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            role_name=f"plasmanet-service-task-{env_name}",
            description="Task role for PlasmaNet Fargate inference service",
        )
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[
                    cdk.Fn.sub(
                        "arn:${AWS::Partition}:s3:::*/plasma_checkpoints/*"
                    )
                ],
            )
        )

        # ── Fargate task definition ───────────────────────────────────────────
        # cpu=256 → 0.25 vCPU.  Fargate minimum memory for 256 CPU units = 512 MB.
        task_def = ecs.FargateTaskDefinition(
            self,
            "ServiceTask",
            family=f"plasmanet-service-{env_name}",
            cpu=256,
            memory_limit_mib=512,
            task_role=task_role,
        )

        # Container image placeholder — build step is a follow-up commit.
        # Push to ECR with tag plasmanet-service before deploying.
        task_def.add_container(
            "PlasmaNetContainer",
            image=ecs.ContainerImage.from_ecr_repository(
                self.ecr_repo,
                tag="plasmanet-service",
            ),
            memory_limit_mib=512,
            logging=ecs.LogDrivers.aws_logs(
                log_group=log_group,
                stream_prefix="plasmanet-service",
            ),
            environment={
                "PORT": "8200",
                "ENV": env_name,
                # Set to e.g. s3://khorium-uploads-dev/plasma_checkpoints/v1/model.pt
                # via CDK context override or SSM Parameter in a later milestone.
                "MODEL_S3_KEY": "",
            },
            port_mappings=[ecs.PortMapping(container_port=8200)],
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    "curl -sf http://localhost:8200/health || exit 1",
                ],
                interval=cdk.Duration.seconds(30),
                timeout=cdk.Duration.seconds(5),
                retries=3,
                start_period=cdk.Duration.seconds(60),
            ),
        )

        # ── ALB ───────────────────────────────────────────────────────────────
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "PlasmaNetALB",
            load_balancer_name=f"plasmanet-{env_name}",
            vpc=self.vpc,
            internet_facing=True,
        )

        listener = alb.add_listener(
            "HttpListener",
            port=80,
            open=True,
            # Default action: 404 for any path not matched by a rule.
            default_action=elbv2.ListenerAction.fixed_response(
                status_code=404,
                content_type="text/plain",
                message_body="PlasmaNet: path not found",
            ),
        )

        # ── Fargate service ───────────────────────────────────────────────────
        service = ecs.FargateService(
            self,
            "PlasmaNetService",
            service_name=f"plasmanet-service-{env_name}",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            min_healthy_percent=100,
            max_healthy_percent=200,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            assign_public_ip=False,
        )

        # Path-based routing: /api/plasma/* → PlasmaNetService, priority 10.
        # Other routes (e.g. /api/* for KhoriumBackend) get higher priority
        # numbers added by KhoriumCDK stacks.
        listener.add_targets(
            "PlasmaNetTargets",
            port=8200,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(
                path="/health",
                healthy_http_codes="200",
                interval=cdk.Duration.seconds(30),
                timeout=cdk.Duration.seconds(5),
            ),
            conditions=[
                elbv2.ListenerCondition.path_patterns(["/api/plasma/*"])
            ],
            priority=10,
            target_group_name=f"plasmanet-tg-{env_name}",
        )

        # Allow the ALB to reach Fargate tasks on port 8200.
        service.connections.allow_from(alb, ec2.Port.tcp(8200))

        # ── CloudFormation outputs ────────────────────────────────────────────
        cdk.CfnOutput(
            self,
            "ServiceUrl",
            value=cdk.Fn.join(
                "", ["http://", alb.load_balancer_dns_name, "/api/plasma"]
            ),
            description="PlasmaNet service base URL (path prefix /api/plasma)",
            export_name=f"PlasmaNetServiceUrl-{env_name}",
        )
        cdk.CfnOutput(
            self,
            "EcrRepoUri",
            value=self.ecr_repo.repository_uri,
            description=(
                "ECR repository URI. "
                "Push :plasmanet-service for the inference image, "
                ":plasmanet-worker for the SU2-NEMO image."
            ),
            export_name=f"PlasmaNetEcrRepoUri-{env_name}",
        )
        cdk.CfnOutput(
            self,
            "LogGroupName",
            value=log_group.log_group_name,
            description="CloudWatch log group for Fargate containers",
            export_name=f"PlasmaNetLogGroup-{env_name}",
        )
