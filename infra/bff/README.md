# Grid BFF proxy — EC2 (Terraform)

A small EC2 instance that runs `grid-local-api` in **proxy mode** (a backend-for-frontend).
It serves the test console (`/ui/`) and forwards `/api/grid/run` to the **deployed AgentCore
runtime**, streaming events back and saving run history to S3. AgentCore does the heavy
compute, so this box is just a thin, cheap proxy.

## What's deployed

| | |
|---|---|
| Instance | `i-0bab53f191deb352f` (t3.medium, Amazon Linux 2023) |
| Region / account | `us-east-1` / `218254303724` |
| Forwards to | `arn:aws:bedrock-agentcore:us-east-1:218254303724:runtime/GridAgentCore_GridAgentCore-j9s7R2FPWR` |
| Exposure | **Private** — security group has **no inbound ports**; the app binds `127.0.0.1:8000` |
| Auth to AWS | IAM **instance role** (no static keys on the box): `InvokeAgentRuntime` + scoped S3 read/write |
| Service | systemd unit `grid-bff` → `uv run grid-local-api` |
| App dir / env / log | `/opt/grid-bff/GridAgentCore` · `/opt/grid-bff/bff.env` · `/var/log/grid-bff-bootstrap.log` |

> The instance is private by design. There is **no public URL** — reach it through SSM (below).

## Prerequisites (one-time, local)

- **AWS credentials for account `218254303724`.** Either export them, or `source` the repo `.env`:
  ```bash
  set -a; source /Users/kaps/repos/aws_agent_core/.env; set +a
  ```
- **AWS CLI v2**: `brew install awscli`
- **SSM Session Manager plugin** (needs your sudo password — run it yourself):
  ```bash
  brew install --cask session-manager-plugin
  ```
- Your IAM identity needs `ssm:StartSession` + `ssm:DescribeInstanceInformation` (admin covers it).

## Access — open the console in your browser (recommended)

Start an SSM port-forward (no inbound port is opened; the tunnel rides the SSM channel):

```bash
aws ssm start-session --region us-east-1 --target i-0bab53f191deb352f \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Leave that running, then open **http://localhost:8000/ui/** in your browser.
(The same command is available via `terraform output ssm_tunnel_command`.)

## Access — a shell on the box (ops/debugging)

```bash
aws ssm start-session --region us-east-1 --target i-0bab53f191deb352f
```

Useful once on the box (or via `aws ssm send-command`):

```bash
systemctl status grid-bff           # service state
journalctl -u grid-bff -n 100       # app logs
sudo tail -f /var/log/grid-bff-bootstrap.log   # first-boot bootstrap log
curl -s localhost:8000/api/health   # health
sudo systemctl restart grid-bff     # restart the proxy
```

## Operations

**Stop / start to save cost** (it bills ~$30/mo while running; nothing else unless you run queries):
```bash
aws ec2 stop-instances  --region us-east-1 --instance-ids i-0bab53f191deb352f
aws ec2 start-instances --region us-east-1 --instance-ids i-0bab53f191deb352f
```
> The public IP changes on stop/start. It doesn't matter for SSM access (which targets the
> instance ID), only for direct-IP access (see below).

**Redeploy app code** after changing the app: rebuild the tarball and re-apply — the instance
re-bootstraps on the new `user_data`:
```bash
# from repo root
tar -C app --exclude='.venv' --exclude='.grid_artifacts*' --exclude='node_modules' \
    --exclude='__pycache__' --exclude='*.pyc' -czf infra/bff/dist/grid-bff.tar.gz GridAgentCore
cd infra/bff && terraform apply
```

**Tear it all down**:
```bash
cd infra/bff && terraform destroy
```

## Terraform

```bash
set -a; source ../../.env; set +a     # AWS creds for account 218254303724
terraform init
terraform plan
terraform apply
```
State is local (`terraform.tfstate`) — do not commit it (it can contain sensitive values).
Key variables are in `variables.tf` (`runtime_arn`, `s3_bucket`, `instance_type`, `expose_public`).

## Optional — a direct URL (no tunnel)

To skip the tunnel and hit the box directly from your machine, open port 8000 to **your IP only**
and bind the app to all interfaces:

1. Set `expose_public = true` and `ingress_cidr = "<your-ip>/32"`, and change the SG/ingress port
   to `8000` (currently scaffolded for `443`).
2. `terraform apply`.
3. Browse `http://<instance-public-ip>:8000/ui/`.

Caveats: this is **plain HTTP** (unencrypted), reachable only from the whitelisted IP, and the
public IP changes on stop/start (attach an Elastic IP to pin it). For a real shareable HTTPS URL
you'd add a domain + cert + an auth gate. Left disabled by default.
