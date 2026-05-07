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
- `FORCEHUB_DEFAULT_PROJECT`: project selected by default in the UI
- `FORCEHUB_DATA_DIR`: directory used for chat history and cached settings
- `FORCEHUB_USERNAME`: basic-auth username
- `FORCEHUB_PASSWORD`: basic-auth password
- `FORCEHUB_AUTH_DISABLED`: set to `1` only for an intentionally unauthenticated local instance
- `FORCEHUB_HOST`: bind host for the FastAPI server
- `FORCEHUB_PORT`: bind port for the FastAPI server
- `FORCEHUB_GIT_BIN`: explicit path to the `git` executable
