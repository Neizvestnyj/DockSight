from docksight.adapters.outbound.docker.mapping import map_container, map_metrics, parse_logs
from docksight.application.redaction import Redactor


def test_inspect_discards_secrets_and_preserves_oom_evidence() -> None:
    """Verify inspect discards secrets and preserves oom evidence."""
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
    """Verify cpu and memory metrics use docker deltas."""
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
    """Verify log redaction handles known values urls and private keys."""
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
    """Verify log response is bounded after redaction."""
    result = parse_logs(b"x" * 5000, Redactor(), 1024, 2)
    assert result.truncated
    assert result.entries == ()


def test_truncated_line_does_not_expose_a_known_environment_secret_prefix() -> None:
    """Verify truncated line does not expose a known environment secret prefix."""
    secret = "private-sensitive-boundary-" + "A" * 104
    redactor = Redactor().with_environment([f"DB_PASSWORD={secret}"])
    raw = b"benign\n" + b"x" * 953 + secret.encode()
    result = parse_logs(raw[:1025], redactor, 1024, 200)
    text = "\n".join(entry.message for entry in result.entries)
    assert "private-sensitive" not in text
    assert text == "benign"
    assert result.truncated
