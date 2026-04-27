import difflib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

APP_NAME = "forcehub"
APP_VERSION = "0.8.0"

PROJECTS_DIR = Path("/home/flozi/projects")
DEFAULT_PROJECT = "forcehub"
DATA_DIR = Path("/home/flozi/projects/forcehub/data")
CHAT_FILE = DATA_DIR / "chats.json"
PROJECT_CACHE_FILE = DATA_DIR / "project_cache.json"

OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

MAX_FILE_CHARS = 8000
MAX_PROJECT_FILES = 15
MAX_SEARCH_RESULTS = 80

app = FastAPI(title="ForceHub", description="Local AI dev dashboard.", version=APP_VERSION)

CHAT_HISTORY: list[dict[str, str]] = []
LAST_DEBUG: dict[str, str | int | float] = {}


class StatusResponse(BaseModel):
    status: str
    app: str
    version: str


class ChatRequest(BaseModel):
    prompt: str
    model: str = "auto"
    mode: Literal["normal", "code", "cpp", "short", "explain"] = "normal"
    project: str = DEFAULT_PROJECT
    project_mode: bool = False


class FileReviewRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    file: str
    model: str = "auto"
    action: Literal["review", "bugs", "explain", "patch"] = "review"


class ProjectActionRequest(BaseModel):
    action: Literal["analyze", "bugs", "readme", "commit"]
    model: str = "auto"
    project: str = DEFAULT_PROJECT


class SearchRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    query: str


class SaveReadmeRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    content: str


class SaveFileRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    file: str
    content: str
    backup: bool = True


class DiffContentRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    file: str
    content: str


class RunCommandRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    command: Literal["git_status", "pytest", "ruff", "ruff_fix", "python_compile", "cpp_compile", "cmake_configure", "cmake_build", "cppcheck", "clang_tidy", "bandit", "npm_test", "npm_build", "npm_audit", "health"]



class ExplainOutputRequest(BaseModel):
    project: str = DEFAULT_PROJECT
    output: str
    model: str = "auto"


class CreateCppProjectRequest(BaseModel):
    project: str


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
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    }
    return path.suffix.lower() in allowed_ext or path.name in {"Dockerfile", ".gitignore", "CMakeLists.txt", "Makefile"}


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
    files = [p for p in root.rglob("*") if p.is_file() and should_include_file(p)]
    files = sorted(files, key=lambda p: str(p.relative_to(root)))[:MAX_PROJECT_FILES]
    for file in files:
        chunks.append(read_file_safe(file, root))
    return "\n".join(chunks)


def load_cache() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not PROJECT_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(PROJECT_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    PROJECT_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
    except Exception:
        return ask_ollama(prompt, "qwen2.5-coder:1.5b")


def save_chat(role: str, content: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    item = {"time": datetime.now().isoformat(timespec="seconds"), "role": role, "content": content}
    data = []
    if CHAT_FILE.exists():
        try:
            data = json.loads(CHAT_FILE.read_text())
        except Exception:
            data = []
    data.append(item)
    CHAT_FILE.write_text(json.dumps(data[-100:], indent=2), encoding="utf-8")


def run_cmd(project: str, cmd: list[str], timeout: int = 60) -> str:
    root = safe_project_path(project)
    try:
        return subprocess.check_output(cmd, cwd=root, stderr=subprocess.STDOUT, text=True, timeout=timeout).strip()
    except subprocess.CalledProcessError as e:
        return e.output.strip()
    except Exception as e:
        return str(e)


def run_git(project: str, args: list[str]) -> str:
    return run_cmd(project, ["git", *args], timeout=20)



def command_exists(project: str, command: str) -> bool:
    out = run_cmd(project, ["bash", "-lc", f"command -v {command} >/dev/null 2>&1 && echo yes || echo no"], timeout=10)
    return out.strip() == "yes"


def detect_project_type(project: str) -> dict:
    root = safe_project_path(project)

    files = {p.name for p in root.iterdir() if p.is_file()}
    has_py = any(root.rglob("*.py"))
    has_cpp = any(root.rglob(pattern) for pattern in ("*.cpp", "*.cc", "*.cxx", "*.hpp", "*.h"))
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
            "pytest": command_exists(project, "pytest"),
            "ruff": command_exists(project, "ruff"),
            "bandit": command_exists(project, "bandit"),
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
    lines.append(str(detected))

    return "\\n".join(lines)


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
async function loadProjects(){const res=await fetch("/projects");const data=await res.json();projectSelect.innerHTML="";for(const p of data.projects){const o=document.createElement("option");o.value=p;o.textContent=p;projectSelect.appendChild(o)}if(data.projects.includes("forcehub"))projectSelect.value="forcehub";await loadFiles()}
async function loadFiles(){const res=await fetch("/api/files?project="+encodeURIComponent(projectSelect.value));const data=await res.json();fileSelect.innerHTML="";for(const f of data.files){const o=document.createElement("option");o.value=f;o.textContent=f;fileSelect.appendChild(o)}}
projectSelect.addEventListener("change",loadFiles);

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
    files = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and should_include_file(p)]
    return {"files": sorted(files)[:300]}


@app.get("/api/file-content")
def api_file_content(project: str, file: str):
    target = safe_file_path(project, file)
    return {"content": target.read_text(encoding="utf-8", errors="replace")}


@app.post("/api/diff-content")
def api_diff_content(req: DiffContentRequest):
    try:
        target = safe_file_path(req.project, req.file)
        old = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        new = req.content.splitlines(keepends=True)
        diff = difflib.unified_diff(old, new, fromfile=f"a/{req.file}", tofile=f"b/{req.file}")
        text = "".join(diff)
        return {"text": text or "No changes."}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/api/save-file")
def api_save_file(req: SaveFileRequest):
    try:
        target = safe_file_path(req.project, req.file)
        if req.backup:
            backup = target.with_suffix(target.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            backup.write_text(target.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        target.write_text(req.content, encoding="utf-8")
        return {"text": f"Saved {req.file} with backup."}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.get("/api/git")
def api_git(project: str = DEFAULT_PROJECT):
    status = run_git(project, ["status", "--short"])
    branch = run_git(project, ["branch", "--show-current"])
    log = run_git(project, ["log", "--oneline", "-5"])
    return {"text": f"Branch: {branch}\\n\\nStatus:\\n{status or 'clean'}\\n\\nLast commits:\\n{log}"}


@app.get("/api/git-diff")
def api_git_diff(project: str = DEFAULT_PROJECT):
    diff = run_git(project, ["diff", "--", "."])
    staged = run_git(project, ["diff", "--cached", "--", "."])
    return {"text": f"UNSTAGED DIFF:\\n{diff or 'none'}\\n\\nSTAGED DIFF:\\n{staged or 'none'}"[:25000]}


@app.post("/api/commit-from-diff")
def api_commit_from_diff(req: ProjectActionRequest):
    try:
        diff = run_git(req.project, ["diff", "--", "."])
        staged = run_git(req.project, ["diff", "--cached", "--", "."])
        combined = f"UNSTAGED DIFF:\\n{diff}\\n\\nSTAGED DIFF:\\n{staged}"
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
        return {"error": True, "text": str(e)}


@app.get("/api/models")
def api_models():
    try:
        r = requests.get(OLLAMA_TAGS_URL, timeout=10)
        r.raise_for_status()
        return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception:
        return {"models": ["qwen2.5-coder:7b", "qwen2.5-coder:1.5b"]}


@app.get("/api/debug")
def api_debug():
    return LAST_DEBUG


@app.post("/api/reset")
def reset_chat():
    CHAT_HISTORY.clear()
    return {"status": "cleared"}


@app.post("/api/search")
def api_search(req: SearchRequest):
    try:
        root = safe_project_path(req.project)
        q = req.query.lower()
        results = []
        for path in root.rglob("*"):
            if not path.is_file() or not should_include_file(path):
                continue
            rel = str(path.relative_to(root))
            for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if q in line.lower():
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if len(results) >= MAX_SEARCH_RESULTS:
                        break
            if len(results) >= MAX_SEARCH_RESULTS:
                break
        return {"text": "\\n".join(results) if results else "No results found."}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/api/run-command")
def api_run_command(req: RunCommandRequest):
    commands = {
        "git_status": ["git", "status", "--short"],
        "pytest": ["python3", "-m", "pytest", "-q"],
        "ruff": ["python3", "-m", "ruff", "check", "."],
        "ruff_fix": ["python3", "-m", "ruff", "check", ".", "--fix"],
        "python_compile": ["python3", "-m", "compileall", "-q", "."],
        "cpp_compile": [
            "bash",
            "-lc",
            "shopt -s nullglob globstar; files=(**/*.cpp **/*.cc **/*.cxx); if [ ${#files[@]} -eq 0 ]; then echo No C++ source files found.; else g++ -std=c++20 -Wall -Wextra -pedantic -fsyntax-only ${files[@]}; fi",
        ],
        "cmake_configure": ["bash", "-lc", "cmake -S . -B build"],
        "cmake_build": ["bash", "-lc", "cmake --build build -j$(nproc)"],
        "cppcheck": [
            "bash",
            "-lc",
            "command -v cppcheck >/dev/null 2>&1 || { echo 'cppcheck not installed. Run: sudo apt install cppcheck'; exit 0; }; cppcheck --enable=warning,performance,portability,style --std=c++20 --suppress=missingIncludeSystem .",
        ],
        "clang_tidy": [
            "bash",
            "-lc",
            "command -v clang-tidy >/dev/null 2>&1 || { echo 'clang-tidy not installed. Run: sudo apt install clang-tidy'; exit 0; }; files=$(find . -type f \( -name '*.cpp' -o -name '*.cc' -o -name '*.cxx' \) | head -20); if [ -z \"$files\" ]; then echo No C++ source files found.; else clang-tidy $files -- -std=c++20; fi",
        ],
        "bandit": [
            "bash",
            "-lc",
            "command -v bandit >/dev/null 2>&1 || { echo 'bandit not installed. Run: pip install bandit'; exit 0; }; bandit -r . -x .venv,venv,__pycache__,data",
        ],
        "npm_test": [
            "bash",
            "-lc",
            "if [ ! -f package.json ]; then echo package.json not found.; elif ! command -v npm >/dev/null 2>&1; then echo npm not installed.; else npm test; fi",
        ],
        "npm_build": [
            "bash",
            "-lc",
            "if [ ! -f package.json ]; then echo package.json not found.; elif ! command -v npm >/dev/null 2>&1; then echo npm not installed.; else npm run build; fi",
        ],
        "npm_audit": [
            "bash",
            "-lc",
            "if [ ! -f package.json ]; then echo package.json not found.; elif ! command -v npm >/dev/null 2>&1; then echo npm not installed.; else npm audit; fi",
        ],
        "health": ["bash", "-lc", "echo health"],
    }
    try:
        if req.command == "health":
            return {"text": project_health(req.project)}

        output = run_cmd(req.project, commands[req.command], timeout=90)
        return {"text": output or "Command finished with no output."}
    except Exception as e:
        return {"error": True, "text": str(e)}


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
        return {"error": True, "text": str(e)}


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
            yield f"\\n[stream error] {e}"

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
        final_prompt = f"You are ForceHub AI project reviewer.\\n\\nTask:\\n{prompts[req.action]}\\n\\nProject context:\\n{context}\\n"
        answer, used_model, elapsed = ask_with_fallback(final_prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": req.action})
        return {"text": answer, "action": req.action, "model": used_model}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/api/cache-project")
def cache_project(req: ProjectActionRequest):
    try:
        context = build_project_context(req.project)
        prompt = f"Create a concise technical summary of this project for future AI context.\\n\\nPROJECT:\\n{context}"
        answer, used_model, elapsed = ask_with_fallback(prompt, req.model)
        cache = load_cache()
        cache[req.project] = {"updated": datetime.now().isoformat(timespec="seconds"), "model": used_model, "summary": answer}
        save_cache(cache)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": "cache_project"})
        return {"text": f"Cached project summary.\\n\\n{answer}", "model": used_model}
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
        final_prompt = f"You are ForceHub AI file reviewer.\\n\\nTask:\\n{prompts[req.action]}\\n\\nFile content:\\n{content}\\n"
        answer, used_model, elapsed = ask_with_fallback(final_prompt, req.model)
        LAST_DEBUG.update({"model": used_model, "elapsed": elapsed, "action": f"file_{req.action}"})
        return {"text": answer, "file": req.file, "action": req.action, "model": used_model}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/api/save-readme")
def save_readme(req: SaveReadmeRequest):
    try:
        root = safe_project_path(req.project)
        readme = root / "README.md"
        readme.write_text(req.content, encoding="utf-8")
        return {"text": f"Saved README.md to {readme}"}
    except Exception as e:
        return {"error": True, "text": str(e)}



@app.get("/api/detect")
def api_detect(project: str = DEFAULT_PROJECT):
    try:
        return detect_project_type(project)
    except Exception as e:
        return {"error": True, "text": str(e)}


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
        return {"error": True, "text": str(e)}


@app.post("/api/create-cpp-project")
def api_create_cpp_project(req: CreateCppProjectRequest):
    try:
        if "/" in req.project or ".." in req.project or not req.project.strip():
            raise ValueError("Invalid project name")

        root = PROJECTS_DIR / req.project
        if root.exists():
            raise ValueError(f"Project already exists: {req.project}")

        (root / "src").mkdir(parents=True)
        (root / "include").mkdir()

        (root / "src" / "main.cpp").write_text(
            '#include <iostream>\\n\\nint main() {\\n    std::cout << "Hello from C++20!\\\\n";\\n    return 0;\\n}\\n',
            encoding="utf-8",
        )

        (root / "CMakeLists.txt").write_text(
            'cmake_minimum_required(VERSION 3.20)\\n'
            f'project({req.project} LANGUAGES CXX)\\n\\n'
            'set(CMAKE_CXX_STANDARD 20)\\n'
            'set(CMAKE_CXX_STANDARD_REQUIRED ON)\\n'
            'set(CMAKE_CXX_EXTENSIONS OFF)\\n\\n'
            'add_executable(${PROJECT_NAME} src/main.cpp)\\n'
            'target_compile_options(${PROJECT_NAME} PRIVATE -Wall -Wextra -pedantic)\\n',
            encoding="utf-8",
        )

        (root / ".gitignore").write_text("build/\\n*.o\\n*.exe\\n*.out\\n.cache/\\n", encoding="utf-8")
        (root / "README.md").write_text(f"# {req.project}\\n\\nC++20 CMake project.\\n", encoding="utf-8")

        subprocess.check_output(["git", "init"], cwd=root, text=True, stderr=subprocess.STDOUT)

        return {"text": f"Created C++ project: {root}\\n\\nNext:\\ncd {root}\\ncmake -S . -B build\\ncmake --build build\\n./build/{req.project}"}
    except Exception as e:
        return {"error": True, "text": str(e)}


@app.post("/ask")
def ask_legacy(req: ChatRequest):
    return api_chat(req)
