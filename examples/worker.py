import time
from pathlib import Path


def main() -> None:
    attempted = Path("/state/attempted")
    if not attempted.exists():
        attempted.touch()
        print(
            "DemoInitializationError: first startup attempt failed. Start the container again to retry initialization.",
            flush=True,
        )
        raise SystemExit(1)
    print("Worker initialized and ready", flush=True)
    Path("/state/healthy").touch()
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
