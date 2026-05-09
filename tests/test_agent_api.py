import importlib
import json
import os
import sys

import pytest


def import_main(monkeypatch, env=None):
    for key in list(os.environ):
        if key.startswith("FORCEHUB_"):
            monkeypatch.delenv(key, raising=False)

    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    return importlib.import_module("app.main")


def test_agent_checkin_and_list(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token"})

    # Redirect runtime DB to tmp path for test safety
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    payload = {
        "agent": "ForceHubAgent",
        "version": "0.1.0",
        "target": "windows",
        "hostname": "TEST-PC",
        "username": "test-user",
        "os": "Windows 11 build 26200",
        "arch": "x64",
        "cpu_threads": 12,
        "ram_mb": 16065,
        "uptime_seconds": 120323,
        "disks": [
            {"mount": "SYSTEM_DRIVE", "total_gb": 231, "free_gb": 116}
        ],
    }

    r = client.post(
        "/api/agents/checkin",
        json=payload,
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["hostname"] == "TEST-PC"

    r = client.get(
        "/api/agents",
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["agents"][0]["hostname"] == "TEST-PC"
    assert data["agents"][0]["payload"]["os"] == "Windows 11 build 26200"

    saved = json.loads((tmp_path / "agents.json").read_text())
    assert "TEST-PC" in saved


def test_agent_checkin_rejects_bad_token(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token"})
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    r = client.post(
        "/api/agents/checkin",
        json={"hostname": "BAD-PC"},
        headers={"X-ForceHub-Agent-Token": "wrong-token"},
    )

    assert r.status_code == 401


def test_agent_checkin_uses_constant_time_token_compare(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token"})
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    calls = []

    def fake_compare_digest(supplied, expected):
        calls.append((supplied, expected))
        return supplied == expected

    monkeypatch.setattr(main._fh_secrets, "compare_digest", fake_compare_digest)

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    r = client.post(
        "/api/agents/checkin",
        json={"hostname": "TEST-PC"},
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 200
    assert calls == [("test-token", "test-token")]


def test_agent_checkin_does_not_require_basic_auth_when_web_auth_enabled(monkeypatch, tmp_path):
    main = import_main(
        monkeypatch,
        {
            "FORCEHUB_AGENT_TOKEN": "test-token",
            "FORCEHUB_USERNAME": "admin",
            "FORCEHUB_PASSWORD": "test-passphrase",
        },
    )
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    r = client.post(
        "/api/agents/checkin",
        json={"hostname": "TEST-PC"},
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"hostname": "BAD/PC"},
        {"hostname": "TEST-PC", "os": "Windows 11\x00"},
    ],
)
def test_agent_checkin_rejects_invalid_payload(monkeypatch, tmp_path, payload):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token"})
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    r = client.post(
        "/api/agents/checkin",
        json=payload,
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 422
    assert not (tmp_path / "agents.json").exists()


def test_agent_checkin_rejects_oversized_payload_string(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token"})
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    r = client.post(
        "/api/agents/checkin",
        json={"hostname": "TEST-PC", "os": "x" * (main._FH_AGENT_MAX_STRING_CHARS + 1)},
        headers={"X-ForceHub-Agent-Token": "test-token"},
    )

    assert r.status_code == 422
