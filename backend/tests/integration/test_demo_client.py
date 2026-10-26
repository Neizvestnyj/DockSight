import subprocess
import sys
from pathlib import Path


def test_demo_client_refuses_execution_without_confirmation() -> None:
    script = Path(__file__).parents[3] / "examples/demo.py"
    result = subprocess.run(
        [sys.executable, str(script), "execute", "00000000-0000-0000-0000-000000000000"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "--confirm" in result.stderr
