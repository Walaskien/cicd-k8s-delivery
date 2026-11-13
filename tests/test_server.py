import json
from pathlib import Path

import pytest
from prometheus_client import REGISTRY

import server


def make_client(monkeypatch, **env):
    for key in ("APP_FAULT", "APP_VERSION", "GREETING"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return server.create_app().test_client()


def requests_seen(route, status):
    labels = {"method": "GET", "route": route, "status": str(status)}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0


def test_health_ok(monkeypatch):
    resp = make_client(monkeypatch).get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_index_reports_version_and_greeting(monkeypatch):
    client = make_client(monkeypatch, APP_VERSION="abc123", GREETING="hi there")
    body = client.get("/").get_json()
    assert body["version"] == "abc123"
    assert body["message"] == "hi there"


def test_metrics_count_requests_by_route(monkeypatch):
    client = make_client(monkeypatch)
    before = requests_seen("/health", 200)
    client.get("/health")
    client.get("/health")
    assert requests_seen("/health", 200) == before + 2

    text = client.get("/metrics").get_data(as_text=True)
    assert "http_requests_total" in text
    assert "http_request_duration_seconds_bucket" in text


def test_unknown_paths_share_one_label(monkeypatch):
    client = make_client(monkeypatch)
    before = requests_seen("unmatched", 404)
    client.get("/nope-1")
    client.get("/nope-2")
    assert requests_seen("unmatched", 404) == before + 2


def test_unhealthy_fault_fails_health_only(monkeypatch):
    client = make_client(monkeypatch, APP_FAULT="unhealthy")
    assert client.get("/health").status_code == 503
    assert client.get("/").status_code == 200


def test_broken_endpoint_fault_keeps_health_green(monkeypatch):
    # this is the case readiness probes cannot catch, only the smoke test can
    client = make_client(monkeypatch, APP_FAULT="broken-endpoint")
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 500


def test_crash_on_start(monkeypatch):
    with pytest.raises(RuntimeError):
        make_client(monkeypatch, APP_FAULT="crash-on-start")


def test_unknown_fault_is_rejected(monkeypatch):
    with pytest.raises(ValueError):
        make_client(monkeypatch, APP_FAULT="unhealty")


def test_chart_schema_fault_list_matches_the_app():
    path = Path(__file__).resolve().parent.parent / "chart/greeter/values.schema.json"
    schema = json.loads(path.read_text())
    allowed = schema["properties"]["config"]["properties"]["fault"]["enum"]
    assert tuple(allowed) == ("",) + server.FAULTS
