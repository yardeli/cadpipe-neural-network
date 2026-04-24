# PlasmaNet CDK

CDK Python stacks that deploy the two-layer SimOps infrastructure described in
[docs/SIMOPS_INTEGRATION.md](../docs/SIMOPS_INTEGRATION.md).

| Stack | Layer | What it does |
|---|---|---|
| `PlasmaNetServiceStack-{env}` | A | Fargate always-on inference service — /api/plasma/* routing |
| `PlasmaNetWorkerStack-{env}` | B | SU2-NEMO Batch EC2 worker — CFD job queue + S3 bucket |

---

## Prerequisites

```bash
pip install aws-cdk-lib constructs
npm install -g aws-cdk
```

Python ≥ 3.10. CDK CLI ≥ 2.100.

---

## Required environment variables

Set these before deploying. **No secrets go in CDK source.**

| Variable | Where used | Example |
|---|---|---|
| `CDK_DEFAULT_ACCOUNT` | CDK account resolution | `123456789012` |
| `CDK_DEFAULT_REGION` | CDK region resolution | `us-east-1` |
| `KHORIUM_BACKEND_URL` | Webhook Lambda env var (set post-deploy) | `https://api.khorium.ai` |

`CDK_DEFAULT_ACCOUNT` and `CDK_DEFAULT_REGION` are set automatically when you
run `aws configure` or use an IAM role with AWS SSO.

---

## Bootstrapping a new AWS account

CDK bootstrap is required once per account/region before the first deploy:

```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION
```

If deploying cross-account (e.g. staging account from a CI role):

```bash
cdk bootstrap \
  --trust <ci-account-id> \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess \
  aws://$STAGING_ACCOUNT_ID/$CDK_DEFAULT_REGION
```

---

## Deploy order

Service stack must deploy first (creates the ECR repo and VPC that the
worker stack references).

```bash
# From the cdk/ directory:

# 1. Synthesize — validates templates without touching AWS
cdk synth

# 2. Review changes against live stacks
cdk diff PlasmaNetServiceStack-dev
cdk diff PlasmaNetWorkerStack-dev

# 3. Deploy Layer A
cdk deploy PlasmaNetServiceStack-dev

# 4. Push the service image before the Fargate service becomes healthy
# (task will stay in PENDING until the image exists in ECR)
ECR_URI=$(aws cloudformation describe-stacks \
  --stack-name PlasmaNetServiceStack-dev \
  --query "Stacks[0].Outputs[?OutputKey=='EcrRepoUri'].OutputValue" \
  --output text)

docker build --target service -t "$ECR_URI:plasmanet-service" ..
aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_URI"
docker push "$ECR_URI:plasmanet-service"

# 5. Deploy Layer B
cdk deploy PlasmaNetWorkerStack-dev

# 6. Set the webhook URL on the Lambda after both stacks are deployed
aws lambda update-function-configuration \
  --function-name plasmanet-simulation-complete-dev \
  --environment "Variables={KHORIUM_BACKEND_URL=https://api.khorium.ai,WEBHOOK_PATH=/api/plasma/simulation_complete}"
```

---

## Context overrides

Pass context with `--context key=value`:

```bash
# Deploy to staging
cdk deploy --all --context env=staging --context region=us-east-1

# Point at an existing shared VPC instead of creating a new one
# (edit plasmanet_service_stack.py to use Vpc.from_lookup() first)
cdk deploy PlasmaNetServiceStack-prod --context env=prod --context account=111222333444
```

---

## Useful synth / diff commands

```bash
# Synthesize all stacks and print CloudFormation YAML
cdk synth

# Synthesize from the repo root (without cd-ing into cdk/)
cdk synth --app "python cdk/app.py"

# Check what CDK would change vs current deployed state
cdk diff

# List all stacks in the app
cdk list

# Destroy (leaves S3 bucket + ECR repo — both have RemovalPolicy.RETAIN)
cdk destroy PlasmaNetWorkerStack-dev
cdk destroy PlasmaNetServiceStack-dev
```

---

## Stack outputs

After deploy, retrieve outputs with:

```bash
aws cloudformation describe-stacks --stack-name PlasmaNetServiceStack-dev \
  --query "Stacks[0].Outputs"
```

| Output key | Stack | Value |
|---|---|---|
| `ServiceUrl` | Service | ALB DNS + /api/plasma prefix |
| `EcrRepoUri` | Service | ECR repo URI for both image tags |
| `LogGroupName` | Service | CloudWatch log group for Fargate tasks |
| `JobQueueName` | Worker | Batch queue name for `batch.submitJob()` |
| `JobDefinitionName` | Worker | Batch job definition name |
| `SimulationsBucketName` | Worker | S3 bucket for CFD artifacts |

---

## Switching to a shared VPC (production)

The stacks create their own VPC by default.  To reuse the shared KhoriumVpc:

1. In `plasmanet_service_stack.py`, replace the `ec2.Vpc(...)` block with:
   ```python
   self.vpc = ec2.Vpc.from_lookup(self, "KhoriumVpc",
       vpc_name=f"KhoriumVpc-{env_name}")
   ```
2. Ensure `CDK_DEFAULT_ACCOUNT` is set to a concrete account ID (required for
   `Vpc.from_lookup()` to query AWS at synth time).
3. Run `cdk synth` — CDK will cache the VPC attributes in `cdk.context.json`.

---

## Architecture reference

```
PlasmaNetServiceStack-{env}
  ECR repo (plasmanet) ──────────────────────────────────┐
  VPC (2-AZ) ─────────────────────────────────────────┐  │
    ALB (/api/plasma/* → port 8200)                    │  │
    ECS Cluster                                         │  │
      Fargate Service (desired=1, always-on)            │  │
        Task: 0.25 vCPU / 512 MB                       │  │
        Container: ECR :plasmanet-service              ←┘  │
        Env: MODEL_S3_KEY, PORT, ENV                       │
    LogGroup /ecs/plasmanet-service/{env} (30 d)           │
                                                           │
PlasmaNetWorkerStack-{env}                                 │
  S3 plasmanet-simulations-{account}                       │
    Lifecycle: input → expire 30 d, output → Glacier 90 d  │
  Batch Spot CE  (c5.xlarge–c5.4xlarge, max 20 vCPU)      │
  Batch OD CE    (fallback, same fleet)                    │
  Job Queue      (Spot order=1, OD order=2)                │
  Job Definition (16 vCPU / 32 GB, 6h timeout)             │
    Container: ECR :plasmanet-worker                      ←┘
    Env: S3_BUCKET, MPP_DATA_DIRECTORY, LD_LIBRARY_PATH
  EventBridge → Lambda (webhook stub → KhoriumBackend)
  LogGroup /aws/batch/plasmanet-nemo/{env} (30 d)
```
