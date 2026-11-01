import os
import re
import subprocess
import sys

import pytest

from tests.integration.live_e2e.lab import ROOT


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["--e2e-suite", "causal"],
            {
                "oom",
                "unknown-exit",
                "clean-shutdown",
                "unhealthy",
                "running-history",
                "compose-follow-up-noisy",
                "compose-follow-up-shutdown",
            },
        ),
        (["--e2e-case", "oom"], {"oom"}),
        (
            ["--e2e-suite", "causal", "--e2e-case", "compose-explicit"],
            {
                "oom",
                "unknown-exit",
                "clean-shutdown",
                "unhealthy",
                "running-history",
                "compose-follow-up-noisy",
                "compose-follow-up-shutdown",
                "compose-explicit",
            },
        ),
    ],
)
def test_cli_collects_only_the_requested_scenario_packages_without_starting_workloads(
    arguments: list[str], expected: set[str]
) -> None:
    environment = os.environ.copy()
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests/integration/live_e2e/test_diagnostics.py",
            "backend/tests/integration/live_e2e/test_follow_up.py",
            "--collect-only",
            "--no-cov",
            "-q",
            "-o",
            "addopts=",
            "--e2e-language",
            "en",
            "--e2e-model",
            "disabled",
            *arguments,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = set(re.findall(r"\[disabled-([a-z-]+)-en(?:\]|-)", result.stdout))
    assert collected == expected
