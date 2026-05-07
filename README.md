# ForceHub

ForceHub is a local FastAPI dashboard for browsing project files, running common repo checks, and sending project-aware prompts to a local Ollama instance.

## Requirements

- Python 3.11+
- `git` on `PATH` for git actions
- Optional tools for advanced checks:
  - `pytest`
  - `ruff`
  - `bandit`
  - `cmake`
  - `cppcheck`
  - `clang-tidy`
  - `npm`

Install the Python dependencies with:

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The app listens on `127.0.0.1:8000` by default.

## Configuration

- `FORCEHUB_PROJECTS_DIR`: directory that contains the projects ForceHub should inspect
- `FORCEHUB_DEFAULT_PROJECT`: project selected by default in the UI; if unset, the UI selects the first allowed project
- `FORCEHUB_DATA_DIR`: directory used for chat history and cached settings
- `FORCEHUB_USERNAME`: basic-auth username
- `FORCEHUB_PASSWORD`: basic-auth password
- `FORCEHUB_PASSWORD_FILE`: path to a file containing the basic-auth password
- `FORCEHUB_AUTH_DISABLED`: set to `1` only for an intentionally unauthenticated local instance
- `FORCEHUB_OLLAMA_URL`: Ollama base URL, default `http://127.0.0.1:11434`
- `FORCEHUB_OLLAMA_GENERATE_URL`: full Ollama generate endpoint override
- `FORCEHUB_OLLAMA_TAGS_URL`: full Ollama tags endpoint override
- `FORCEHUB_HOST`: bind host for the FastAPI server
- `FORCEHUB_PORT`: bind port for the FastAPI server
- `FORCEHUB_GIT_BIN`: explicit path to the `git` executable
- `FORCEHUB_LOG_LEVEL`: app log level, default `INFO`
- `FORCEHUB_LOG_FILE`: optional rotating log file path; unset keeps app logs off disk
- `FORCEHUB_LOG_MAX_BYTES`: maximum size for one log file before rotation
- `FORCEHUB_LOG_BACKUP_COUNT`: number of rotated log files to keep
