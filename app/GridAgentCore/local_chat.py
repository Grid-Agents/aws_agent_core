from __future__ import annotations

import argparse
import asyncio
import json

from dotenv import load_dotenv

from grid_agent_core.agent import run_grid_agent_events


async def _run(payload: dict) -> None:
    async for event in run_grid_agent_events(payload):
        print(json.dumps(event, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Grid AgentCore locally.")
    parser.add_argument("prompt")
    parser.add_argument("--methods", default="vector,pageindex,find")
    parser.add_argument("--allow-sdk-file-tools", action="store_true")
    parser.add_argument("--disable-subagents", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    payload = {
        "prompt": args.prompt,
        "methods": [item.strip() for item in args.methods.split(",") if item.strip()],
        "allow_sdk_file_tools": args.allow_sdk_file_tools,
        "enable_subagents": not args.disable_subagents,
    }
    asyncio.run(_run(payload))


if __name__ == "__main__":
    main()
