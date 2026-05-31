from __future__ import annotations

from typing import Any

from bedrock_agentcore import BedrockAgentCoreApp
from dotenv import load_dotenv

from chatbot import ask_claude


load_dotenv()

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict[str, Any]) -> dict[str, str]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "Payload must include a non-empty 'prompt' string."}

    try:
        return {"response": await ask_claude(prompt)}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    app.run()
