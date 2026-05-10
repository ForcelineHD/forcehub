import importlib
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError


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


def create_project(tmp_path):
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (project_dir / ".env").write_text("SECRET=1\n", encoding="utf-8")
    return projects_dir, project_dir


def app_env(tmp_path, projects_dir):
    return {
        "FORCEHUB_AUTH_DISABLED": "1",
        "FORCEHUB_DATA_DIR": str(tmp_path / "data"),
        "FORCEHUB_DEFAULT_PROJECT": "proj",
        "FORCEHUB_PROJECTS_DIR": str(projects_dir),
    }


def test_path_traversal_rejected_by_file_api(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    (tmp_path / "secret.txt").write_text("secret\n", encoding="utf-8")
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))

    client = TestClient(main.app)
    response = client.get("/api/file-content", params={"project": "proj", "file": "../secret.txt"})

    assert response.status_code == 200
    assert response.json()["error"] is True
    assert "Invalid file path" in response.json()["text"]


@pytest.mark.parametrize("project", ["", ".", "..", "../proj", "proj/nested", "bad name", "bad\x1fname"])
def test_invalid_project_names_are_rejected(monkeypatch, project):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1"})

    with pytest.raises(ValueError):
        main.normalize_project_name(project)


@pytest.mark.parametrize(
    "file_path",
    ["", "../main.py", r"..\main.py", "/etc/passwd", "C:/Windows/win.ini", "//host/share.txt", "dir/../main.py", "bad\x1fname.py"],
)
def test_invalid_file_paths_are_rejected(monkeypatch, file_path):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1"})

    with pytest.raises(ValueError):
        main.normalize_file_path(file_path)


def test_file_whitelist_rejects_sensitive_dotenv(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))

    with pytest.raises(ValueError, match="whitelist"):
        main.safe_file_path("proj", ".env")


def test_project_index_returns_safe_metadata_without_file_contents(monkeypatch, tmp_path):
    projects_dir, project_dir = create_project(tmp_path)
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (project_dir / "web.js").write_text("const token = 'not returned';\n", encoding="utf-8")
    (project_dir / "tests").mkdir()
    (project_dir / "tests" / "test_app.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (project_dir / "logs").mkdir()
    (project_dir / "logs" / "app.log").write_text("runtime\n", encoding="utf-8")
    (project_dir / "build").mkdir()
    (project_dir / "build" / "bundle.js").write_text("built\n", encoding="utf-8")
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    monkeypatch.setattr(main, "git_tracked_project_files", lambda project, root: None)

    response = TestClient(main.app).get("/api/project-index", params={"project": "proj"})

    assert response.status_code == 200
    data = response.json()
    paths = {item["path"] for item in data["files"]}
    assert {"main.py", "docs/guide.md", "web.js", "tests/test_app.py"} <= paths
    assert ".env" not in paths
    assert "logs/app.log" not in paths
    assert "build/bundle.js" not in paths
    assert data["categories"]["python"] == 1
    assert data["categories"]["docs"] == 1
    assert data["categories"]["frontend"] == 1
    assert data["categories"]["test"] == 1
    assert all(set(item) == {"path", "extension", "type", "size", "category"} for item in data["files"])
    assert "print('ok')" not in response.text
    assert "not returned" not in response.text


def test_project_index_prefers_git_tracked_files_and_revalidates_paths(monkeypatch, tmp_path):
    projects_dir, project_dir = create_project(tmp_path)
    (project_dir / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
    (project_dir / "untracked.py").write_text("print('untracked')\n", encoding="utf-8")
    (project_dir / "docs").mkdir()
    (project_dir / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (project_dir / "build").mkdir()
    (project_dir / "build" / "bundle.js").write_text("built\n", encoding="utf-8")
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/git")

    def fake_check_output(command, cwd, stderr, timeout):
        assert command[1:] == ["ls-files", "-z", "--"]
        assert cwd == project_dir.resolve()
        return b"tracked.py\0docs/guide.md\0.env\0../outside.py\0build/bundle.js\0"

    monkeypatch.setattr(main.subprocess, "check_output", fake_check_output)

    response = TestClient(main.app).get("/api/project-index", params={"project": "proj"})

    assert response.status_code == 200
    data = response.json()
    assert [item["path"] for item in data["files"]] == ["docs/guide.md", "tracked.py"]
    assert data["total"] == 2
    assert data["truncated"] is False


def test_save_file_size_limit_in_model_and_api(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    oversized = "x" * (main.MAX_FILE_CHARS + 1)

    with pytest.raises(ValidationError):
        main.SaveFileRequest(project="proj", file="main.py", content=oversized)

    client = TestClient(main.app)
    response = client.post(
        "/api/save-file",
        json={"project": "proj", "file": "main.py", "content": oversized, "backup": False},
    )

    assert response.status_code == 422


def test_rate_limiting_blocks_after_configured_limit(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    env = app_env(tmp_path, projects_dir) | {
        "FORCEHUB_RATE_LIMIT_REQUESTS": "2",
        "FORCEHUB_RATE_LIMIT_WINDOW_SECONDS": "60",
    }
    main = import_main(monkeypatch, env)

    client = TestClient(main.app)

    assert client.get("/projects").status_code == 200
    assert client.get("/projects").status_code == 200
    limited = client.get("/projects")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_rate_limit_cleans_stale_buckets(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    main.RATE_LIMIT_REQUESTS = 2
    main.RATE_LIMIT_WINDOW_SECONDS = 60
    main.RATE_LIMIT_BUCKETS.clear()

    ticks = iter([100.0, 100.1, 100.2, 200.0])
    monkeypatch.setattr(main.time, "monotonic", lambda: next(ticks))
    request = SimpleNamespace(url=SimpleNamespace(path="/api/test"), client=SimpleNamespace(host="127.0.0.1"))

    assert main.rate_limit_result(request) == (False, 0)
    assert main.rate_limit_result(request) == (False, 0)
    assert main.rate_limit_result(request)[0] is True
    main.RATE_LIMIT_BUCKETS["stale:/x"].append(1.0)
    assert main.rate_limit_result(SimpleNamespace(url=SimpleNamespace(path="/api/next"), client=request.client)) == (False, 0)
    assert "stale:/x" not in main.RATE_LIMIT_BUCKETS


def test_ollama_url_empty_values_fallback_and_invalid_values_reject(monkeypatch):
    main = import_main(
        monkeypatch,
        {
            "FORCEHUB_AUTH_DISABLED": "1",
            "FORCEHUB_OLLAMA_URL": "",
            "FORCEHUB_OLLAMA_GENERATE_URL": "/api/generate",
        },
    )
    assert main.OLLAMA_BASE_URL == "http://127.0.0.1:11434"
    assert main.OLLAMA_GENERATE_URL == "http://127.0.0.1:11434/api/generate"

    with pytest.raises(ValueError, match="FORCEHUB_OLLAMA_URL"):
        import_main(monkeypatch, {"FORCEHUB_OLLAMA_URL": "ftp://127.0.0.1:11434"})

    with pytest.raises(ValueError, match="FORCEHUB_OLLAMA_GENERATE_URL"):
        import_main(monkeypatch, {"FORCEHUB_OLLAMA_GENERATE_URL": "api/generate"})


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        (None, 180),
        ("", 180),
        ("  ", 180),
        ("10", 10),
        ("600", 600),
        ("9", 180),
        ("601", 180),
        ("bad", 180),
    ],
)
def test_ollama_timeout_env_default_min_max_behavior(monkeypatch, env_value, expected):
    env = {"FORCEHUB_AUTH_DISABLED": "1"}
    if env_value is not None:
        env["FORCEHUB_OLLAMA_TIMEOUT_SECONDS"] = env_value

    main = import_main(monkeypatch, env)

    assert main.OLLAMA_TIMEOUT_SECONDS == expected


@pytest.mark.parametrize(
    ("chunk_chars", "max_chunks", "expected_chunk_chars", "expected_max_chunks"),
    [
        (None, None, 8000, 8),
        ("", "", 8000, 8),
        ("2000", "1", 2000, 1),
        ("20000", "20", 20000, 20),
        ("1999", "0", 8000, 8),
        ("20001", "21", 8000, 8),
        ("bad", "bad", 8000, 8),
    ],
)
def test_review_chunk_env_default_min_max_behavior(monkeypatch, chunk_chars, max_chunks, expected_chunk_chars, expected_max_chunks):
    env = {"FORCEHUB_AUTH_DISABLED": "1"}
    if chunk_chars is not None:
        env["FORCEHUB_REVIEW_CHUNK_CHARS"] = chunk_chars
    if max_chunks is not None:
        env["FORCEHUB_REVIEW_MAX_CHUNKS"] = max_chunks

    main = import_main(monkeypatch, env)

    assert main.REVIEW_CHUNK_CHARS == expected_chunk_chars
    assert main.REVIEW_MAX_CHUNKS == expected_max_chunks


def test_empty_env_path_values_fall_back(monkeypatch):
    main = import_main(
        monkeypatch,
        {
            "FORCEHUB_AUTH_DISABLED": "1",
            "FORCEHUB_DATA_DIR": "",
            "FORCEHUB_PROJECTS_DIR": "",
        },
    )

    assert main.PROJECTS_DIR == main.BASE_DIR.parent
    assert main.DATA_DIR == main.BASE_DIR / "data"

    monkeypatch.setenv("FORCEHUB_PROJECTS_DIR", "bad\x1fpath")
    with pytest.raises(ValueError):
        main.env_path("FORCEHUB_PROJECTS_DIR", main.BASE_DIR.parent)


def test_invalid_default_model_and_mode_fall_back(monkeypatch):
    main = import_main(
        monkeypatch,
        {
            "FORCEHUB_AUTH_DISABLED": "1",
            "FORCEHUB_DEFAULT_MODEL": "",
            "FORCEHUB_DEFAULT_MODE": "invalid",
        },
    )

    assert main.DEFAULT_MODEL == "qwen2.5-coder:3b"
    assert main.DEFAULT_MODE == "normal"
    assert main.ChatRequest(prompt="hello", project="proj").model == "qwen2.5-coder:3b"


def test_password_file_rejects_non_regular_and_insecure_posix_permissions(monkeypatch, tmp_path):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1"})
    secret = tmp_path / "password.txt"
    secret.write_text("secret\n", encoding="utf-8")

    assert main.read_secret_file(str(tmp_path)) == ""

    if os.name == "posix":
        secret.chmod(0o644)
        assert main.read_secret_file(str(secret)) == ""
        secret.chmod(0o600)

    assert main.read_secret_file(str(secret)) == "secret"


def test_run_command_api_rejects_non_allowlisted_command(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))

    with pytest.raises(ValidationError):
        main.RunCommandRequest(project="proj", command="whoami")

    response = TestClient(main.app).post("/api/run-command", json={"project": "proj", "command": "whoami"})

    assert response.status_code == 422


def test_chat_endpoint_uses_mocked_ollama_request(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {"response": "mocked response"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(main.requests, "post", fake_post)
    response = TestClient(main.app).post("/api/chat", json={"project": "proj", "prompt": "hello"})

    assert response.status_code == 200
    assert response.json()["text"] == "mocked response"
    assert calls[0][0] == main.OLLAMA_GENERATE_URL
    assert calls[0][1]["timeout"] == main.OLLAMA_TIMEOUT_SECONDS


def test_chat_stream_uses_configured_ollama_timeout(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    env = app_env(tmp_path, projects_dir) | {"FORCEHUB_OLLAMA_TIMEOUT_SECONDS": "11"}
    main = import_main(monkeypatch, env)
    calls = []

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter([b'{"response":"streamed"}'])

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeStreamResponse()

    monkeypatch.setattr(main.requests, "post", fake_post)
    response = TestClient(main.app).post("/api/chat-stream", json={"project": "proj", "prompt": "hello"})

    assert response.status_code == 200
    assert response.text == "streamed"
    assert calls[0][0] == main.OLLAMA_GENERATE_URL
    assert calls[0][1]["timeout"] == 11
    assert calls[0][1]["stream"] is True
    assert calls[0][1]["json"]["stream"] is True


def test_ollama_timeout_uses_labeled_fallback(monkeypatch):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1", "FORCEHUB_OLLAMA_TIMEOUT_SECONDS": "10"})
    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

        def json(self):
            return {"response": "fallback response"}

    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        calls.append(model)
        if model == "qwen2.5-coder:7b":
            raise main.requests.exceptions.Timeout()
        return FakeResponse()

    monkeypatch.setattr(main.requests, "post", fake_post)
    answer, used_model, elapsed = main.ask_with_fallback("review", "qwen2.5-coder:7b")

    assert calls == ["qwen2.5-coder:7b", main.OLLAMA_FALLBACK_MODEL]
    assert used_model == main.OLLAMA_FALLBACK_MODEL
    assert elapsed >= 0
    assert "Selected model qwen2.5-coder:7b timed out after 10 seconds" in answer
    assert f"Fallback model {main.OLLAMA_FALLBACK_MODEL} was used" in answer
    assert "fallback response" in answer


def test_ollama_timeout_returns_structured_error_when_fallback_times_out(monkeypatch):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1", "FORCEHUB_OLLAMA_TIMEOUT_SECONDS": "10"})
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"]["model"])
        raise main.requests.exceptions.Timeout()

    monkeypatch.setattr(main.requests, "post", fake_post)
    answer, used_model, elapsed = main.ask_with_fallback("review", "qwen2.5-coder:7b")

    assert calls == ["qwen2.5-coder:7b", main.OLLAMA_FALLBACK_MODEL]
    assert used_model == main.OLLAMA_FALLBACK_MODEL
    assert elapsed >= 0
    assert answer.startswith("[ForceHub timeout]")
    assert "Selected model: qwen2.5-coder:7b" in answer
    assert f"Fallback model: {main.OLLAMA_FALLBACK_MODEL}" in answer
    assert "both Ollama requests timed out" in answer


def test_large_file_truncation_warning_is_prompted_logged_and_returned(monkeypatch, tmp_path, caplog):
    projects_dir, project_dir = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    large_file = project_dir / "large.py"
    large_file.write_text("x" * (main.MAX_FILE_CHARS + 20), encoding="utf-8")
    prompts = []

    def fake_ask(prompt, model):
        prompts.append(prompt)
        return main.NO_CONFIRMED_ISSUE, "mock-model", 0.01

    monkeypatch.setattr(main, "ask_with_fallback", fake_ask)

    with caplog.at_level(logging.WARNING, logger=main.APP_NAME):
        response = TestClient(main.app).post(
            "/api/file-action",
            json={"project": "proj", "file": "large.py", "action": "review"},
        )

    warning_text = response.json()["text"].splitlines()[0]
    assert response.status_code == 200
    assert warning_text.startswith(main.TRUNCATION_WARNING_PREFIX)
    assert "large.py" in warning_text
    assert str(main.REVIEW_CHUNK_CHARS) in warning_text
    assert "chunked review" in warning_text
    assert len(prompts) == 2
    assert all(warning_text in prompt for prompt in prompts)
    assert response.json()["text"].endswith(main.NO_CONFIRMED_ISSUE)
    assert "large.py" in caplog.text
    assert "chunked review" in caplog.text


def test_large_file_review_splits_into_chunks(monkeypatch, tmp_path):
    projects_dir, project_dir = create_project(tmp_path)
    env = app_env(tmp_path, projects_dir) | {
        "FORCEHUB_REVIEW_CHUNK_CHARS": "2000",
        "FORCEHUB_REVIEW_MAX_CHUNKS": "8",
    }
    main = import_main(monkeypatch, env)
    large_file = project_dir / "large.py"
    large_file.write_text("a" * 4500, encoding="utf-8")
    prompts = []

    def fake_ask(prompt, model):
        prompts.append(prompt)
        return f"Location: large.py:{len(prompts)}\nEvidence: confirmed issue in chunk {len(prompts)}.", "mock-model", 0.01

    monkeypatch.setattr(main, "ask_with_fallback", fake_ask)
    response = TestClient(main.app).post(
        "/api/file-action",
        json={"project": "proj", "file": "large.py", "action": "bugs"},
    )
    text = response.json()["text"]

    assert response.status_code == 200
    assert len(prompts) == 3
    assert "Chunk: 1 of 3" in prompts[0]
    assert "Character range: 0-2000" in prompts[0]
    assert "Chunk: 2 of 3" in prompts[1]
    assert "Character range: 2000-4000" in prompts[1]
    assert "Chunk: 3 of 3" in prompts[2]
    assert "Character range: 4000-4500" in prompts[2]
    assert text.count("confirmed issue in chunk") == 3
    assert "Chunk 1 (0-2000)" in text
    assert "Chunk 3 (4000-4500)" in text


def test_large_file_review_respects_max_chunk_limit(monkeypatch, tmp_path):
    projects_dir, project_dir = create_project(tmp_path)
    env = app_env(tmp_path, projects_dir) | {
        "FORCEHUB_REVIEW_CHUNK_CHARS": "2000",
        "FORCEHUB_REVIEW_MAX_CHUNKS": "2",
    }
    main = import_main(monkeypatch, env)
    large_file = project_dir / "large.py"
    large_file.write_text("a" * 5000, encoding="utf-8")
    prompts = []

    def fake_ask(prompt, model):
        prompts.append(prompt)
        return main.NO_CONFIRMED_ISSUE, "mock-model", 0.01

    monkeypatch.setattr(main, "ask_with_fallback", fake_ask)
    response = TestClient(main.app).post(
        "/api/file-action",
        json={"project": "proj", "file": "large.py", "action": "review"},
    )
    text = response.json()["text"]

    assert response.status_code == 200
    assert len(prompts) == 2
    assert "Chunk: 1 of 2" in prompts[0]
    assert "Chunk: 2 of 2" in prompts[1]
    assert "Only the first 2 chunk(s) were reviewed" in text
    assert text.endswith(main.NO_CONFIRMED_ISSUE)


def test_chunked_review_suppresses_generic_no_issue_output(monkeypatch, tmp_path):
    projects_dir, project_dir = create_project(tmp_path)
    env = app_env(tmp_path, projects_dir) | {"FORCEHUB_REVIEW_CHUNK_CHARS": "2000"}
    main = import_main(monkeypatch, env)
    large_file = project_dir / "large.py"
    large_file.write_text("a" * 4500, encoding="utf-8")

    def fake_ask(prompt, model):
        return "Security Concerns\n- Review validation.\n\nRecommendations\n- Improve error handling.", "mock-model", 0.01

    monkeypatch.setattr(main, "ask_with_fallback", fake_ask)
    response = TestClient(main.app).post(
        "/api/file-action",
        json={"project": "proj", "file": "large.py", "action": "bugs"},
    )
    text = response.json()["text"]

    assert response.status_code == 200
    assert "Security Concerns" not in text
    assert "Recommendations" not in text
    assert text.endswith(main.NO_CONFIRMED_ISSUE)


def test_bugs_and_review_prompts_are_confirmed_only(monkeypatch, tmp_path):
    projects_dir, _ = create_project(tmp_path)
    main = import_main(monkeypatch, app_env(tmp_path, projects_dir))
    prompts = []

    def fake_ask(prompt, model):
        prompts.append(prompt)
        return main.NO_CONFIRMED_ISSUE, "mock-model", 0.01

    monkeypatch.setattr(main, "ask_with_fallback", fake_ask)
    client = TestClient(main.app)

    file_response = client.post(
        "/api/file-action",
        json={"project": "proj", "file": "main.py", "action": "review"},
    )
    project_response = client.post(
        "/api/project-action",
        json={"project": "proj", "action": "bugs"},
    )

    assert file_response.status_code == 200
    assert project_response.status_code == 200
    assert len(prompts) == 2
    for prompt in prompts:
        assert "Only confirmed issues." in prompt
        assert "No generic best-practice lists." in prompt
        assert "No style, documentation, formatting, or comment suggestions." in prompt
        assert "Must cite exact function/location/evidence" in prompt
        assert f"If no confirmed issue exists, output exactly:\n{main.NO_CONFIRMED_ISSUE}" in prompt


def test_generic_audit_sections_without_evidence_are_suppressed(monkeypatch):
    main = import_main(monkeypatch, {"FORCEHUB_AUTH_DISABLED": "1"})

    generic = """Security Concerns
- Review authentication.

Recommendations
- Improve validation.
"""
    evidenced = """Security Concerns
Location: app/main.py:10
Evidence: the handler raises before validating input.
"""

    assert main.clean_confirmed_audit_answer(generic) == main.NO_CONFIRMED_ISSUE
    assert main.clean_confirmed_audit_answer(evidenced) == evidenced.strip()
