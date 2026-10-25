import argparse
import json
import os
from uuid import uuid4

import httpx
from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect DockSight responses and confirm an action"
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    commands = parser.add_subparsers(dest="command", required=True)
    diagnose = commands.add_parser("diagnose", help="Stream a diagnostic turn")
    diagnose.add_argument(
        "query",
        nargs="?",
        default="Why did the worker in Compose project docksight-demo exit?",
    )
    diagnose.add_argument("--host", default="local")
    execute = commands.add_parser(
        "execute", help="Execute a previously prepared action"
    )
    execute.add_argument("action_id")
    execute.add_argument("--confirm", action="store_true")
    execute.add_argument(
        "--key", default=None, help="Reuse this key when retrying the same action"
    )
    state = commands.add_parser("state", help="Read an action outcome")
    state.add_argument("action_id")
    args = parser.parse_args()
    if args.command == "execute" and not args.confirm:
        parser.error("Execution requires --confirm after reviewing the action")
    load_dotenv()
    token = os.getenv("DOCKSIGHT_API_TOKEN")
    if not token:
        parser.error("Set DOCKSIGHT_API_TOKEN or configure it in .env")
    try:
        with httpx.Client(
            base_url=args.url, headers={"Authorization": f"Bearer {token}"}, timeout=300
        ) as client:
            if args.command == "diagnose":
                with client.stream(
                    "POST",
                    "/api/v1/chat/turns",
                    json={"host": args.host, "query": args.query},
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line.startswith("data: "):
                            event = json.loads(line[6:])
                            print(json.dumps(event, indent=2, ensure_ascii=False))
                            if event["type"] == "turn.failed":
                                raise SystemExit(1)
            elif args.command == "execute":
                key = args.key or str(uuid4())
                print(f"Idempotency key: {key}")
                response = client.post(
                    f"/api/v1/actions/{args.action_id}/execute",
                    json={"confirmed": True},
                    headers={"Idempotency-Key": key},
                )
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2))
            else:
                response = client.get(f"/api/v1/actions/{args.action_id}")
                response.raise_for_status()
                print(json.dumps(response.json(), indent=2))
    except httpx.HTTPError as exc:
        print(
            f"DockSight request failed ({type(exc).__name__}). Check the server and action state."
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
