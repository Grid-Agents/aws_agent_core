# simple_agent_core.md

## Purpose

Create a minimal demo that uses Claude Agent SDK with a Claude Sonnet model and deploys it to AWS Bedrock AgentCore Runtime.

The app can be a simple chatbot that accepts a user prompt and returns a Claude-generated response.

## Status

Completed baseline. Keep this document as the reference for the simple chatbot
demo. Plan the next Grid document retrieval implementation in
`docs/grid_agents.md` rather than expanding this file.

## Target Architecture

```text
User prompt
  -> AgentCore Runtime endpoint
  -> Python AgentCore app
  -> Claude Agent SDK
  -> Claude Sonnet on Amazon Bedrock
  -> final chatbot response
```

## User Instructions
In the README.md, specify the step-by-step guide for all commands including setup, launch, deploy, and invocation.

## Expected Result

A minimal deployed chatbot agent running on AWS Bedrock AgentCore Runtime, using Claude Agent SDK as the agent harness and Claude Sonnet through Amazon Bedrock as the model.

## Implementation Notes

- Agent source lives in `app/SimpleAgentCore/`.
- AgentCore CLI configuration lives in `agentcore/`.
- Local Python dependency management uses `uv`.
- Local direct invocation is available through `app/SimpleAgentCore/local_chat.py`.
- Runtime deployment uses the CodeZip AgentCore Runtime config in `agentcore/agentcore.json`.
