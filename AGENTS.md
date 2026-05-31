# AGENTS.md

## Goal

Build a minimal AWS Bedrock AgentCore application that runs a simple chatbot agent using Claude Agent SDK with a Claude Sonnet model on Amazon Bedrock.

The implementation should be clear, minimal, and easy to run locally and deploy to AWS AgentCore Runtime.

## Required Deliverables

Maintain the following files:

- `README.md`
- `simple_agent_core.md`
- Agent application source code
- Deployment/configuration files needed by AWS AgentCore

## README.md Requirement

Always maintain a `README.md` that explains:

1. What the system does
2. The high-level system design
3. Main components and file structure
4. How to install dependencies
5. How to run the agent locally
6. How to deploy the agent to AWS Bedrock AgentCore Runtime
7. How to invoke/test the deployed agent
8. How the agent works internally
9. Required environment variables and AWS permissions

Keep the README practical and concise. It should help a new engineer understand, run, and deploy the project without reading all source files first.

## System Design Expectations

Use this architecture:

```text
User / CLI / API
  -> AWS Bedrock AgentCore Runtime
  -> Python app entrypoint
  -> Claude Agent SDK agent
  -> Claude Sonnet model through Amazon Bedrock
  -> response returned to user
```

The initial version should be a simple chatbot. It does not need advanced memory, RAG, or external tools unless they are added later.

## Implementation Guidelines

- Python.
- Keep the application small and readable.
- Use Claude Agent SDK as the agent harness.
- Use Amazon Bedrock as the model provider.
- Use a Claude Sonnet model available in the configured AWS region.
- Deploy the app on AWS Bedrock AgentCore Runtime.
- Keep tool permissions restrictive.
- Avoid unnecessary abstractions.
- Add comments only where they clarify non-obvious behavior.
- Do not hard-code secrets or AWS credentials. (Use ".env" file instead)
- Use environment variables for region, model ID, and runtime configuration.

## Quality Bar

Before finishing changes, verify that:

- The app can run locally.
- The README instructions match the actual commands. (step by step guide)
- The deployment instructions are present.
- The code path is simple enough for a demo.
- Errors are handled clearly.
- No credentials are committed.

## Note
You are allowed to maintain and adjust the plan in "docs/" to be your implementation plan playbook.