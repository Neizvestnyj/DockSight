from dataclasses import asdict

import pytest

from docksight.adapters.outbound.docker.mapping import map_container, map_metrics, parse_logs
from docksight.application.redaction import Redactor
from docksight.domain.errors import DockSightError


@pytest.mark.parametrize("health", ["starting", "healthy", "unhealthy"])
def test_inspect_keeps_health_separate_from_process_state_and_discards_probe_output(health: str) -> None:
    result = map_container(
        {
            "Id": "a" * 64,
            "Name": "/api",
            "State": {
                "Status": "running",
                "Health": {"Status": health, "FailingStreak": 3, "Log": [{"Output": "probe-secret-sentinel"}]},
            },
        },
        "local",
        (),
        Redactor(),
    )
    assert result.state == "running"
    assert result.health == health
    assert "probe-secret-sentinel" not in str(asdict(result))
    assert "FailingStreak" not in asdict(result)


@pytest.mark.parametrize(
    "state",
    [{"Status": "running"}, {"Status": "running", "Health": None}, {"Status": "running", "Health": {"Status": "none"}}],
)
def test_missing_health_is_not_reported_as_healthy(state: dict[str, object]) -> None:
    result = map_container({"Id": "a" * 64, "Name": "/api", "State": state}, "local", (), Redactor())
    assert result.health is None


@pytest.mark.parametrize("health", [{"Status": "degraded"}, {"Status": 1}, {}, "unhealthy", []])
def test_invalid_health_fails_with_a_typed_runtime_error(health: object) -> None:
    with pytest.raises(DockSightError) as caught:
        map_container(
            {"Id": "a" * 64, "Name": "/api", "State": {"Status": "running", "Health": health}},
            "local",
            (),
            Redactor(),
        )
    assert caught.value.code == "invalid_runtime_data"


def test_log_byte_and_line_limits_keep_the_latest_complete_rows_in_order() -> None:
    raw = (
        b"2026-10-01T00:00:00Z ERROR: historical SQL failure\n" * 100
        + b"2026-10-27T14:02:05Z LOG: received fast shutdown request\n"
        + b"2026-10-27T14:02:06Z LOG: database system is shut down\n"
    )
    for budget, lines in [(128, 200), (65536, 2)]:
        batch = parse_logs(raw, Redactor(), budget, lines)
        assert [row.message for row in batch.entries] == [
            "LOG: received fast shutdown request",
            "LOG: database system is shut down",
        ]
        assert batch.entries[-1].timestamp is not None
        assert batch.entries[-1].timestamp.day == 27
        assert batch.truncated


def test_tail_clipping_redacts_secrets_before_selecting_the_byte_window() -> None:
    secret = "private-sensitive-boundary-" + "A" * 104
    raw = ("historical\n" * 200 + f"2026-10-27T14:02:06Z value={secret}\n").encode()
    batch = parse_logs(raw, Redactor((secret,)), 64, 200)
    assert batch.entries[-1].message == "value=[REDACTED]"
    assert secret not in "\n".join(row.message for row in batch.entries)
    assert batch.truncated


def test_inspect_discards_secrets_and_preserves_oom_evidence() -> None:
    raw = {
        "Id": "a" * 64,
        "Name": "/worker",
        "RestartCount": 2,
        "Config": {
            "Image": "worker:1",
            "Env": ["APP_ENV=test", "DB_PASSWORD=hunter22"],
            "Labels": {"com.docker.compose.project": "demo"},
        },
        "State": {
            "Status": "exited",
            "ExitCode": 137,
            "OOMKilled": True,
            "StartedAt": "2026-01-01T10:00:00.123456789Z",
        },
    }
    result = map_container(raw, "local", ("APP_ENV", "DB_PASSWORD"), Redactor())
    assert result.state == "exited"
    assert result.oom_killed is True
    assert result.environment == (("APP_ENV", "test"),)
    assert result.started_at is not None
    assert result.started_at.microsecond == 123456


def test_cpu_and_memory_metrics_use_docker_deltas() -> None:
    result = map_metrics(
        {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 300},
                "system_cpu_usage": 2000,
                "online_cpus": 2,
            },
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
            "memory_stats": {"usage": 1000, "limit": 4000, "stats": {"inactive_file": 200}},
        }
    )
    assert result.cpu_percent == 40.0
    assert result.memory_usage_bytes == 800
    assert map_metrics({}).cpu_percent is None


def test_log_redaction_handles_known_values_urls_and_private_keys() -> None:
    redactor = Redactor(("hunter22",))
    raw = (
        b"2026-01-01T00:00:00Z password=hunter22 postgres://user:pass@db/test\n"
        b"-----BEGIN PRIVATE KEY-----\nabcdef\n-----END PRIVATE KEY-----"
    )
    result = parse_logs(raw, redactor, 1024, 200)
    text = "\n".join(line.message for line in result.entries)
    assert "hunter22" not in text
    assert "user:pass" not in text
    assert "abcdef" not in text
    assert result.entries[0].timestamp is not None


def test_log_response_is_bounded_after_redaction() -> None:
    result = parse_logs(b"x" * 5000, Redactor(), 1024, 2)
    assert result.truncated
    assert result.entries == ()


def test_tail_boundary_does_not_expose_a_partial_known_environment_secret() -> None:
    secret = "private-sensitive-boundary-" + "A" * 104
    redactor = Redactor().with_environment([f"DB_PASSWORD={secret}"])
    raw = b"benign\n" + b"x" * 953 + secret.encode() + b"\nshutdown complete\n"
    result = parse_logs(raw, redactor, 64, 200)
    text = "\n".join(entry.message for entry in result.entries)
    assert "private-sensitive" not in text
    assert text == "shutdown complete"
    assert result.truncated
