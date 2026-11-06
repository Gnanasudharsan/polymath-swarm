"""Call Polymath Swarm from any A2A client (here: the official a2a-sdk).

    POLYMATH_API_KEY=... uv run python examples/a2a_client.py "Compute 2^10 + 1; is it prime?"
    uv run python examples/a2a_client.py --agent compute "Is 97 prime?"   # one specialist

Discovers the Agent Card, sends the problem with message/send, prints the evidence report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os

import httpx
from a2a import helpers
from a2a.client import ClientConfig, ClientFactory
from a2a.types import Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict


async def main(url: str, problem: str, agent: str | None) -> None:
    base = f"{url.rstrip('/')}/agents/{agent}" if agent else url.rstrip("/")
    headers = {"x-api-key": os.environ.get("POLYMATH_API_KEY", "")}
    async with httpx.AsyncClient(headers=headers, timeout=900) as http:
        card = (await http.get(f"{base}/.well-known/agent-card.json")).json()
        print(f"agent: {card['name']} — {card['description'][:90]}…")
        client = await ClientFactory(ClientConfig(httpx_client=http, streaming=False)
                                     ).create_from_url(base)  # fmt: skip
        message = helpers.new_text_message(problem, role=Role.ROLE_USER)
        async for resp in client.send_message(SendMessageRequest(message=message)):
            task = MessageToDict(resp).get("task", {})
            print(f"state: {task.get('status', {}).get('state')}\n")
            for artifact in task.get("artifacts", []):
                for part in artifact.get("parts", []):
                    if "text" in part:
                        print(part["text"])
                    elif "data" in part:
                        data = part["data"]
                        summary = {k: data[k] for k in ("run_id", "status") if k in data}
                        print(json.dumps(summary or data, indent=2)[:1500])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("problem")
    parser.add_argument("--url", default=os.environ.get("POLYMATH_URL", "http://localhost:8000"))
    parser.add_argument(
        "--agent", default=None, help="literature | reasoner | compute | formalizer | critic"
    )
    args = parser.parse_args()
    asyncio.run(main(args.url, args.problem, args.agent))
