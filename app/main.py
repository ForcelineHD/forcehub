import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

APP_NAME = "forcehub"
APP_VERSION = "0.5.0"

PROJECTS_DIR = Path("/home/flozi/projects")
DEFAULT_PROJECT = "forcehub"
DATA_DIR = Path("/home/flozi/projects/forcehub/data")
CHAT_FILE = DATA_DIR / "chats.json"

OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

MAX_FILE_CHARS = 6000
MAX_PROJECT_FILES = 15

app = FastAPI(
    title="ForceHub",
    description="Local project-aware AI dashboard.",
    version=APP_VERSION,
)

CHAT_HISTORY: list[dict[str, str]] = []


class StatusResponse(BaseModel):
    status: str
    app: str
    version: str


class ChatRequest(BaseModel):
    prompt: str
    model: str = "qwen2.5-coder:7b"
    mode: Literal["normal", "code", "short", "explain"] = "normal"
    project: str = DEFAULT_PROJECT
    project_mode: bool = False


class FileReviewRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    file: str
    model: str = "qwen2.5-coder:7b"
    action: Literal["review", "bugs", "explain", "patch"] = "review"


class ProjectActionRequest(BaseModel):
    action: Literal["analyze", "bugs", "readme", "commit"]
    model: str = "qwen2.5-coder:7b"
    project: str = DEFAULT_PROJECT


def safe_project_path(project: str) -> Path:
    base = PROJECTS_DIR.resolve()
    target = (PROJECTS_DIR / project).resolve()

    if not str(target).startswith(str(base)):
        raise ValueError("Invalid project path")

    if not target.exists() or not target.is_dir():
        raise ValueError(f"Project not found: {project}")

    return target


def safe_file_path(project: str, file: str) -> Path:
    root = safe_project_path(project)
    target = (root / file).resolve()

    if not str(target).startswith(str(root.resolve())):
        raise ValueError("Invalid file path")

    if not target.exists() or not target.is_file():
        raise ValueError(f"File not found: {file}")

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
    }

    return path.suffix.lower() in allowed_ext or path.name in {"Dockerfile", ".gitignore"}


def read_file_safe(path: Path, root: Path) -> str:
    try:
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
        return f"\n\n--- FILE: {rel} ---\n{text}"
    except Exception as e:
        return f"\n\n--- FILE ERROR: {path.name}: {e} ---"


def build_project_context(project: str) -> str:
    root = safe_project_path(project)
    chunks = [f"PROJECT: {project}\nROOT: {root}\n"]

    files = [
        p for p in root.rglob("*")
        if p.is_file() and should_include_file(p)
    ]

    files = sorted(files, key=lambda p: str(p.relative_to(root)))[:MAX_PROJECT_FILES]

    for file in files:
        chunks.append(read_file_safe(file, root))

    return "\n".join(chunks)


def build_prompt(user_prompt: str, mode: str, project: str, project_mode: bool) -> str:
    system = {
        "normal": "You are ForceHub AI. Answer clearly and practically.",
        "code": "You are ForceHub AI coding assistant. Give code-first, practical answers.",
        "short": "Answer briefly and directly. No padding.",
        "explain": "Explain step by step, but avoid unnecessary basics.",
    }.get(mode, "You are ForceHub AI.")

    history = ""
    for item in CHAT_HISTORY[-8:]:
        history += f"{item['role']}: {item['content']}\n"

    project_context = build_project_context(project) if project_mode else ""

    return f"""{system}

Conversation:
{history}

Project context:
{project_context}

User request:
{user_prompt}

Assistant:"""


def ask_ollama(prompt: str, model: str) -> str:
    r = requests.post(
        OLLAMA_GENERATE_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "top_p": 0.9,
                "num_ctx": 4096,
            },
        },
        timeout=180,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text}")

    return r.json().get("response", "").strip()


def ask_with_fallback(prompt: str, model: str) -> tuple[str, str]:
    try:
        return ask_ollama(prompt, model), model
    except Exception:
        return ask_ollama(prompt, "qwen2.5-coder:1.5b"), "qwen2.5-coder:1.5b"


def save_chat(role: str, content: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    item = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }

    data = []
    if CHAT_FILE.exists():
        try:
            data = json.loads(CHAT_FILE.read_text())
        except Exception:
            data = []

    data.append(item)
    data = data[-100:]
    CHAT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_git(project: str, args: list[str]) -> str:
    root = safe_project_path(project)
    try:
        out = subprocess.check_output(
            ["git", *args],
            cwd=root,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        return out.strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()
    except Exception as e:
        return str(e)


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
.layout{display:grid;grid-template-columns:310px 1fr;height:100vh}
.sidebar{background:var(--panel);border-right:1px solid var(--border);padding:18px;overflow:auto}
.sidebar h2{margin:0 0 8px;color:#8ab4ff}.small{color:var(--muted);font-size:13px}
.sidebar a{color:#b7c7ff;display:block;margin:10px 0;text-decoration:none}
.control{margin-top:14px}label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}
select,input{width:100%;background:#0f1117;color:var(--text);border:1px solid #30384d;border-radius:8px;padding:8px}
.main{display:flex;flex-direction:column;height:100vh}.header{padding:14px 22px;border-bottom:1px solid var(--border);background:var(--panel2);display:flex;justify-content:space-between;align-items:center}
.header h2{margin:0}.chat{flex:1;overflow-y:auto;padding:22px}
.msg{max-width:980px;padding:14px 16px;margin-bottom:14px;border-radius:12px;white-space:pre-wrap;line-height:1.48;font-size:14px}
.user{background:var(--user);margin-left:auto}.ai{background:var(--ai);border:1px solid #2b3245}.error{background:#3a1d24;border:1px solid #6d2b39}
.inputbar{display:flex;gap:10px;padding:16px;border-top:1px solid var(--border);background:var(--panel2)}
textarea{flex:1;resize:none;height:60px;border-radius:10px;border:1px solid #30384d;background:#0f1117;color:#eee;padding:12px;font-size:15px}
button{border:0;border-radius:10px;background:var(--blue);color:white;font-weight:bold;cursor:pointer;padding:10px 14px}
button:disabled{background:#3a3f50;cursor:wait}.secondary{background:#2a3040;width:100%;margin-top:8px}.action{background:#26385f;width:100%;margin-top:8px;text-align:left}
.badge{font-size:12px;color:#b7c7ff}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
<h2>ForceHub</h2>
<div class="small">Project-aware AI dashboard</div>
<hr style="border-color:#252b3a">

<a href="/status">Status API</a>
<a href="/projects">Projects API</a>
<a href="/docs">API Docs</a>

<div class="control"><label>Project</label><select id="project"></select></div>
<div class="control"><label>Model</label><select id="model"></select></div>
<div class="control"><label>Mode</label><select id="mode">
<option value="normal">Normal</option><option value="code">Code Assistant</option><option value="short">Short Answers</option><option value="explain">Explain Step-by-Step</option>
</select></div>

<div class="control"><label><input id="projectMode" type="checkbox"> Use project context</label></div>

<div class="control">
<label>File-aware review</label>
<select id="file"></select>
<div class="grid2">
<button class="action" onclick="fileAction('review')">Review file</button>
<button class="action" onclick="fileAction('bugs')">Find bugs</button>
<button class="action" onclick="fileAction('explain')">Explain file</button>
<button class="action" onclick="fileAction('patch')">Suggest patch</button>
</div>
</div>

<div class="control">
<label>Project actions</label>
<button class="action" onclick="runAction('analyze')">Analyze project</button>
<button class="action" onclick="runAction('bugs')">Find project bugs</button>
<button class="action" onclick="runAction('readme')">Generate README</button>
<button class="action" onclick="runAction('commit')">Commit message</button>
</div>

<div class="control">
<label>Git helper</label>
<button class="action" onclick="gitInfo()">Show Git status</button>
</div>

<button class="secondary" onclick="clearChat()">Clear Memory</button>
<div class="control small">Backend: Ollama<br>Version: 0.5.0</div>
</aside>

<main class="main">
<div class="header">
<div><h2>ForceHub Chat Pro</h2><div class="small">Project-aware + file-aware + Git helper</div></div>
<div id="state" class="badge">Ready</div>
</div>

<div id="chat" class="chat">
<div class="msg ai">Ready. Pick a file or enable project context.</div>
</div>

<div class="inputbar">
<textarea id="prompt" placeholder="Type your message... Enter = send, Shift+Enter = newline"></textarea>
<button id="send" onclick="sendMessage()">Send</button>
</div>
</main>
</div>

<script>
const chat=document.getElementById("chat"),promptBox=document.getElementById("prompt"),sendBtn=document.getElementById("send"),state=document.getElementById("state"),modelSelect=document.getElementById("model"),modeSelect=document.getElementById("mode"),projectSelect=document.getElementById("project"),projectMode=document.getElementById("projectMode"),fileSelect=document.getElementById("file");

function addMessage(text,cls){const div=document.createElement("div");div.className="msg "+cls;div.textContent=text;chat.appendChild(div);chat.scrollTop=chat.scrollHeight}
function busy(x){sendBtn.disabled=x;sendBtn.textContent=x?"Thinking":"Send";state.textContent=x?"Working...":"Ready"}

async function loadModels(){try{const res=await fetch("/api/models");const data=await res.json();modelSelect.innerHTML="";for(const m of data.models){const o=document.createElement("option");o.value=m;o.textContent=m;modelSelect.appendChild(o)}if(data.models.includes("qwen2.5-coder:7b"))modelSelect.value="qwen2.5-coder:7b"}catch{modelSelect.innerHTML='<option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>'}}
async function loadProjects(){const res=await fetch("/projects");const data=await res.json();projectSelect.innerHTML="";for(const p of data.projects){const o=document.createElement("option");o.value=p;o.textContent=p;projectSelect.appendChild(o)}if(data.projects.includes("forcehub"))projectSelect.value="forcehub";await loadFiles()}
async function loadFiles(){const res=await fetch("/api/files?project="+encodeURIComponent(projectSelect.value));const data=await res.json();fileSelect.innerHTML="";for(const f of data.files){const o=document.createElement("option");o.value=f;o.textContent=f;fileSelect.appendChild(o)}}

projectSelect.addEventListener("change",loadFiles);

async function sendMessage(){
 const prompt=promptBox.value.trim(); if(!prompt)return;
 addMessage(prompt,"user"); promptBox.value=""; busy(true);
 try{const res=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt,model:modelSelect.value,mode:modeSelect.value,project:projectSelect.value,project_mode:projectMode.checked})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}catch(e){addMessage("Request error: "+e,"ai error")}finally{busy(false);promptBox.focus()}
}

async function runAction(action){
 addMessage("Project action: "+action,"user"); busy(true);
 try{const res=await fetch("/api/project-action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,model:modelSelect.value,project:projectSelect.value})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}catch(e){addMessage("Request error: "+e,"ai error")}finally{busy(false)}
}

async function fileAction(action){
 addMessage("File action: "+action+" → "+fileSelect.value,"user"); busy(true);
 try{const res=await fetch("/api/file-action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,model:modelSelect.value,project:projectSelect.value,file:fileSelect.value})});const data=await res.json();addMessage(data.text||data.error||"No response",data.error?"ai error":"ai")}catch(e){addMessage("Request error: "+e,"ai error")}finally{busy(false)}
}

async function gitInfo(){const res=await fetch("/api/git?project="+encodeURIComponent(projectSelect.value));const data=await res.json();addMessage(data.text||JSON.stringify(data,null,2),"ai")}
async function clearChat(){await fetch("/api/reset",{method:"POST"});chat.innerHTML="";addMessage("Memory cleared.","ai")}

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
    return {"projects": sorted([p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()])}


@app.get("/api/files")
def api_files(project: str = DEFAULT_PROJECT):
    root = safe_project_path(project)
    files = [
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and should_include_file(p)
    ]
    return {"files": sorted(files)[:200]}


@app.get("/api/git")
def api_git(project: str = DEFAULT_PROJECT):
    status = run_git(project, ["status", "--short"])
    branch = run_git(project, ["branch", "--show-current"])
    log = run_git(project, ["log", "--oneline", "-5"])
    return {"text": f"Branch: {branch}\\n\\nStatus:\\n{status or 'clean'}\\n\\nLast commits:\\n{log}"}


@app.get("/api/models")
def api_models():
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=10)
        r.raise_for_status()
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        return {"models": models or ["qwen2.5-coder:7b"]}
    except Exception:
        return {"models": ["qwen2.5-coder:7b", "qwen2.5-coder:1.5b"]}


@app.post("/api/reset")
def reset_chat():
    CHAT_HISTORY.clear()
    return {"status": "cleared"}


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    try:
        prompt = build_prompt(req.prompt, req.mode, req.project, req.project_mode)
        answer, used_model = ask_with_fallback(prompt, req.model)

        CHAT_HISTORY.append({"role": "user", "content": req.prompt})
        CHAT_HISTORY.append({"role": "assistant", "content": answer})
        del CHAT_HISTORY[:-20]

        save_chat("user", req.prompt)
        save_chat("assistant", answer)

        return {"text": answer, "model": used_model}
    except Exception as e:
        return {"error": True, "text": str(e)}


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

        final_prompt = f"""You are ForceHub AI project reviewer.

Task:
{prompts[req.action]}

Project context:
{context}

Answer clearly and practically.
"""

        answer, used_model = ask_with_fallback(final_prompt, req.model)
        return {"text": answer, "action": req.action, "model": used_model}
    except Exception as e:
        return {"error": True, "text": str(e)}


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

        final_prompt = f"""You are ForceHub AI file reviewer.

Task:
{prompts[req.action]}

File content:
{content}

Answer clearly and practically.
"""

        answer, used_model = ask_with_fallback(final_prompt, req.model)
        return {"text": answer, "file": req.file, "action": req.action, "model": used_model}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/ask")
def ask_legacy(req: ChatRequest):
    return api_chat(req)
