import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def architecture_project(tmp_path: Path) -> Path:
    """Create the package boundaries required by every real architecture contract."""
    for package in (
        "docksight",
        "docksight/domain",
        "docksight/application",
        "docksight/adapters",
        "docksight/adapters/inbound",
        "docksight/adapters/outbound",
    ):
        directory = tmp_path / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "docksight/bootstrap.py").write_text("", encoding="utf-8")
    return tmp_path


def lint_project(project: Path) -> subprocess.CompletedProcess[str]:
    """Evaluate real import-linter contracts against an isolated package tree."""
    config = Path(__file__).parents[2] / "pyproject.toml"
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(config),
            "--no-cache",
        ],
        cwd=project,
        env={**os.environ, "PYTHONPATH": str(project)},
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("forbidden", ["httpx", "docksight.application", "sqlalchemy", "alembic", "portalocker"])
def test_domain_contract_rejects_outward_imports(architecture_project: Path, forbidden: str) -> None:
    (architecture_project / "docksight/domain/rules.py").write_text(
        f"import {forbidden}\n", encoding="utf-8", newline="\n"
    )
    result = lint_project(architecture_project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Domain remains independent BROKEN" in result.stdout


@pytest.mark.parametrize("forbidden", ["sqlalchemy", "alembic", "portalocker"])
def test_application_contract_rejects_storage_libraries(architecture_project: Path, forbidden: str) -> None:
    (architecture_project / "docksight/application/archive.py").write_text(
        f"import {forbidden}\n", encoding="utf-8", newline="\n"
    )
    result = lint_project(architecture_project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Application owns its ports BROKEN" in result.stdout


@pytest.mark.parametrize(("source", "target"), [("inbound", "outbound"), ("outbound", "inbound")])
def test_adapter_contract_rejects_cross_imports(architecture_project: Path, source: str, target: str) -> None:
    (architecture_project / f"docksight/adapters/{source}/bridge.py").write_text(
        f"import docksight.adapters.{target}\n", encoding="utf-8", newline="\n"
    )
    result = lint_project(architecture_project)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Inbound and outbound adapters remain independent BROKEN" in result.stdout


def test_contracts_allow_inward_imports_and_bootstrap_wiring(architecture_project: Path) -> None:
    for adapter in ("inbound", "outbound"):
        (architecture_project / f"docksight/adapters/{adapter}/bridge.py").write_text(
            "import docksight.application\n", encoding="utf-8", newline="\n"
        )
    (architecture_project / "docksight/bootstrap.py").write_text(
        "import docksight.adapters.inbound.bridge\nimport docksight.adapters.outbound.bridge\n",
        encoding="utf-8",
        newline="\n",
    )
    result = lint_project(architecture_project)
    assert result.returncode == 0, result.stdout + result.stderr
