import importlib


def test_agents_dashboard_renders(monkeypatch, tmp_path):
    monkeypatch.setenv("FORCEHUB_AGENT_TOKEN", "test-token")

    main = importlib.import_module("app.main")
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
                    {"mount": "C:\\", "total_gb": 231, "free_gb": 116}
                ],
            },
        }
    })

    html = main._fh_agent_dashboard_html()

    assert "ForceHub Agents" in html
    assert "TEST-PC" in html
    assert "Windows 11 build 26200" in html
    assert "C:\\" in html
