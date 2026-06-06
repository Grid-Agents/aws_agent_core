from __future__ import annotations

from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv


load_dotenv()

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict[str, Any]):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        yield {"type": "error", "error": "Payload must include a non-empty 'prompt' string."}
        return
    from grid_agent_core.agent import run_grid_agent_events

    async for event in run_grid_agent_events(payload):
        yield event


if __name__ == "__main__":
    app.run()
