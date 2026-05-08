import importlib
import json


def test_agent_checkin_and_list(monkeypatch, tmp_path):
    monkeypatch.setenv("FORCEHUB_AGENT_TOKEN", "test-token")

    main = importlib.import_module("app.main")

    # Redirect runtime DB to tmp path for test safety
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    payload = {
        "agent": "ForceHubAgent",
        "version": "0.1.0",
        "target": "windows",
        "hostname": "TEST-PC",
        "username": "Master",
        "os": "Windows 11 build 26200",
        "arch": "x64",
        "cpu_threads": 12,
        "ram_mb": 16065,
        "uptime_seconds": 120323,
        "disks": [
            {"mount": "C:\\", "total_gb": 231, "free_gb": 116}
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
    monkeypatch.setenv("FORCEHUB_AGENT_TOKEN", "test-token")

    main = importlib.import_module("app.main")
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    from fastapi.testclient import TestClient

    client = TestClient(main.app)

    r = client.post(
        "/api/agents/checkin",
        json={"hostname": "BAD-PC"},
        headers={"X-ForceHub-Agent-Token": "wrong-token"},
    )

    assert r.status_code == 401
