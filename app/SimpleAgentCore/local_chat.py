from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv

from chatbot import ask_claude


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SimpleAgentCore chatbot locally.")
    parser.add_argument("prompt", help="Prompt to send to Claude through Amazon Bedrock.")
    args = parser.parse_args()

    load_dotenv()
    print(await ask_claude(args.prompt))


if __name__ == "__main__":
    asyncio.run(main())
