# AGENTS.md

## Project Goal

Build AWS Bedrock AgentCore applications that run Claude Agent SDK agents with
Claude Sonnet models on Amazon Bedrock.

The completed baseline is a minimal chatbot demo. The next implementation is
the Grid Agents system described in `docs/grid_agents.md`.

## Planning Rules

- Treat `docs/simple_agent_core.md` as the completed baseline plan.
- Treat `docs/grid_agents.md` as the active implementation playbook for the
  Grid Agents work.
- Codex is allowed to refine planning documents under `docs/` over time as it
  learns more from the codebase, official AWS resources, AWS constraints, and the sibling
  `/Users/maoxunhuang/Desktop/GridAgents/claude_agent` project.
- Keep planning documents clear, current, and concise. Prefer updating the plan
  before making broad implementation changes.
- When the user asks for planning only, edit only `AGENTS.md` and markdown files
  under `docs/`.

## Required Deliverables

Maintain:

- `README.md`
- `docs/simple_agent_core.md`
- `docs/grid_agents.md`
- Agent application source code
- Frontend source code for interacting with the agent
- Deployment/configuration files needed by AWS Bedrock AgentCore Runtime
- Index build and upload scripts/configuration for Grid documents

## README.md Requirement

Always maintain a practical and concise `README.md` that explains:

1. What the system does
2. The high-level system design
3. Main components and file structure
4. How to install dependencies
5. How to run the agent locally
6. How to build Grid document indexes
7. How to upload raw documents and indexes to AWS
8. How to deploy the agent to AWS Bedrock AgentCore Runtime
9. How to configure AgentCore isolation and scalability
10. How to invoke/test the deployed agent
11. How to run the frontend
12. How the agent works internally
13. Required environment variables and AWS permissions

The README should help a new engineer understand, run, deploy, and test the
project without reading all source files first.

## System Design Expectations

### Simple AgentCore Baseline

```text
User / CLI / API
  -> AWS Bedrock AgentCore Runtime
  -> Python app entrypoint
  -> Claude Agent SDK agent
  -> Claude Sonnet model through Amazon Bedrock
  -> response returned to user
```

### Grid Agents Target

```text
User / Web UI / CLI
  -> Frontend/API
  -> AWS Bedrock AgentCore Runtime
  -> Python app entrypoint
  -> Claude Agent SDK root agent and subagents
  -> retrieval tools over Grid raw documents and indexes
  -> Claude Sonnet model through Amazon Bedrock
  -> cited answer plus observable agent trajectory
```

The Grid Agents implementation should adapt the useful behavior from
`/Users/maoxunhuang/Desktop/GridAgents/claude_agent`, but it should not copy
unrelated benchmark/demo behavior unless it is needed for Grid document search.

## Implementation Guidelines

- Python for the AgentCore runtime.
- Use Claude Agent SDK as the agent harness.
- Use Amazon Bedrock as the model provider.
- Use a Claude Sonnet model available in the configured AWS region.
- Deploy the app on AWS Bedrock AgentCore Runtime.
- Use environment variables for region, model ID, data locations, index
  locations, and runtime configuration.
- Do not hard-code secrets or AWS credentials. Use `.env` locally and AWS IAM
  roles in deployed runtime.
- Keep tool permissions restrictive. Retrieval tools should read only the Grid
  document corpus and index artifacts they need.
- Keep the implementation small and readable. Avoid speculative abstractions.
- Add comments only where they clarify non-obvious behavior.
- Preserve observable agent-loop events, tool calls, subagent calls, citations,
  latency, and errors. Do not claim to expose hidden model chain-of-thought.

## Quality Bar

Before finishing implementation changes, verify that:

- The app can run locally.
- The index build script can build Grid document vector, PageIndex, and GraphRAG
  artifacts or clearly report missing prerequisites.
- Raw Grid documents and index artifacts can be uploaded/deployed to AWS.
- The AgentCore runtime can access the configured raw documents and indexes.
- The README commands match the actual commands.
- Deployment instructions are present and cover isolation and scalability.
- The frontend can ask questions and display expandable root-agent and subagent
  trajectories.
- Errors are handled clearly.
- No credentials are committed.