# Grid BFF proxy — EC2 (Terraform)

A small EC2 instance that runs `grid-local-api` in **proxy mode** (a backend-for-frontend).
It serves the test console (`/ui/`) and forwards `/api/grid/run` to the **deployed AgentCore
runtime**, streaming events back and saving run history to S3. AgentCore does the heavy
compute, so this box is just a thin, cheap proxy.

## What's deployed

| | |
|---|---|
| Instance | EC2 `t3.medium` by default, Amazon Linux 2023 |
| Region / account | Your configured AWS account and `var.region` |
| Forwards to | `var.runtime_arn` |
| Exposure | **Private** — security group has **no inbound ports**; the app binds `127.0.0.1:8000` |
| Auth to AWS | IAM **instance role** (no static keys on the box): `InvokeAgentRuntime` + scoped S3 read/write |
| Service | systemd unit `grid-bff` → `uv run grid-local-api` |
| App dir / env / log | `/opt/grid-bff/GridAgentCore` · `/opt/grid-bff/bff.env` · `/var/log/grid-bff-bootstrap.log` |

> The instance is private by design. There is **no public URL** — reach it through SSM (below).

## Prerequisites (one-time, local)

- AWS credentials for the account that owns the AgentCore runtime and artifact bucket. Either use an AWS profile/SSO session, export temporary credentials, or source the repo `.env`:
  ```bash
  set -a; source ../../.env; set +a
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
aws ssm start-session --region "$AWS_REGION" --target "$(terraform output -raw instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Leave that running, then open **http://localhost:8000/ui/** in your browser.
(The same command is available via `terraform output ssm_tunnel_command`.)

## Access — a shell on the box (ops/debugging)

```bash
aws ssm start-session --region "$AWS_REGION" --target "$(terraform output -raw instance_id)"
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
aws ec2 stop-instances --region "$AWS_REGION" --instance-ids "$(terraform output -raw instance_id)"
aws ec2 start-instances --region "$AWS_REGION" --instance-ids "$(terraform output -raw instance_id)"
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

## Email intake (Gmail poller)

The BFF can run the email-intake poller (pulls application bundles from a Gmail inbox,
extracts them with Claude on Bedrock, queues them for operator Accept/Reject). It's **off
unless you set `gmail_token_ssm_param`**. Because the box is headless, the OAuth token is
minted locally and delivered via SSM.

1. **Mint the token locally** (one-time) — see the repo's
   `app/review_frontend/README.md` → "Email intake (Gmail)". You end up with
   `gmail_token.json` (a portable refresh token; Workspace account = no 7-day expiry).

2. **Store it as an SSM SecureString** (it's a secret — never in the code tarball):
   ```bash
   aws ssm put-parameter --region "$AWS_REGION" --type SecureString \
     --name /grid-bff/gmail-token --value "file://$(pwd)/../../gmail_token.json"
   ```

3. **Apply with intake enabled:**
   ```bash
   cd infra/bff && terraform apply \
     -var "region=$AWS_REGION" -var "runtime_arn=$AGENTCORE_RUNTIME_ARN" \
     -var "s3_bucket=$GRID_S3_BUCKET" -var "s3_prefix=$GRID_S3_PREFIX" \
     -var "gmail_intake_enabled=true" \
     -var "gmail_token_ssm_param=/grid-bff/gmail-token" \
     -var 'gmail_query=is:unread has:attachment subject:(grid application)'
   ```
   This grants the instance role `bedrock:InvokeModel` (Claude family) + read of the token
   parameter, writes the intake env into `bff.env`, and fetches the token to
   `/opt/grid-bff/gmail_token.json` on boot. The poller starts with the service.

**Notes**
- **Single process** — the systemd unit runs one `grid-local-api` (no `--workers`), so exactly
  one poller polls the inbox. Idempotency is via Gmail labels.
- **Durability** — pending/accepted bundles live on the instance's EBS volume. They survive
  restart/stop-start but are **wiped on a code redeploy** (`user_data_replace_on_change`
  replaces the instance). For durable state, back `review_seed/{pending,applications}` with
  S3/EFS (separate follow-up).
- **Token rotation** — re-mint locally, `put-parameter --overwrite`, then
  `sudo systemctl restart grid-bff` (or re-apply to re-fetch on next boot).
- **The portal SPA isn't served here** — only `/api/review/*`. Run `review_frontend` locally
  pointed at the SSM tunnel (`:8000`), or serve the built SPA separately.

## Terraform

```bash
set -a; source ../../.env; set +a
terraform init
terraform plan
terraform apply \
  -var "region=$AWS_REGION" \
  -var "runtime_arn=$AGENTCORE_RUNTIME_ARN" \
  -var "s3_bucket=$GRID_S3_BUCKET" \
  -var "s3_prefix=$GRID_S3_PREFIX"
```
State is local (`terraform.tfstate`) — do not commit it (it can contain sensitive values).
Key variables are in `variables.tf` (`runtime_arn`, `s3_bucket`, `s3_prefix`, `instance_type`, `expose_public`).

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
