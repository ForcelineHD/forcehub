import base64
import importlib
import os
import sys


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


def basic_auth(username, password):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_agents_dashboard_renders(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AGENT_TOKEN": "test-token", "FORCEHUB_AUTH_DISABLED": "1"})
    main._FH_AGENT_DATA_FILE = tmp_path / "agents.json"

    main._fh_save_agents({
        "TEST-PC": {
            "hostname": "TEST-PC",
            "last_checkin_unix": 1778219200,
            "client_host": "127.0.0.1",
            "payload": {
                "hostname": "TEST-PC",
                "os": "Windows 11 build 26200",
                "target": "windows",
                "arch": "x64",
                "ram_mb": 16065,
                "cpu_threads": 12,
                "disks": [
                    {"mount": "SYSTEM_DRIVE", "total_gb": 231, "free_gb": 116}
                ],
            },
        }
    })

    html = main._fh_agent_dashboard_html()

    assert "ForceHub Agents" in html
    assert "TEST-PC" in html
    assert "Windows 11 build 26200" in html
    assert "SYSTEM_DRIVE" in html


def test_agents_dashboard_requires_basic_auth_when_enabled(monkeypatch, tmp_path):
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

    unauthenticated = client.get("/agents")
    assert unauthenticated.status_code == 401

    authenticated = client.get("/agents", headers=basic_auth("admin", "test-passphrase"))
    assert authenticated.status_code == 200
    assert "ForceHub Agents" in authenticated.text
