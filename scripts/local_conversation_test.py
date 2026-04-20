from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.conversation import ConversationManager


async def main() -> None:
    manager = ConversationManager(caller_phone_number="+15555550123")
    print("Ashley local test started. Type 'quit' to stop.\n")

    while True:
        caller_text = input("Caller: ").strip()
        if caller_text.lower() in {"quit", "exit"}:
            manager.cleanup()
            print("Ended.")
            return

        if not caller_text:
            continue

        result = await manager.handle_caller_input(caller_text)
        print(f"\nAshley: {result.response_text}\n")

        if result.call_complete:
            print("Call complete.")
            return


if __name__ == "__main__":
    asyncio.run(main())
