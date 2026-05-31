# Simple AgentCore Chatbot

Minimal AWS Bedrock AgentCore application that runs a simple chatbot agent with Claude Agent SDK and a Claude Sonnet model on Amazon Bedrock.

## What It Does

The app accepts a `prompt`, sends it through Claude Agent SDK, routes Claude model calls to Amazon Bedrock, and returns a text response. It intentionally has no tools, memory, RAG, or external integrations.

## Design

```text
User / CLI / API
  -> AWS Bedrock AgentCore Runtime
  -> app/SimpleAgentCore/main.py
  -> Claude Agent SDK
  -> Claude Sonnet on Amazon Bedrock
  -> response returned to user
```

## Files

- `app/SimpleAgentCore/main.py` - AgentCore Runtime entrypoint.
- `app/SimpleAgentCore/chatbot.py` - Claude Agent SDK wrapper.
- `app/SimpleAgentCore/local_chat.py` - direct local CLI invocation.
- `app/SimpleAgentCore/pyproject.toml` - Python dependencies for local `uv` and AgentCore packaging.
- `agentcore/agentcore.json` - AgentCore CLI project/runtime config.
- `agentcore/aws-targets.example.json` - template for account/region deployment target.
- `agentcore/cdk/` - generated CDK app used by `agentcore deploy`.
- `.env.example` - local environment template without real secrets.
- `tests/test_chatbot.py` - local validation for prompt/response handling.

## Prerequisites

- Python 3.10 or later.
- `uv` for Python dependency management.
- Node.js 20 or later and npm for the AWS AgentCore CLI.
- AWS CLI v2 for credentials, account lookup, and Bedrock access checks.
- AWS credentials through either `AWS_PROFILE`, explicit AWS environment variables, SSO, or an AgentCore execution role.
- Amazon Bedrock model access enabled for the selected Anthropic Claude Sonnet model in your AWS region.
- IAM permissions to deploy AgentCore Runtime resources with the AgentCore CLI/CDK, plus runtime permission to call the selected Bedrock model.

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

Install the AgentCore CLI if needed:

```bash
npm install -g @aws/agentcore
agentcore --version
```

## Setup With uv

From the repository root:

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
cd app/SimpleAgentCore
uv sync --extra dev
cd ../..
npm install --prefix agentcore/cdk
cp .env.example .env
```

Do not activate a separate `.venv` manually when using this project. `uv` creates and uses `app/SimpleAgentCore/.venv` automatically. If you see a warning like `VIRTUAL_ENV=... does not match the project environment path .venv`, your shell still has another virtual environment active; run `deactivate 2>/dev/null || true` and `unset VIRTUAL_ENV`, then rerun the `uv` command.

Edit `.env` for your account and region:

```bash
AWS_REGION=us-west-2
AWS_PROFILE=default
CLAUDE_CODE_USE_BEDROCK=1
ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
```

If that Sonnet model ID is not enabled in your region/account, replace `ANTHROPIC_MODEL` with an enabled Claude Sonnet Bedrock model or inference profile ID.

Check AWS identity and model access:

```bash
set -a
source .env
set +a
aws sts get-caller-identity
aws bedrock list-foundation-models --region "$AWS_REGION" --by-provider Anthropic
```

## Claude Agent SDK Settings

This project uses Claude Agent SDK through its Claude Code Bedrock provider. These are the important settings:

- `CLAUDE_CODE_USE_BEDROCK=1` - required. Tells Claude Agent SDK/Claude Code to use Amazon Bedrock instead of Anthropic direct API auth.
- `AWS_REGION` - required for Bedrock-backed Claude Agent SDK calls. Use the same region where the Anthropic model is enabled.
- `ANTHROPIC_MODEL` - required for predictable demos. Use a Bedrock Claude Sonnet model ID or inference profile ID.
- `AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` - required locally so Bedrock can authenticate the model call.
- `AGENT_SYSTEM_PROMPT` - optional app setting used by `chatbot.py`; this is not a Claude Agent SDK provider setting.

You do not set `ANTHROPIC_API_KEY` for this project because the model call goes through Amazon Bedrock. Bedrock authenticates with AWS IAM credentials and bills through AWS.

## AWS Credentials

There is no committed secret key because secrets must not live in source control. You still need credentials locally; choose one method.

Profile-based credentials:

```bash
aws configure sso --profile default
aws sso login --profile default
```

Then use this in `.env`:

```bash
AWS_PROFILE=default
AWS_REGION=us-west-2
```

Explicit temporary credentials:

```bash
AWS_REGION=us-west-2
AWS_ACCESS_KEY_ID=replace-with-access-key-id
AWS_SECRET_ACCESS_KEY=replace-with-secret-access-key
AWS_SESSION_TOKEN=replace-with-session-token-if-needed
```

For deployed AgentCore Runtime, do not ship local credentials. The runtime should use its AWS execution role. That role needs only the Bedrock invoke permissions for the configured Claude Sonnet model.

## AgentCore Config Guide

AgentCore deployment uses two local config files:

- `agentcore/agentcore.json` - committed project/runtime definition.
- `agentcore/aws-targets.json` - local account/region target. This is ignored by git because it is account-specific.

It also uses `agentcore/cdk/`, a generated CDK project required by `agentcore deploy`. Do not delete it. If it is missing, deployment fails with `CDK project not found at .../agentcore/cdk`.

Create `agentcore/aws-targets.json`:

```bash
cp agentcore/aws-targets.example.json agentcore/aws-targets.json
```

Fill it with your AWS account and deployment region:

```json
[
  {
    "name": "default",
    "description": "Default deployment target for SimpleAgentCore",
    "account": "123456789012",
    "region": "us-west-2"
  }
]
```

Get the account value from AWS:

```bash
aws sts get-caller-identity --query Account --output text
```

Use the same region as `AWS_REGION` unless you intentionally deploy AgentCore and Bedrock model access in another supported region.

`agentcore/agentcore.json` fields:

- `$schema` - AgentCore JSON schema URL used by editor tooling and validation.
- `name` - AgentCore project name. Keep `SimpleAgentCore` unless you want a different deployed project name.
- `version` - config schema version. Keep `1`.
- `managedBy` - `CDK`; the AgentCore CLI deploys infrastructure through CDK.
- `tags` - AWS tags applied by the project. Safe to edit for ownership/cost tracking.
- `runtimes[0].name` - runtime agent name shown in AgentCore.
- `runtimes[0].build` - `CodeZip`; packages the Python app directory as source. Use `Container` only if you add system dependencies.
- `runtimes[0].entrypoint` - `main.py`; resolved inside `codeLocation`.
- `runtimes[0].codeLocation` - `app/SimpleAgentCore/`; must contain `main.py` and `pyproject.toml`.
- `runtimes[0].runtimeVersion` - AWS runtime Python version. This project uses `PYTHON_3_14`.
- `runtimes[0].networkMode` - `PUBLIC`; simplest demo networking. Change only if you are ready to configure VPC networking.
- `runtimes[0].protocol` - `HTTP`; `main.py` exposes the AgentCore HTTP invocation handler.
- `runtimes[0].instrumentation.enableOtel` - `false` for this minimal CodeZip demo, so AgentCore starts `main.py` directly without requiring OpenTelemetry packages in the ZIP.
- `runtimes[0].envVars` - non-secret runtime environment values deployed with AgentCore. This project sets `AWS_REGION`, `CLAUDE_CODE_USE_BEDROCK`, `ANTHROPIC_MODEL`, and `AGENT_SYSTEM_PROMPT` here so the deployed runtime can call Bedrock without a local `.env` file.
- `memories`, `credentials`, `evaluators`, `onlineEvalConfigs`, `agentCoreGateways`, `policyEngines`, `configBundles`, `abTests`, `httpGateways`, `harnesses`, `datasets` - intentionally empty for this minimal chatbot.

Before deploying, confirm these match:

```bash
grep -E '^(AWS_REGION|AWS_PROFILE|CLAUDE_CODE_USE_BEDROCK|ANTHROPIC_MODEL)=' .env
python3 -m json.tool agentcore/aws-targets.json
python3 -m json.tool agentcore/agentcore.json
npm install --prefix agentcore/cdk
agentcore validate
```

The important consistency checks are:

- `.env` `AWS_REGION` equals the `region` value for the `default` entry in `agentcore/aws-targets.json`.
- `.env` `ANTHROPIC_MODEL` is available in that region/account.
- `agentcore/agentcore.json` `codeLocation` points to `app/SimpleAgentCore/`.
- `entrypoint` is `main.py`.
- `runtimes[0].envVars` has the same `AWS_REGION`, `CLAUDE_CODE_USE_BEDROCK`, and `ANTHROPIC_MODEL` values you tested locally.

## Run Locally

Direct local invocation:

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
set -a
source .env
set +a
cd app/SimpleAgentCore
uv run python local_chat.py "Explain AgentCore in one paragraph."
```

AgentCore local development server from the repository root:

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
set -a
source .env
set +a
agentcore dev --no-browser --port 8080
```

In another terminal:

```bash
curl -s http://127.0.0.1:8080/invocations \
  -H "content-type: application/json" \
  -d '{"prompt":"Hello, what can you do?"}'
```

## Deploy

Run the non-AWS local checks first:

```bash
set -a
source .env
set +a
npm install --prefix agentcore/cdk
agentcore validate
```

Preview the deployment. This still needs valid AWS credentials because AgentCore checks the target account and region:

```bash
agentcore deploy --dry-run
```

Deploy to AWS Bedrock AgentCore Runtime:

```bash
agentcore deploy
```

Check status:

```bash
agentcore status
```

## Invoke Deployed Agent

```bash
agentcore invoke --prompt "Give me a short checklist for launching a demo agent."
```

For a continued conversation:

```bash
agentcore invoke --session-id demo-session --prompt "My project is a Bedrock chatbot."
agentcore invoke --session-id demo-session --prompt "What should I test next?"
```

## How It Works Internally

`main.py` creates a `BedrockAgentCoreApp` and exposes one `@app.entrypoint` function. The handler validates that the incoming payload contains a non-empty `prompt`, then calls `ask_claude`.

`ask_claude` sets conservative defaults for Bedrock-backed Claude Agent SDK usage, builds `ClaudeAgentOptions`, disables tools, invokes `query()`, and extracts text from the SDK message stream. For CodeZip deployments, `chatbot.py` also ensures the bundled Claude CLI is executable before passing its path to Claude Agent SDK.

AgentCore packages `app/SimpleAgentCore/` as a CodeZip app using `agentcore/agentcore.json`, then hosts it as an HTTP AgentCore Runtime endpoint.

## Prompt Workflow

Local direct CLI flow:

```text
Terminal prompt argument
  -> app/SimpleAgentCore/local_chat.py
  -> load .env from repository root/current shell
  -> chatbot.ask_claude(prompt)
  -> Claude Agent SDK query()
  -> Amazon Bedrock InvokeModel/streaming invoke using AWS credentials
  -> Claude Sonnet response events
  -> collect_text()
  -> final text printed to stdout
```

Input shape:

```bash
uv run python local_chat.py "Explain AgentCore in one paragraph."
```

Output shape:

```text
AgentCore is ...
```

Local AgentCore server flow:

```text
HTTP POST /invocations with {"prompt": "..."}
  -> local AgentCore dev server
  -> app/SimpleAgentCore/main.py invoke(payload)
  -> validate payload["prompt"]
  -> chatbot.ask_claude(prompt)
  -> Claude Agent SDK
  -> Amazon Bedrock Claude Sonnet
  -> {"response": "..."} or {"error": "..."}
```

Input shape:

```json
{"prompt":"Hello, what can you do?"}
```

Successful output shape:

```json
{"response":"..."}
```

Validation or runtime error output shape:

```json
{"error":"..."}
```

Deployed AWS flow:

```text
agentcore deploy
  -> AgentCore CLI reads agentcore/agentcore.json
  -> AgentCore CLI reads agentcore/aws-targets.json
  -> AgentCore CLI uses agentcore/cdk to synthesize/deploy CloudFormation
  -> packages app/SimpleAgentCore/ as CodeZip
  -> deploys an AgentCore Runtime in the target AWS account/region
  -> runtime starts main.py in AWS

agentcore invoke --prompt "..."
  -> AgentCore Runtime endpoint
  -> deployed main.py invoke(payload)
  -> Claude Agent SDK running inside AWS runtime
  -> Amazon Bedrock Claude Sonnet in AWS_REGION
  -> response returned through AgentCore Runtime
  -> CLI prints the response
```

The deployed runtime should use its AWS execution role, not local `.env` secrets. Local `.env` is for your laptop commands: selecting region/model and authenticating the deployment/invocation CLI. In AWS, IAM role permissions replace local access keys.

## AWS Permissions

For local model invocation, the caller needs permission to invoke the chosen Bedrock model, usually including:

```text
bedrock:InvokeModel
bedrock:InvokeModelWithResponseStream
```

For deployment, the caller also needs permissions required by the AgentCore CLI/CDK to create and update AgentCore Runtime, IAM roles/policies, CloudFormation stacks, S3 assets, CloudWatch logs, and related deployment resources.

The runtime execution role should be kept narrow: grant only the Bedrock invoke permissions needed for the configured Claude Sonnet model.

## Verify

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
cd app/SimpleAgentCore
uv run pytest ../../tests
uv run python -m py_compile main.py chatbot.py local_chat.py ../../tests/test_chatbot.py
```

## Clean Up

```bash
agentcore remove all
agentcore deploy
```
