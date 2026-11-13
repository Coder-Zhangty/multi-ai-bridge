"""Simple CLI for quick single-message testing.

Usage:
    python cli.py chatgpt "Hello, who are you?"
    python cli.py deepseek "Hello" --no-stream
    python cli.py --list   # list configured platforms
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# Fix Windows console encoding for Chinese output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings
from app.pool.dispatcher import Dispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cli")


async def main():
    parser = argparse.ArgumentParser(description="Multi-AI Bridge CLI")
    parser.add_argument("platform", nargs="?", help="Target platform (chatgpt, claude, gemini, ...)")
    parser.add_argument("message", nargs="?", help="Message to send")
    parser.add_argument("--conversation-id", "-c", default=None)
    parser.add_argument("--no-stream", action="store_true", help="Print full reply at once")
    parser.add_argument("--list", action="store_true", help="List configured platforms")
    parser.add_argument("--health", action="store_true", help="Show pool health")
    parser.add_argument("--timeout", "-t", type=float, default=180.0)
    args = parser.parse_args()

    settings = get_settings()
    dispatcher = Dispatcher(settings)

    try:
        await dispatcher.start()

        if args.list or (not args.platform and not args.health):
            print("Configured platforms:")
            for p in dispatcher.platforms:
                mode = dispatcher.settings.get_platform_mode(p)
                pool = dispatcher._pools.get(p)
                api = dispatcher._api_adapters.get(p)
                parts = [f"mode={mode}"]
                if pool:
                    parts.append(f"browser({pool.healthy_count}h/{pool.idle_count}i)")
                if api:
                    parts.append("api")
                print(f"  {p}: {', '.join(parts)}")
            if not args.health:
                return

        if args.health:
            import json
            print(json.dumps([h.model_dump() for h in dispatcher.health()], indent=2, ensure_ascii=False))
            return

        if not args.platform or not args.message:
            parser.print_help()
            return

        if args.platform not in dispatcher.platforms:
            print(f"Error: platform '{args.platform}' not available.")
            print(f"Available: {dispatcher.platforms}")
            sys.exit(1)

        print(f"\nSending to {args.platform}...\n")

        if args.no_stream:
            result = await dispatcher.chat(
                platform=args.platform,
                message=args.message,
                conversation_id=args.conversation_id,
                timeout=args.timeout,
            )
            print(result["reply"])
            print(f"\n--- conversation_id: {result['conversation_id']} ---")
        else:
            last_conv_id = None
            async for chunk in dispatcher.chat_stream(
                platform=args.platform,
                message=args.message,
                conversation_id=args.conversation_id,
                timeout=args.timeout,
            ):
                if chunk["event"] == "chunk":
                    print(chunk["delta"], end="", flush=True)
                    last_conv_id = chunk.get("conversation_id")
                elif chunk["event"] == "done":
                    print(f"\n\n--- conversation_id: {chunk['conversation_id']} ---")

    finally:
        await dispatcher.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
