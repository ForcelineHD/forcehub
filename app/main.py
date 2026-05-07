import base64
import difflib
import importlib.util
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

APP_NAME = "forcehub"
APP_VERSION = "0.8.0"
logger = logging.getLogger(APP_NAME)

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    logger.warning("Invalid boolean value for %s; using default %s", name, default)
    return default


def env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("Invalid integer value for %s; using default %s", name, default)
        return default
    if minimum is not None and value < minimum:
        logger.warning("%s below minimum %s; using default %s", name, minimum, default)
        return default
    if maximum is not None and value > maximum:
        logger.warning("%s above maximum %s; using default %s", name, maximum, default)
        return default
    return value


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_path(name: str, default: Path | str) -> Path:
    raw = env_str(name, str(default))
    return Path(raw).expanduser().resolve()


def env_config_value(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip()
    if CONTROL_CHAR_PATTERN.search(value):
        raise ValueError(f"{name} contains control characters")
    return value


def validate_absolute_http_url(value: str, name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL")
    return value.rstrip("/")


def validate_ollama_endpoint(value: str, name: str, base_url: str) -> str:
    if CONTROL_CHAR_PATTERN.search(value):
        raise ValueError(f"{name} contains control characters")
    if value.startswith("/"):
        path = PurePosixPath(value)
        if value.startswith("//") or "\\" in value or any(part in {".", ".."} for part in path.parts):
            raise ValueError(f"{name} must be a safe relative path")
        return f"{base_url}{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute http(s) URL or a relative path starting with /")
    return value


PROJECTS_DIR = env_path("FORCEHUB_PROJECTS_DIR", BASE_DIR.parent)
DEFAULT_PROJECT = env_str("FORCEHUB_DEFAULT_PROJECT")
DATA_DIR = env_path("FORCEHUB_DATA_DIR", BASE_DIR / "data")
CHAT_FILE = DATA_DIR / "chats.json"
PROJECT_CACHE_FILE = DATA_DIR / "project_cache.json"
PROJECT_SETTINGS_FILE = DATA_DIR / "project_settings.json"

OLLAMA_BASE_URL = validate_absolute_http_url(
    env_config_value("FORCEHUB_OLLAMA_URL", "http://127.0.0.1:11434"),
    "FORCEHUB_OLLAMA_URL",
)
OLLAMA_GENERATE_URL = validate_ollama_endpoint(
    env_config_value("FORCEHUB_OLLAMA_GENERATE_URL", f"{OLLAMA_BASE_URL}/api/generate"),
    "FORCEHUB_OLLAMA_GENERATE_URL",
    OLLAMA_BASE_URL,
)
OLLAMA_TAGS_URL = validate_ollama_endpoint(
    env_config_value("FORCEHUB_OLLAMA_TAGS_URL", f"{OLLAMA_BASE_URL}/api/tags"),
    "FORCEHUB_OLLAMA_TAGS_URL",
    OLLAMA_BASE_URL,
)
VALID_MODES = {"normal", "code", "cpp", "short", "explain"}
DEFAULT_MODEL = env_str("FORCEHUB_DEFAULT_MODEL", "qwen2.5-coder:1.5b")
DEFAULT_MODE = env_str("FORCEHUB_DEFAULT_MODE", "normal")
if DEFAULT_MODE not in VALID_MODES:
    logger.warning("Invalid FORCEHUB_DEFAULT_MODE %s; using normal", DEFAULT_MODE)
    DEFAULT_MODE = "normal"
RATE_LIMIT_REQUESTS = env_int("FORCEHUB_RATE_LIMIT_REQUESTS", 120, minimum=1)
RATE_LIMIT_WINDOW_SECONDS = env_int("FORCEHUB_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1)
RATE_LIMIT_DISABLED = env_bool("FORCEHUB_RATE_LIMIT_DISABLED")

MAX_FILE_CHARS = 8000
MAX_PROJECT_FILES = 15
MAX_SEARCH_RESULTS = 80
CPP_SOURCE_PATTERNS = ("*.cpp", "*.cc", "*.cxx")
CPP_HEADER_PATTERNS = ("*.h", "*.hh", "*.hpp", "*.hxx")
SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:basic|bearer)\s+)[^\s,;]+"
    r"|((?:password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*)[^\s,;]+"
)

app = FastAPI(title="ForceHub", description="Local AI dev dashboard.", version=APP_VERSION)

CHAT_HISTORY: list[dict[str, str]] = []
LAST_DEBUG: dict[str, str | int | float] = {}
RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    message: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password: str
    disabled: bool


class ForceHubModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("project", check_fields=False)
    @classmethod
    def validate_project_field(cls, value: str) -> str:
        return normalize_project_name(value)

    @field_validator("file", check_fields=False)
    @classmethod
    def validate_file_field(cls, value: str) -> str:
        return str(normalize_file_path(value))

    @field_validator("model", "preferred_model", check_fields=False)
    @classmethod
    def validate_model_field(cls, value: str) -> str:
        if not value or CONTROL_CHAR_PATTERN.search(value) or len(value) > 128:
            raise ValueError("Invalid model name")
        return value


def redact_sensitive(value: object) -> str:
    return SENSITIVE_LOG_PATTERN.sub(lambda match: f"{match.group(1) or match.group(2)}[REDACTED]", str(value))


class SensitiveLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: redact_sensitive(value) for key, value in record.args.items()}
        elif record.args:
            record.args = tuple(redact_sensitive(arg) for arg in record.args)
        return True


class StatusResponse(BaseModel):
    status: str
    app: str
    version: str


class ChatRequest(ForceHubModel):
    prompt: str = Field(min_length=1, max_length=12000)
    model: str = DEFAULT_MODEL
    mode: Literal["normal", "code", "cpp", "short", "explain"] = DEFAULT_MODE
    project: str = DEFAULT_PROJECT
    project_mode: bool = False


class FileReviewRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    file: str
    model: str = DEFAULT_MODEL
    action: Literal["review", "bugs", "explain", "patch"] = "review"


class ProjectActionRequest(ForceHubModel):
    action: Literal["analyze", "bugs", "readme", "commit"]
    model: str = DEFAULT_MODEL
    project: str = DEFAULT_PROJECT


class SearchRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    query: str = Field(min_length=1, max_length=200)


class SaveReadmeRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    content: str = Field(max_length=MAX_FILE_CHARS)


class SaveFileRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    file: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=MAX_FILE_CHARS)
    backup: bool = True


class DiffContentRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    file: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=MAX_FILE_CHARS)


class RunCommandRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    command: Literal["git_status", "pytest", "ruff", "ruff_fix", "python_compile", "cpp_compile", "cmake_configure", "cmake_build", "cppcheck", "clang_tidy", "bandit", "npm_test", "npm_build", "npm_audit", "health"]



class ExplainOutputRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    output: str = Field(min_length=1, max_length=12000)
    model: str = DEFAULT_MODEL


class CreateCppProjectRequest(ForceHubModel):
    project: str



class ProjectSettingsRequest(ForceHubModel):
    project: str = DEFAULT_PROJECT
    preferred_model: str = DEFAULT_MODEL
    preferred_mode: Literal["normal", "code", "cpp", "short", "explain"] = DEFAULT_MODE
    project_context: bool = False


def ensure_dir(path: Path, *, private: bool = True) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
    except PermissionError as exc:
        logger.exception("Insufficient permissions to create directory %s", path)
        raise RuntimeError(f"Insufficient permissions to create directory: {path}") from exc
    except OSError as exc:
        logger.exception("Unable to create directory %s", path)
        raise RuntimeError(f"Unable to create directory: {path}") from exc
    if not path.is_dir():
        raise RuntimeError(f"Expected directory path is not a directory: {path}")


def configure_logging() -> None:
    level_name = env_str("FORCEHUB_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    if not any(isinstance(existing_filter, SensitiveLogFilter) for existing_filter in logger.filters):
        logger.addFilter(SensitiveLogFilter())

    log_file = env_str("FORCEHUB_LOG_FILE")
    if not log_file:
        return

    log_path = Path(log_file).expanduser().resolve()
    if any(getattr(handler, "_forcehub_log_file", None) == str(log_path) for handler in logger.handlers):
        return

    ensure_dir(log_path.parent)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=env_int("FORCEHUB_LOG_MAX_BYTES", 1_048_576, minimum=1),
        backupCount=env_int("FORCEHUB_LOG_BACKUP_COUNT", 3, minimum=0),
        encoding="utf-8",
    )
    handler._forcehub_log_file = str(log_path)
    handler.setLevel(level)
    handler.addFilter(SensitiveLogFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)


configure_logging()


def is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def normalize_project_name(project: str) -> str:
    normalized = project.strip()
    if not normalized:
        raise ValueError("Project name is required")

    if CONTROL_CHAR_PATTERN.search(normalized):
        raise ValueError("Invalid project name: control characters are not allowed")
    if "/" in normalized or "\\" in normalized:
        raise ValueError("Invalid project name: use a direct project directory name")
    if not PROJECT_NAME_PATTERN.fullmatch(normalized) or normalized in {".", ".."}:
        raise ValueError("Invalid project name: use letters, numbers, dots, dashes, or underscores")

    return normalized


def normalize_file_path(file: str) -> Path:
    normalized = file.strip()
    if not normalized:
        raise ValueError("File path is required")
    if CONTROL_CHAR_PATTERN.search(normalized):
        raise ValueError("Invalid file path: control characters are not allowed")

    normalized = normalized.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Invalid file path: use a project-relative file path")
    if any(":" in part for part in path.parts):
        raise ValueError("Invalid file path: drive-qualified paths are not allowed")
    if any(CONTROL_CHAR_PATTERN.search(part) for part in path.parts):
        raise ValueError("Invalid file path: control characters are not allowed")

    return Path(*path.parts)


def list_project_names() -> list[str]:
    ensure_dir(PROJECTS_DIR, private=False)
    projects = []
    try:
        candidates = list(PROJECTS_DIR.iterdir())
    except OSError as exc:
        logger.exception("Unable to list configured projects directory %s", PROJECTS_DIR)
        raise RuntimeError(f"Unable to list projects directory: {PROJECTS_DIR}") from exc

    for path in candidates:
        if not path.is_dir():
            continue
        try:
            normalized = normalize_project_name(path.name)
            resolved = path.resolve()
        except (OSError, ValueError) as exc:
            logger.warning("Skipping invalid project directory %s: %s", path, exc)
            continue
        if is_relative_to(resolved, PROJECTS_DIR) and os.access(resolved, os.R_OK | os.X_OK):
            projects.append(normalized)
        else:
            logger.warning("Skipping inaccessible or out-of-root project directory %s", path)
    return sorted(projects)


def find_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Invalid project root: {root}")

    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.rglob(pattern):
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
            except OSError as exc:
                logger.warning("Skipping inaccessible file during discovery %s: %s", path, exc)
                continue
            if not is_relative_to(resolved, root):
                logger.warning("Skipping file outside project root during discovery: %s", path)
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(resolved)
    return sorted(found, key=lambda path: str(path.relative_to(root)))


def resolve_executable(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def python_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def get_git_command() -> str | None:
    configured = os.getenv("FORCEHUB_GIT_BIN")
    if configured:
        return configured
    return resolve_executable("git")


def read_secret_file(path: str) -> str:
    secret_path = Path(path).expanduser().resolve()
    try:
        return secret_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.error("Unable to read configured secret file %s: %s", secret_path, exc)
        return ""


def get_auth_config() -> AuthConfig:
    password_file = env_str("FORCEHUB_PASSWORD_FILE")
    password = read_secret_file(password_file) if password_file else os.getenv("FORCEHUB_PASSWORD", "")
    return AuthConfig(
        username=env_str("FORCEHUB_USERNAME"),
        password=password,
        disabled=env_bool("FORCEHUB_AUTH_DISABLED"),
    )



def is_auth_disabled() -> bool:
    return get_auth_config().disabled


def check_basic_auth(request: Request) -> AuthResult:
    auth_config = get_auth_config()
    if auth_config.disabled:
        return AuthResult(True)

    if not auth_config.username or not auth_config.password:
        message = (
            "ForceHub authentication is not configured. Set FORCEHUB_USERNAME and "
            "FORCEHUB_PASSWORD or FORCEHUB_PASSWORD_FILE, or set FORCEHUB_AUTH_DISABLED=1 for local-only use."
        )
        logger.error(message)
        return AuthResult(False, message)

    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "basic" or not token.strip():
        return AuthResult(False, "ForceHub authentication required")

    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
        username, separator, password = decoded.partition(":")
        if not separator:
            return AuthResult(False, "Invalid Basic auth payload")
        if not username:
            return AuthResult(False, "Basic auth username is required")
        if not password:
            return AuthResult(False, "Basic auth password is required")

        username_matches = secrets.compare_digest(username, auth_config.username)
        password_matches = secrets.compare_digest(password, auth_config.password)
        if username_matches and password_matches:
            return AuthResult(True)

        return AuthResult(False, "Invalid ForceHub username or password")
    except Exception as exc:
        logger.warning("Rejected malformed Basic auth header: %s", exc)
        return AuthResult(False, "Invalid Basic auth header")


def rate_limit_result(request: Request) -> tuple[bool, int]:
    if RATE_LIMIT_DISABLED or request.url.path.startswith("/status"):
        return False, 0

    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{request.url.path}"
    bucket = RATE_LIMIT_BUCKETS[key]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        return True, retry_after
    bucket.append(now)
    return False, 0


@app.middleware("http")
async def forcehub_basic_auth(request: Request, call_next):
    if request.url.path.startswith("/status"):
        return await call_next(request)

    auth_result = check_basic_auth(request)
    if not auth_result:
        return PlainTextResponse(
            auth_result.message or "ForceHub authentication required",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="ForceHub"'},
        )

    return await call_next(request)


@app.middleware("http")
async def forcehub_rate_limit(request: Request, call_next):
    limited, retry_after = rate_limit_result(request)
    if limited:
        return PlainTextResponse(
            "ForceHub rate limit exceeded",
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


def load_project_settings() -> dict:
    ensure_dir(DATA_DIR)
    if not PROJECT_SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(PROJECT_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        logger.error("Project settings file must contain a JSON object: %s", PROJECT_SETTINGS_FILE)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in project settings file %s: %s", PROJECT_SETTINGS_FILE, exc)
        return {}
    except OSError:
        logger.exception("Failed to read project settings file %s", PROJECT_SETTINGS_FILE)
        return {}


def save_project_settings(data: dict) -> None:
    try:
        ensure_dir(DATA_DIR)
        PROJECT_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.exception("Failed to save project settings file %s", PROJECT_SETTINGS_FILE)
        raise RuntimeError(f"Unable to save project settings: {PROJECT_SETTINGS_FILE}") from exc


def api_error(action: str, exc: Exception) -> dict[str, bool | str]:
    logger.exception("%s failed", action)
    return {"error": True, "text": f"{action} failed: {exc}"}


def safe_project_path(project: str) -> Path:
    ensure_dir(PROJECTS_DIR)
    normalized_project = normalize_project_name(project)
    allowed_projects = set(list_project_names())
    if normalized_project not in allowed_projects:
        raise ValueError(f"Project is not allowed or does not exist: {normalized_project}")

    target = (PROJECTS_DIR / normalized_project).resolve()
    if not is_relative_to(target, PROJECTS_DIR):
        raise ValueError("Invalid project path: resolved outside the allowed projects directory")
    if not target.exists() or not target.is_dir():
        raise ValueError(f"Project not found: {normalized_project}")
    return target


def safe_file_path(project: str, file: str) -> Path:
    root = safe_project_path(project)
    relative_file = normalize_file_path(file)
    target = (root / relative_file).resolve()
    if not is_relative_to(target, root.resolve()):
        raise ValueError("Invalid file path: resolved outside the project directory")
    if not target.exists() or not target.is_file():
        raise ValueError(f"File not found: {file}")
    if not should_include_file(target):
        raise ValueError(f"File is not in the allowed ForceHub file whitelist: {file}")
    return target


def should_include_file(path: Path) -> bool:
    blocked_dirs = {
        ".git", ".venv", "venv", "__pycache__", "node_modules",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "data",
    }
    if any(part in blocked_dirs for part in path.parts):
        return False
    allowed_ext = {
        ".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml",
        ".html", ".css", ".js", ".ts", ".sh",
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    }
    return path.suffix.lower() in allowed_ext or path.name in {"Dockerfile", ".gitignore", "CMakeLists.txt", "Makefile"}


def iter_project_files(root: Path):
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Invalid project root: {root}")

    seen: set[Path] = set()
    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            resolved = path.resolve()
        except OSError as exc:
            logger.warning("Skipping inaccessible project file %s: %s", path, exc)
            continue
        if not is_relative_to(resolved, root):
            logger.warning("Skipping project file outside root: %s", path)
            continue
        if resolved in seen or not should_include_file(path) or not should_include_file(resolved):
            continue
        seen.add(resolved)
        yield resolved


def read_text_limited(path: Path, max_chars: int = MAX_FILE_CHARS) -> tuple[str, bool]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(max_chars + 1)

    if len(text) > max_chars:
        logger.error("File exceeds maximum read length of %s chars and was truncated: %s", max_chars, path)
        return text[:max_chars], True

    return text, False


def read_file_safe(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        text, truncated = read_text_limited(path)
        suffix = f" (truncated after {MAX_FILE_CHARS} chars)" if truncated else ""
        return f"\n\n--- FILE: {rel}{suffix} ---\n{text}"
    except Exception as e:
        logger.exception("Failed to read file %s", path)
        return f"\n\n--- FILE ERROR: {path.name}: {e} ---"


def build_project_context(project: str) -> str:
    root = safe_project_path(project)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Project directory is invalid: {project}")
    chunks = [f"PROJECT: {project}\nROOT: {root}\n"]
    try:
        files = list(iter_project_files(root))
    except (OSError, ValueError) as exc:
        logger.exception("Failed to scan project context for %s", root)
        raise RuntimeError(f"Unable to scan project directory: {project}") from exc
    files = sorted(files, key=lambda p: str(p.relative_to(root)))[:MAX_PROJECT_FILES]
    for file in files:
        chunks.append(read_file_safe(file, root))
    return "\n".join(chunks)


def load_cache() -> dict:
    ensure_dir(DATA_DIR)
    if not PROJECT_CACHE_FILE.exists():
        return {}
    try:
        data = json.loads(PROJECT_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        logger.error("Project cache file must contain a JSON object: %s", PROJECT_CACHE_FILE)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in project cache file %s: %s", PROJECT_CACHE_FILE, exc)
        return {}
    except OSError:
        logger.exception("Failed to read project cache file %s", PROJECT_CACHE_FILE)
        return {}


def save_cache(data: dict) -> None:
    try:
        ensure_dir(DATA_DIR)
        PROJECT_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.exception("Failed to save project cache file %s", PROJECT_CACHE_FILE)
        raise RuntimeError(f"Unable to save project cache: {PROJECT_CACHE_FILE}") from exc


def choose_model(model: str, prompt: str) -> str:
    if model != "auto":
        return model
    return "qwen2.5-coder:1.5b" if len(prompt) < 1200 else "qwen2.5-coder:7b"


def build_prompt(user_prompt: str, mode: str, project: str, project_mode: bool) -> str:
    system = {
        "normal": "You are ForceHub AI. Answer clearly and practically.",
        "code": "You are ForceHub AI coding assistant. Give code-first, practical answers.",
        "cpp": "You are ForceHub AI C++ assistant. Focus on modern C++20, build systems, compile errors, performance, memory safety, RAII, undefined behavior, headers, CMake, and practical fixes.",
        "short": "Answer briefly and directly. No padding.",
        "explain": "Explain step by step, but avoid unnecessary basics.",
    }.get(mode, "You are ForceHub AI.")

    history = "".join(f"{i['role']}: {i['content']}\n" for i in CHAT_HISTORY[-8:])
    project_context = build_project_context(project) if project_mode else ""
    cached_summary = load_cache().get(project, {}).get("summary", "")

    return f"""{system}

Cached project summary:
{cached_summary}

Conversation:
{history}

Project context:
{project_context}

User request:
{user_prompt}

Assistant:"""


def ask_ollama(prompt: str, model: str) -> tuple[str, str, float]:
    selected_model = choose_model(model, prompt)
    start = time.time()
    r = requests.post(
        OLLAMA_GENERATE_URL,
        json={
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096},
        },
        timeout=180,
    )
    elapsed = round(time.time() - start, 2)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text}")
    return r.json().get("response", "").strip(), selected_model, elapsed


def ask_with_fallback(prompt: str, model: str) -> tuple[str, str, float]:
    try:
        return ask_ollama(prompt, model)
    except Exception as exc:
        logger.warning("Ollama request failed for model %s, retrying fallback model: %s", model, exc)
        return ask_ollama(prompt, "qwen2.5-coder:1.5b")


def save_chat(role: str, content: str) -> None:
    ensure_dir(DATA_DIR)
    item = {"time": datetime.now().isoformat(timespec="seconds"), "role": role, "content": content}
    data = []
    if CHAT_FILE.exists():
        try:
            data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load chat history from %s, starting fresh: %s", CHAT_FILE, exc)
            data = []
    data.append(item)
    try:
        CHAT_FILE.write_text(json.dumps(data[-100:], indent=2), encoding="utf-8")
    except OSError as exc:
        logger.exception("Failed to save chat history to %s", CHAT_FILE)
        raise RuntimeError(f"Unable to save chat history: {CHAT_FILE}") from exc


def run_cmd(project: str, cmd: list[str], timeout: int = 60) -> str:
    root = safe_project_path(project)
    try:
        command = [str(part) for part in cmd]
        return subprocess.check_output(command, cwd=root, stderr=subprocess.STDOUT, text=True, timeout=timeout).strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()
    except Exception as e:
        logger.exception("Command failed in project %s: %s", project, cmd)
        return f"Command failed: {e}"


def run_git(project: str, args: list[str]) -> str:
    git_bin = get_git_command()
    if not git_bin:
        return "git is not installed or not on PATH."
    return run_cmd(project, [git_bin, *args], timeout=20)



def command_exists(project: str, command: str) -> bool:
    del project
    return resolve_executable(command) is not None


def detect_project_type(project: str) -> dict:
    root = safe_project_path(project)

    files = {p.name for p in root.iterdir() if p.is_file()}
    has_py = any(root.rglob("*.py"))
    has_cpp = bool(find_files(root, CPP_SOURCE_PATTERNS + CPP_HEADER_PATTERNS))
    has_node = "package.json" in files

    detected = []
    if has_py or "pyproject.toml" in files or "requirements.txt" in files:
        detected.append("python")
    if has_cpp or "CMakeLists.txt" in files or "Makefile" in files:
        detected.append("cpp")
    if has_node:
        detected.append("node")

    return {
        "types": detected or ["unknown"],
        "python": {
            "pyproject": "pyproject.toml" in files,
            "requirements": "requirements.txt" in files,
            "pytest": python_module_available("pytest"),
            "ruff": python_module_available("ruff"),
            "bandit": python_module_available("bandit"),
        },
        "cpp": {
            "cmake": "CMakeLists.txt" in files,
            "makefile": "Makefile" in files,
            "gpp": command_exists(project, "g++"),
            "clangpp": command_exists(project, "clang++"),
            "cppcheck": command_exists(project, "cppcheck"),
            "clang_tidy": command_exists(project, "clang-tidy"),
        },
        "node": {
            "package_json": has_node,
            "npm": command_exists(project, "npm"),
        },
    }


def project_health(project: str) -> str:
    root = safe_project_path(project)

    checks = []
    checks.append(("Git repo", (root / ".git").exists()))
    checks.append(("README exists", (root / "README.md").exists()))
    checks.append(("License exists", any((root / name).exists() for name in ["LICENSE", "LICENSE.md", "COPYING"])))
    checks.append(("Python app exists", any(root.rglob("*.py"))))
    checks.append(("C++ files exist", any(root.rglob("*.cpp")) or any(root.rglob("*.cc")) or any(root.rglob("*.cxx"))))
    checks.append(("CMake exists", (root / "CMakeLists.txt").exists()))
    checks.append(("package.json exists", (root / "package.json").exists()))

    git_status = run_git(project, ["status", "--short"]) if (root / ".git").exists() else "not a git repo"
    checks.append(("Git clean", git_status.strip() == ""))

    score = sum(1 for _, ok in checks if ok)
    total = len(checks)

    lines = [f"Project health: {score}/{total}", ""]
    for name, ok in checks:
        lines.append(f"{'OK' if ok else 'MISS'} - {name}")

    lines.append("")
    lines.append("Git status:")
    lines.append(git_status or "clean")

    detected = detect_project_type(project)
    lines.append("")
    lines.append("Detected:")
    lines.append(json.dumps(detected, indent=2))

    return "\n".join(lines)


@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<title>ForceHub AI Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#0f1117;--panel:#151924;--panel2:#111521;--border:#252b3a;--text:#e6e6e6;--muted:#8d96aa;--blue:#4f7cff;--user:#1f3a5f;--ai:#1d2230}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text)}
.layout{display:grid;grid-template-columns:370px 1fr;height:100vh}
.sidebar{background:var(--panel);border-right:1px solid var(--border);padding:18px;overflow:auto}
.sidebar h2{margin:0 0 8px;color:#8ab4ff}.small{color:var(--muted);font-size:13px}
.sidebar a{color:#b7c7ff;display:block;margin:10px 0;text-decoration:none}
.control{margin-top:14px}label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}
select,input{width:100%;background:#0f1117;color:var(--text);border:1px solid #30384d;border-radius:8px;padding:8px}
.main{display:flex;flex-direction:column;height:100vh}.header{padding:14px 22px;border-bottom:1px solid var(--border);background:var(--panel2);display:flex;justify-content:space-between;align-items:center}
.header h2{margin:0}.chat{flex:1;overflow-y:auto;padding:22px}
.msg{max-width:1100px;padding:14px 16px;margin-bottom:14px;border-radius:12px;white-space:pre-wrap;line-height:1.48;font-size:14px}
.user{background:var(--user);margin-left:auto}.ai{background:var(--ai);border:1px solid #2b3245}.error{background:#3a1d24;border:1px solid #6d2b39}
.inputbar{display:flex;gap:10px;padding:16px;border-top:1px solid var(--border);background:var(--panel2)}
textarea{flex:1;resize:none;height:60px;border-radius:10px;border:1px solid #30384d;background:#0f1117;color:#eee;padding:12px;font-size:15px}
button{border:0;border-radius:10px;background:var(--blue);color:white;font-weight:bold;cursor:pointer;padding:10px 14px}
button:disabled{background:#3a3f50;cursor:wait}.secondary{background:#2a3040;width:100%;margin-top:8px}.action{background:#26385f;width:100%;margin-top:8px;text-align:left}
.badge{font-size:12px;color:#b7c7ff}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.editor{width:100%;height:280px;background:#0b0d12;color:#e6e6e6;border:1px solid #30384d;border-radius:8px;padding:10px;font-family:Consolas,monospace;font-size:13px}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
<h2>ForceHub</h2>
<div class="small">Local AI dev dashboard</div>
<hr style="border-color:#252b3a">

<a href="/status">Status API</a>
<a href="/projects">Projects API</a>
<a href="/docs">API Docs</a>

<div class="control"><label>Project</label><select id="project"></select></div>
<div class="control"><label>Model</label><select id="model"></select></div>
<div class="control"><label>Mode</label><select id="mode">
<option value="normal">Normal</option><option value="code">Code Assistant</option><option value="cpp">C++ Assistant</option><option value="short">Short Answers</option><option value="explain">Explain Step-by-Step</option>
</select></div>

<div class="control"><label><input id="projectMode" type="checkbox"> Use project context</label></div>

<div class="control">
<label>File</label><select id="file"></select>
<div class="grid2">
<button class="action" onclick="viewFile()">View file</button>
<button class="action" onclick="previewDiff()">Preview diff</button>
<button class="action" onclick="saveFile()">Save file</button>
<button class="action" onclick="fileAction('patch')">Patch idea</button>
<button class="action" onclick="fileAction('review')">Review</button>
<button class="action" onclick="fileAction('bugs')">Bugs</button>
</div>
</div>

<div class="control">
<label>Project actions</label>
<button class="action" onclick="runAction('analyze')">Analyze project</button>
<button class="action" onclick="runAction('bugs')">Find project bugs</button>
<button class="action" onclick="runAction('readme')">Generate README text</button>
<button class="action" onclick="cacheProject()">Cache project summary</button>
</div>

<div class="control">
<label>Git / checks</label>
<div class="grid2">
<button class="action" onclick="gitInfo()">git status</button>
<button class="action" onclick="gitDiff()">git diff</button>
<button class="action" onclick="commitFromDiff()">commit msg</button>
<button class="action" onclick="runCommand('python_compile')">compile</button>
<button class="action" onclick="runCommand('pytest')">pytest</button>
<button class="action" onclick="runCommand('ruff')">ruff</button>
<button class="action" onclick="runCommand('cppcheck')">cppcheck</button>
<button class="action" onclick="runCommand('clang_tidy')">clang-tidy</button>
<button class="action" onclick="runCommand('bandit')">bandit</button>
<button class="action" onclick="runCommand('npm_test')">npm test</button>
<button class="action" onclick="runCommand('npm_build')">npm build</button>
<button class="action" onclick="runCommand('npm_audit')">npm audit</button>

<button class="action" onclick="detectProject()">detect type</button>
<button class="action" onclick="runCommand('health')">health score</button>
<button class="action" onclick="explainLast()">explain last output</button>
<button class="action" onclick="createCppProject()">new C++ project</button>

<button class="action" onclick="runCommand('cpp_compile')">C++ compile</button>
<button class="action" onclick="runCommand('cmake_configure')">cmake config</button>
<button class="action" onclick="runCommand('cmake_build')">cmake build</button>
</div>
</div>

<div class="control"><label>Search project</label><input id="search" placeholder="Search text..."><button class="action" onclick="searchProject()">Search</button></div>


<div class="control">
<label>Project settings</label>
<button class="action" onclick="loadProjectSettings()">Load settings</button>
<button class="action" onclick="saveProjectSettings()">Save settings</button>
<div class="small">Saved: model, mode, project context</div>
</div>

<button class="secondary" onclick="showDebug()">Show debug</button>
<button class="secondary" onclick="clearChat()">Clear Memory</button>
<div class="control small">Backend: Ollama<br>Version: 0.8.0</div>
</aside>

<main class="main">
<div class="header">
<div><h2>ForceHub Chat Pro</h2><div class="small">Streaming + diff preview + safe save</div></div>
<div id="state" class="badge">Ready</div>
</div>

<div id="chat" class="chat">
<div class="msg ai">Ready. Streaming is enabled. Use the editor for safe file changes.</div>
<textarea id="editor" class="editor" placeholder="File content appears here after View file..."></textarea>
</div>

<div class="inputbar">
<textarea id="prompt" placeholder="Type your message... Enter = streaming send, Shift+Enter = newline"></textarea>
<button id="send" onclick="sendMessage()">Send</button>
</div>
</main>
</div>

<script>
const chat=document.getElementById("chat"),promptBox=document.getElementById("prompt"),sendBtn=document.getElementById("send"),state=document.getElementById("state"),modelSelect=document.getElementById("model"),modeSelect=document.getElementById("mode"),projectSelect=document.getElementById("project"),projectMode=document.getElementById("projectMode"),fileSelect=document.getElementById("file"),searchBox=document.getElementById("search"),editor=document.getElementById("editor");

function addMessage(text,cls){const div=document.createElement("div");div.className="msg "+cls;div.textContent=text;chat.appendChild(div);chat.scrollTop=chat.scrollHeight;return div}
function busy(x){sendBtn.disabled=x;sendBtn.textContent=x?"Thinking":"Send";state.textContent=x?"Working...":"Ready"}

async function loadModels(){try{const res=await fetch("/api/models");const data=await res.json();modelSelect.innerHTML='<option value="auto">auto</option>';for(const m of data.models){const o=document.createElement("option");o.value=m;o.textContent=m;modelSelect.appendChild(o)}}catch{modelSelect.innerHTML='<option value="auto">auto</option><option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>'}}
async function loadProjects(){const res=await fetch("/projects");const data=await res.json();projectSelect.innerHTML="";for(const p of data.projects){const o=document.createElement("option");o.value=p;o.textContent=p;projectSelect.appendChild(o)}const fallback=data.default_project&&data.projects.includes(data.default_project)?data.default_project:data.projects[0];if(fallback)projectSelect.value=fallback;await loadFiles();if(fallback)await loadProjectSettings()}
async function loadFiles(){if(!projectSelect.value){fileSelect.innerHTML="";return}const res=await fetch("/api/files?project="+encodeURIComponent(projectSelect.value));const data=await res.json();fileSelect.innerHTML="";for(const f of data.files){const o=document.createElement("option");o.value=f;o.textContent=f;fileSelect.appendChild(o)}}
projectSelect.addEventListener("change",async()=>{await loadFiles();await loadProjectSettings()});

async function sendMessage(){
 const prompt=promptBox.value.trim(); if(!prompt)return;
 addMessage(prompt,"user"); promptBox.value=""; busy(true);
 const aiDiv=addMessage("","ai");
 try{
  const res=await fetch("/api/chat-stream",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt,model:modelSelect.value,mode:modeSelect.value,project:projectSelect.value,project_mode:projectMode.checked})});
  const reader=res.body.getReader(); const decoder=new TextDecoder();
  while(true){const {done,value}=await reader.read(); if(done)break; aiDiv.textContent+=decoder.decode(value); chat.scrollTop=chat.scrollHeight}
 }catch(e){aiDiv.textContent="Request error: "+e; aiDiv.className="msg ai error"}finally{busy(false);promptBox.focus()}
}

async function runAction(action){addMessage("Project action: "+action,"user");busy(true);try{const res=await fetch("/api/project-action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,model:modelSelect.value,project:projectSelect.value})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}finally{busy(false)}}
async function fileAction(action){addMessage("File action: "+action+" → "+fileSelect.value,"user");busy(true);try{const res=await fetch("/api/file-action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,model:modelSelect.value,project:projectSelect.value,file:fileSelect.value})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}finally{busy(false)}}
async function viewFile(){const res=await fetch("/api/file-content?project="+encodeURIComponent(projectSelect.value)+"&file="+encodeURIComponent(fileSelect.value));const data=await res.json();editor.value=data.content||"";addMessage("Loaded file: "+fileSelect.value,"ai")}
async function previewDiff(){const res=await fetch("/api/diff-content",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content:editor.value})});const data=await res.json();addMessage(data.text||data.error||"No diff",data.error?"ai error":"ai")}
async function saveFile(){if(!confirm("Save file with timestamped .bak backup?"))return;const res=await fetch("/api/save-file",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content:editor.value,backup:true})});const data=await res.json();addMessage(data.text||data.error||"Saved",data.error?"ai error":"ai")}
async function gitInfo(){const res=await fetch("/api/git?project="+encodeURIComponent(projectSelect.value));const data=await res.json();addMessage(data.text||JSON.stringify(data,null,2),"ai")}
async function gitDiff(){const res=await fetch("/api/git-diff?project="+encodeURIComponent(projectSelect.value));const data=await res.json();addMessage(data.text||"No diff","ai")}
async function commitFromDiff(){busy(true);try{const res=await fetch("/api/commit-from-diff",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,model:modelSelect.value,action:"commit"})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}finally{busy(false)}}
async function searchProject(){const q=searchBox.value.trim();if(!q)return;const res=await fetch("/api/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,query:q})});const data=await res.json();addMessage(data.text||"No results","ai")}
async function runCommand(command){busy(true);try{const res=await fetch("/api/run-command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,command})});const data=await res.json();lastOutput = data.text || data.error || "No output"; addMessage(lastOutput,data.error?"ai error":"ai")}finally{busy(false)}}
async function cacheProject(){busy(true);try{const res=await fetch("/api/cache-project",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({project:projectSelect.value,model:modelSelect.value,action:"analyze"})});const data=await res.json();addMessage(data.text||data.error||"Cached",data.error?"ai error":"ai")}finally{busy(false)}}
async function showDebug(){const res=await fetch("/api/debug");const data=await res.json();addMessage(JSON.stringify(data,null,2),"ai")}
async function clearChat(){await fetch("/api/reset",{method:"POST"});chat.innerHTML="";chat.appendChild(editor);editor.value="";addMessage("Memory cleared.","ai")}

let lastOutput = "";

async function detectProject(){
  const res = await fetch("/api/detect?project="+encodeURIComponent(projectSelect.value));
  const data = await res.json();
  lastOutput = JSON.stringify(data, null, 2);
  addMessage(lastOutput, "ai");
}

async function explainLast(){
  if(!lastOutput.trim()){
    addMessage("No previous command output to explain.", "ai error");
    return;
  }
  busy(true);
  try{
    const res = await fetch("/api/explain-output", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({project:projectSelect.value, output:lastOutput, model:modelSelect.value})
    });
    const data = await res.json();
    addMessage(data.text || data.error || "No response", data.error ? "ai error" : "ai");
  } finally {
    busy(false);
  }
}

async function createCppProject(){
  const name = prompt("New C++ project folder name:");
  if(!name) return;
  const res = await fetch("/api/create-cpp-project", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({project:name})
  });
  const data = await res.json();
  addMessage(data.text || data.error || "Done", data.error ? "ai error" : "ai");
  await loadProjects();
}




async function loadProjectSettings(){
  const res = await fetch("/api/project-settings?project="+encodeURIComponent(projectSelect.value));
  const data = await res.json();

  if(data.preferred_model) modelSelect.value = data.preferred_model;
  if(data.preferred_mode) modeSelect.value = data.preferred_mode;
  if(typeof data.project_context === "boolean") projectMode.checked = data.project_context;

  addMessage("Loaded settings for " + projectSelect.value, "ai");
}

async function saveProjectSettings(){
  const res = await fetch("/api/project-settings", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      project: projectSelect.value,
      preferred_model: modelSelect.value,
      preferred_mode: modeSelect.value,
      project_context: projectMode.checked
    })
  });
  const data = await res.json();
  addMessage(data.text || data.error || "Settings saved", data.error ? "ai error" : "ai");
}


promptBox.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMessage()}});
loadModels();loadProjects();
</script>
</body>
</html>
"""


@app.get("/status", response_model=StatusResponse)
def status():
    return StatusResponse(status="ok", app=APP_NAME, version=APP_VERSION)


@app.get("/projects")
def list_projects():
    return {"projects": list_project_names(), "default_project": DEFAULT_PROJECT}


def project_file_listing(project: str, limit: int = 300) -> list[str]:
    root = safe_project_path(project)
    files = [str(p.relative_to(root)) for p in iter_project_files(root)]
    return sorted(files)[:limit]


def file_content_response(project: str, file: str) -> dict[str, str | int | bool]:
    target = safe_file_path(project, file)
    content, truncated = read_text_limited(target)
    return {"content": content, "truncated": truncated, "max_chars": MAX_FILE_CHARS}


def diff_content_response(req: DiffContentRequest) -> dict[str, str | bool]:
    target = safe_file_path(req.project, req.file)
    old_content, truncated = read_text_limited(target)
    if truncated:
        return {"error": True, "text": f"Cannot diff {req.file}: file exceeds {MAX_FILE_CHARS} characters."}
    old = old_content.splitlines(keepends=True)
    new = req.content.splitlines(keepends=True)
    diff = difflib.unified_diff(old, new, fromfile=f"a/{req.file}", tofile=f"b/{req.file}")
    text = "".join(diff)
    return {"text": text or "No changes."}


def create_file_backup(target: Path) -> Path:
    backup = target.with_suffix(target.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(target, backup)
    except OSError as exc:
        logger.exception("Failed to create backup for %s at %s", target, backup)
        raise RuntimeError(f"Unable to create backup for {target.name}") from exc
    return backup


def write_text_file(target: Path, content: str) -> None:
    temp = target.with_name(f".{target.name}.tmp-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    try:
        temp.write_text(content, encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        logger.exception("Failed to write file %s", target)
        raise RuntimeError(f"Unable to write file: {target.name}") from exc
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError as exc:
            logger.warning("Unable to remove temporary file %s: %s", temp, exc)


@app.get("/api/files")
async def api_files(project: str = DEFAULT_PROJECT):
    try:
        files = await run_in_threadpool(project_file_listing, project)
        return {"files": files}
    except Exception as e:
        return api_error("List files", e)


@app.get("/api/file-content")
async def api_file_content(project: str, file: str):
    try:
        return await run_in_threadpool(file_content_response, project, file)
    except Exception as e:
        return api_error("Read file content", e)


@app.post("/api/diff-content")
async def api_diff_content(req: DiffContentRequest):
    try:
        return await run_in_threadpool(diff_content_response, req)
    except Exception as e:
        return api_error("Diff preview", e)


@app.post("/api/save-file")
def api_save_file(req: SaveFileRequest):
    try:
        target = safe_file_path(req.project, req.file)
        if req.backup:
            create_file_backup(target)
        write_text_file(target, req.content)
        backup_text = " with backup" if req.backup else ""
        return {"text": f"Saved {req.file}{backup_text}."}
    except Exception as e:
        return api_error("Save file", e)


@app.get("/api/git")
def api_git(project: str = DEFAULT_PROJECT):
    status = run_git(project, ["status", "--short"])
    branch = run_git(project, ["branch", "--show-current"])
    log = run_git(project, ["log", "--oneline", "-5"])
    return {"text": f"Branch: {branch}\n\nStatus:\n{status or 'clean'}\n\nLast commits:\n{log}"}


@app.get("/api/git-diff")
def api_git_diff(project: str = DEFAULT_PROJECT):
    diff = run_git(project, ["diff", "--", "."])
    staged = run_git(project, ["diff", "--cached", "--", "."])
    return {"text": f"UNSTAGED DIFF:\n{diff or 'none'}\n\nSTAGED DIFF:\n{staged or 'none'}"[:25000]}


@app.post("/api/commit-from-diff")
def api_commit_from_diff(req: ProjectActionRequest):
    try:
        diff = run_git(req.project, ["diff", "--", "."])
        staged = run_git(req.project, ["diff", "--cached", "--", "."])
        combined = f"UNSTAGED DIFF:\n{diff}\n\nSTAGED DIFF:\n{staged}"
        if not diff.strip() and not staged.strip():
            return {"text": "No git diff found. Nothing to summarize."}

        prompt = f"""Generate a clean git commit message for this diff.

Rules:
- First line: short conventional commit style if suitable.
- Then 3-5 bullet changelog items.

DIFF:
{combined[:16000]}
"""
        answer, used_model, elapsed = ask_with_fallback(prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": "commit_from_diff"})
        return {"text": answer, "model": used_model}
    except Exception as e:
        return api_error("Commit message generation", e)


@app.get("/api/models")
def api_models():
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=10)
        r.raise_for_status()
        return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as exc:
        logger.warning("Failed to load Ollama models, returning fallback models: %s", exc)
        return {"models": ["qwen2.5-coder:7b", "qwen2.5-coder:1.5b"]}


@app.get("/api/debug")
def api_debug():
    return LAST_DEBUG


@app.post("/api/reset")
def reset_chat():
    CHAT_HISTORY.clear()
    return {"status": "cleared"}


def search_project_files(req: SearchRequest) -> dict[str, str]:
    root = safe_project_path(req.project)
    q = req.query.lower()
    results = []
    for path in iter_project_files(root):
        rel = str(path.relative_to(root))
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if q in line.lower():
                        results.append(f"{rel}:{line_number}: {line.strip()}")
                        if len(results) >= MAX_SEARCH_RESULTS:
                            break
        except OSError as exc:
            logger.warning("Skipping unreadable file during search %s: %s", path, exc)
            continue
        if len(results) >= MAX_SEARCH_RESULTS:
            break
    return {"text": "\n".join(results) if results else "No results found."}


@app.post("/api/search")
async def api_search(req: SearchRequest):
    try:
        return await run_in_threadpool(search_project_files, req)
    except Exception as e:
        return api_error("Search", e)


def run_python_module(project: str, module: str, *args: str, timeout: int = 90) -> str:
    return run_cmd(project, [sys.executable, "-m", module, *args], timeout=timeout)


def run_cpp_compile(project: str) -> str:
    root = safe_project_path(project)
    files = find_files(root, CPP_SOURCE_PATTERNS)
    if not files:
        return "No C++ source files found."

    compiler = resolve_executable("g++", "clang++", "cl")
    if not compiler:
        return "No C++ compiler found on PATH."

    relative_files = [str(path.relative_to(root)) for path in files]
    if Path(compiler).name.lower() == "cl.exe":
        return run_cmd(project, [compiler, "/std:c++20", "/W4", "/EHsc", "/Zs", *relative_files], timeout=90)

    return run_cmd(
        project,
        [compiler, "-std=c++20", "-Wall", "-Wextra", "-pedantic", "-fsyntax-only", *relative_files],
        timeout=90,
    )


def run_cmake_configure(project: str) -> str:
    root = safe_project_path(project)
    if not (root / "CMakeLists.txt").exists():
        return "CMakeLists.txt not found."

    cmake = resolve_executable("cmake")
    if not cmake:
        return "cmake is not installed or not on PATH."

    return run_cmd(project, [cmake, "-S", ".", "-B", "build"], timeout=120)


def run_cmake_build(project: str) -> str:
    root = safe_project_path(project)
    if not (root / "build").exists():
        return "build directory not found. Run cmake configure first."

    cmake = resolve_executable("cmake")
    if not cmake:
        return "cmake is not installed or not on PATH."

    jobs = str(os.cpu_count() or 1)
    return run_cmd(project, [cmake, "--build", "build", "--parallel", jobs], timeout=180)


def run_cppcheck(project: str) -> str:
    root = safe_project_path(project)
    if not find_files(root, CPP_SOURCE_PATTERNS + CPP_HEADER_PATTERNS):
        return "No C++ files found."

    cppcheck = resolve_executable("cppcheck")
    if not cppcheck:
        return "cppcheck is not installed or not on PATH."

    return run_cmd(
        project,
        [
            cppcheck,
            "--enable=warning,performance,portability,style",
            "--std=c++20",
            "--suppress=missingIncludeSystem",
            ".",
        ],
        timeout=180,
    )


def run_clang_tidy(project: str) -> str:
    root = safe_project_path(project)
    files = find_files(root, CPP_SOURCE_PATTERNS)[:20]
    if not files:
        return "No C++ source files found."

    clang_tidy = resolve_executable("clang-tidy")
    if not clang_tidy:
        return "clang-tidy is not installed or not on PATH."

    relative_files = [str(path.relative_to(root)) for path in files]
    return run_cmd(project, [clang_tidy, *relative_files, "--", "-std=c++20"], timeout=180)


def run_bandit(project: str) -> str:
    if not python_module_available("bandit"):
        return "bandit is not installed. Run: pip install bandit"
    return run_python_module(project, "bandit", "-r", ".", "-x", ".venv,venv,__pycache__,data", timeout=180)


def run_npm(project: str, *args: str) -> str:
    root = safe_project_path(project)
    if not (root / "package.json").exists():
        return "package.json not found."

    npm = resolve_executable("npm", "npm.cmd")
    if not npm:
        return "npm is not installed or not on PATH."

    return run_cmd(project, [npm, *args], timeout=180)


@app.post("/api/run-command")
def api_run_command(req: RunCommandRequest):
    commands = {
        "git_status": lambda project: run_git(project, ["status", "--short"]),
        "pytest": lambda project: run_python_module(project, "pytest", "-q"),
        "ruff": lambda project: run_python_module(project, "ruff", "check", "."),
        "ruff_fix": lambda project: run_python_module(project, "ruff", "check", ".", "--fix"),
        "python_compile": lambda project: run_python_module(project, "compileall", "-q", "."),
        "cpp_compile": run_cpp_compile,
        "cmake_configure": run_cmake_configure,
        "cmake_build": run_cmake_build,
        "cppcheck": run_cppcheck,
        "clang_tidy": run_clang_tidy,
        "bandit": run_bandit,
        "npm_test": lambda project: run_npm(project, "test"),
        "npm_build": lambda project: run_npm(project, "run", "build"),
        "npm_audit": lambda project: run_npm(project, "audit"),
    }
    try:
        if req.command == "health":
            return {"text": project_health(req.project)}

        output = commands[req.command](req.project)
        return {"text": output or "Command finished with no output."}
    except Exception as e:
        return api_error("Run command", e)


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    try:
        prompt = build_prompt(req.prompt, req.mode, req.project, req.project_mode)
        answer, used_model, elapsed = ask_with_fallback(prompt, req.model)
        CHAT_HISTORY.append({"role": "user", "content": req.prompt})
        CHAT_HISTORY.append({"role": "assistant", "content": answer})
        del CHAT_HISTORY[:-20]
        save_chat("user", req.prompt)
        save_chat("assistant", answer)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": "chat"})
        return {"text": answer, "model": used_model, "elapsed": elapsed}
    except Exception as e:
        return api_error("Chat", e)


@app.post("/api/chat-stream")
def api_chat_stream(req: ChatRequest):
    def generate():
        try:
            prompt = build_prompt(req.prompt, req.mode, req.project, req.project_mode)
            selected_model = choose_model(req.model, prompt)
            start = time.time()
            full = ""

            with requests.post(
                OLLAMA_GENERATE_URL,
                json={
                    "model": selected_model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.2, "top_p": 0.9, "num_ctx": 4096},
                },
                stream=True,
                timeout=180,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    chunk = obj.get("response", "")
                    full += chunk
                    yield chunk

            elapsed = round(time.time() - start, 2)
            CHAT_HISTORY.append({"role": "user", "content": req.prompt})
            CHAT_HISTORY.append({"role": "assistant", "content": full})
            del CHAT_HISTORY[:-20]
            save_chat("user", req.prompt)
            save_chat("assistant", full)
            LAST_DEBUG.update({"model": selected_model, "elapsed": elapsed, "action": "chat_stream"})

        except Exception as e:
            logger.exception("Chat stream failed")
            yield f"\n[stream error] Chat stream failed: {e}"

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/api/project-action")
def project_action(req: ProjectActionRequest):
    try:
        context = build_project_context(req.project)
        prompts = {
            "analyze": "Analyze this project. Explain what it does and give practical improvements.",
            "bugs": "Find bugs, weak points, security issues, and reliability problems.",
            "readme": "Write a professional GitHub README for this project.",
            "commit": "Generate a clean commit message and short changelog.",
        }
        final_prompt = f"You are ForceHub AI project reviewer.\n\nTask:\n{prompts[req.action]}\n\nProject context:\n{context}\n"
        answer, used_model, elapsed = ask_with_fallback(final_prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": req.action})
        return {"text": answer, "action": req.action, "model": used_model}
    except Exception as e:
        return api_error("Project action", e)


@app.post("/api/cache-project")
def cache_project(req: ProjectActionRequest):
    try:
        context = build_project_context(req.project)
        prompt = f"Create a concise technical summary of this project for future AI context.\n\nPROJECT:\n{context}"
        answer, used_model, elapsed = ask_with_fallback(prompt, req.model)
        cache = load_cache()
        cache[req.project] = {"updated": datetime.now().isoformat(timespec="seconds"), "model": used_model, "summary": answer}
        save_cache(cache)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": "cache_project"})
        return {"text": f"Cached project summary.\n\n{answer}", "model": used_model}
    except Exception as e:
        return api_error("Cache project", e)


@app.post("/api/file-action")
def file_action(req: FileReviewRequest):
    try:
        root = safe_project_path(req.project)
        file_path = safe_file_path(req.project, req.file)
        content = read_file_safe(file_path, root)
        prompts = {
            "review": "Review this file. Give practical improvements only.",
            "bugs": "Find likely bugs, security issues, and weak design choices in this file.",
            "explain": "Explain what this file does clearly.",
            "patch": "Suggest a safe patch. Do not apply it. Show replacement code blocks only.",
        }
        final_prompt = f"You are ForceHub AI file reviewer.\n\nTask:\n{prompts[req.action]}\n\nFile content:\n{content}\n"
        answer, used_model, elapsed = ask_with_fallback(final_prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": f"file_{req.action}"})
        return {"text": answer, "file": req.file, "action": req.action, "model": used_model}
    except Exception as e:
        return api_error("File action", e)


@app.post("/api/save-readme")
def save_readme(req: SaveReadmeRequest):
    try:
        root = safe_project_path(req.project)
        readme = root / "README.md"
        write_text_file(readme, req.content)
        return {"text": f"Saved README.md to {readme}"}
    except Exception as e:
        return api_error("Save README", e)



@app.get("/api/detect")
def api_detect(project: str = DEFAULT_PROJECT):
    try:
        return detect_project_type(project)
    except Exception as e:
        return api_error("Project detection", e)


@app.post("/api/explain-output")
def api_explain_output(req: ExplainOutputRequest):
    try:
        prompt = f"""Explain this build/test/lint output and give practical fixes.

Project: {req.project}

Output:
{req.output[:12000]}

Rules:
- Explain the root cause.
- Give exact next commands.
- Give code/config fixes only if needed.
"""
        answer, used_model, elapsed = ask_with_fallback(prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": "explain_output"})
        return {"text": answer, "model": used_model}
    except Exception as e:
        return api_error("Explain output", e)


@app.post("/api/create-cpp-project")
def api_create_cpp_project(req: CreateCppProjectRequest):
    try:
        project_name = normalize_project_name(req.project)
        root = (PROJECTS_DIR / project_name).resolve()
        if not is_relative_to(root, PROJECTS_DIR):
            raise ValueError("Invalid project path: resolved outside the allowed projects directory")
        if root.exists():
            raise ValueError(f"Project already exists: {project_name}")

        (root / "src").mkdir(parents=True)
        (root / "include").mkdir()

        (root / "src" / "main.cpp").write_text(
            '#include <iostream>\n\nint main() {\n    std::cout << "Hello from C++20!\\n";\n    return 0;\n}\n',
            encoding="utf-8",
        )

        (root / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\n"
            f"project({project_name} LANGUAGES CXX)\n\n"
            "set(CMAKE_CXX_STANDARD 20)\n"
            "set(CMAKE_CXX_STANDARD_REQUIRED ON)\n"
            "set(CMAKE_CXX_EXTENSIONS OFF)\n\n"
            "add_executable(${PROJECT_NAME} src/main.cpp)\n"
            "target_compile_options(${PROJECT_NAME} PRIVATE\n"
            "  $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->\n"
            "  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-Wall -Wextra -pedantic>\n"
            ")\n",
            encoding="utf-8",
        )

        (root / ".gitignore").write_text("build/\n*.o\n*.exe\n*.out\n.cache/\n", encoding="utf-8")
        (root / "README.md").write_text(f"# {project_name}\n\nC++20 CMake project.\n", encoding="utf-8")

        git_bin = get_git_command()
        git_message = ""
        if git_bin:
            subprocess.check_output([git_bin, "init"], cwd=root, text=True, stderr=subprocess.STDOUT)
        else:
            git_message = "\n\nGit was not initialized because git is not installed or not on PATH."

        return {
            "text": (
                f"Created C++ project: {root}\n\n"
                "Next:\n"
                f"cd {root}\n"
                "cmake -S . -B build\n"
                "cmake --build build"
                f"{git_message}"
            )
        }
    except Exception as e:
        return api_error("Create C++ project", e)



@app.get("/api/project-settings")
def api_get_project_settings(project: str = DEFAULT_PROJECT):
    data = load_project_settings()
    return data.get(project, {
        "project": project,
        "preferred_model": DEFAULT_MODEL,
        "preferred_mode": DEFAULT_MODE,
        "project_context": False,
    })


@app.post("/api/project-settings")
def api_save_project_settings(req: ProjectSettingsRequest):
    try:
        safe_project_path(req.project)

        data = load_project_settings()
        data[req.project] = {
            "project": req.project,
            "preferred_model": req.preferred_model,
            "preferred_mode": req.preferred_mode,
            "project_context": req.project_context,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        save_project_settings(data)

        return {"text": f"Saved settings for {req.project}"}
    except Exception as e:
        return api_error("Save project settings", e)


@app.post("/ask")
def ask_legacy(req: ChatRequest):
    return api_chat(req)


def main() -> None:
    import uvicorn

    host = env_str("FORCEHUB_HOST", "127.0.0.1")
    port = env_int("FORCEHUB_PORT", 8000, minimum=1, maximum=65535)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
