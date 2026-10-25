import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("forbidden", ["httpx", "docksight.application"])
def test_domain_contract_rejects_outward_imports(tmp_path: Path, forbidden: str) -> None:
    """Verify domain contract rejects outward imports."""
    config = Path(__file__).parents[2] / "pyproject.toml"
    for package in ["docksight", "docksight/domain", "docksight/application", "docksight/adapters"]:
        directory = tmp_path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "docksight/bootstrap.py").write_text("", encoding="utf-8")
    (tmp_path / "docksight/domain/rules.py").write_text(f"import {forbidden}\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(config),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Domain remains independent BROKEN" in result.stdout
