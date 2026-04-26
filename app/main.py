from pathlib import Path
from typing import Literal

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

APP_NAME = "forcehub"
APP_VERSION = "0.3.0"
PROJECTS_DIR = "/home/flozi/projects"
OLLAMA_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

app = FastAPI(
    title="ForceHub",
    description="Local dashboard for ForceHub projects and AI tools.",
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


def build_prompt(user_prompt: str, mode: str) -> str:
    system = {
        "normal": "You are ForceHub AI. Answer clearly and practically.",
        "code": "You are ForceHub AI coding assistant. Give direct code-first answers.",
        "short": "Answer briefly and directly. No padding.",
        "explain": "Explain clearly step by step, but avoid unnecessary basics.",
    }.get(mode, "You are ForceHub AI. Answer clearly.")

    history = ""
    for item in CHAT_HISTORY[-8:]:
        history += f"{item['role']}: {item['content']}\n"

    return f"{system}\n\nConversation:\n{history}\nuser: {user_prompt}\nassistant:"


@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!doctype html>
<html>
<head>
<title>ForceHub AI Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --bg:#0f1117;
  --panel:#151924;
  --panel2:#111521;
  --border:#252b3a;
  --text:#e6e6e6;
  --muted:#8d96aa;
  --blue:#4f7cff;
  --user:#1f3a5f;
  --ai:#1d2230;
}
*{box-sizing:border-box}
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text)}
.layout{display:grid;grid-template-columns:270px 1fr;height:100vh}
.sidebar{background:var(--panel);border-right:1px solid var(--border);padding:18px}
.sidebar h2{margin:0 0 8px;color:#8ab4ff}
.small{color:var(--muted);font-size:13px}
.sidebar a{color:#b7c7ff;display:block;margin:10px 0;text-decoration:none}
.control{margin-top:16px}
label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}
select,button,textarea{font-family:inherit}
select{
  width:100%;background:#0f1117;color:var(--text);
  border:1px solid #30384d;border-radius:8px;padding:8px;
}
.main{display:flex;flex-direction:column;height:100vh}
.header{padding:14px 22px;border-bottom:1px solid var(--border);background:var(--panel2);display:flex;justify-content:space-between;align-items:center}
.header h2{margin:0}
.chat{flex:1;overflow-y:auto;padding:22px}
.msg{max-width:900px;padding:14px 16px;margin-bottom:14px;border-radius:12px;white-space:pre-wrap;line-height:1.48;font-size:14px}
.user{background:var(--user);margin-left:auto}
.ai{background:var(--ai);border:1px solid #2b3245}
.error{background:#3a1d24;border:1px solid #6d2b39}
.inputbar{display:flex;gap:10px;padding:16px;border-top:1px solid var(--border);background:var(--panel2)}
textarea{flex:1;resize:none;height:60px;border-radius:10px;border:1px solid #30384d;background:#0f1117;color:#eee;padding:12px;font-size:15px}
button{border:0;border-radius:10px;background:var(--blue);color:white;font-weight:bold;cursor:pointer;padding:0 16px}
button:disabled{background:#3a3f50;cursor:wait}
.secondary{background:#2a3040;width:100%;padding:10px;margin-top:10px}
.badge{font-size:12px;color:#b7c7ff}
pre{background:#0b0d12;border:1px solid #2b3245;padding:12px;border-radius:8px;overflow:auto}
code{font-family:Consolas,monospace}
</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <h2>ForceHub</h2>
    <div class="small">AI Pro Dashboard</div>
    <hr style="border-color:#252b3a">

    <a href="/status">Status API</a>
    <a href="/projects">Projects API</a>
    <a href="/docs">API Docs</a>

    <div class="control">
      <label>Model</label>
      <select id="model"></select>
    </div>

    <div class="control">
      <label>Mode</label>
      <select id="mode">
        <option value="normal">Normal</option>
        <option value="code">Code Assistant</option>
        <option value="short">Short Answers</option>
        <option value="explain">Explain Step-by-Step</option>
      </select>
    </div>

    <button class="secondary" onclick="clearChat()">Clear Memory</button>

    <div class="control small">
      Backend: Ollama<br>
      Endpoint: /api/chat<br>
      Version: 0.3.0
    </div>
  </aside>

  <main class="main">
    <div class="header">
      <div>
        <h2>ForceHub Chat Pro</h2>
        <div class="small">FastAPI → Ollama direct backend</div>
      </div>
      <div id="state" class="badge">Ready</div>
    </div>

    <div id="chat" class="chat">
      <div class="msg ai">Ready. Ask me about code, Linux, networking, FastAPI, or your projects.</div>
    </div>

    <div class="inputbar">
      <textarea id="prompt" placeholder="Type your message... Enter = send, Shift+Enter = newline"></textarea>
      <button id="send" onclick="sendMessage()">Send</button>
    </div>
  </main>
</div>

<script>
const chat = document.getElementById("chat");
const promptBox = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const state = document.getElementById("state");
const modelSelect = document.getElementById("model");
const modeSelect = document.getElementById("mode");

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function loadModels() {
  try {
    const res = await fetch("/api/models");
    const data = await res.json();
    modelSelect.innerHTML = "";
    for (const model of data.models) {
      const opt = document.createElement("option");
      opt.value = model;
      opt.textContent = model;
      modelSelect.appendChild(opt);
    }
    if (data.models.includes("qwen2.5-coder:7b")) {
      modelSelect.value = "qwen2.5-coder:7b";
    }
  } catch {
    modelSelect.innerHTML = '<option value="qwen2.5-coder:7b">qwen2.5-coder:7b</option>';
  }
}

async function sendMessage() {
  const prompt = promptBox.value.trim();
  if (!prompt) return;

  addMessage(prompt, "user");
  promptBox.value = "";
  sendBtn.disabled = true;
  sendBtn.textContent = "Thinking";
  state.textContent = "Thinking...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        prompt,
        model: modelSelect.value,
        mode: modeSelect.value
      })
    });

    const data = await res.json();
    if (!res.ok || data.error) {
      addMessage(data.text || data.error || "Unknown error", "ai error");
    } else {
      addMessage(data.text || "No response", "ai");
    }
  } catch (err) {
    addMessage("Request error: " + err, "ai error");
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send";
    state.textContent = "Ready";
    promptBox.focus();
  }
}

async function clearChat() {
  await fetch("/api/reset", {method:"POST"});
  chat.innerHTML = "";
  addMessage("Memory cleared.", "ai");
}

promptBox.addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

loadModels();
</script>
</body>
</html>
"""


@app.get("/status", response_model=StatusResponse)
def status():
    return StatusResponse(status="ok", app=APP_NAME, version=APP_VERSION)


@app.get("/projects")
def list_projects():
    base = Path(PROJECTS_DIR)
    return {"projects": [p.name for p in base.iterdir() if p.is_dir()]}


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
    prompt = build_prompt(req.prompt, req.mode)

    try:
        r = requests.post(
            OLLAMA_GENERATE_URL,
            json={
                "model": req.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "num_ctx": 4096,
                },
            },
            timeout=240,
        )

        if r.status_code != 200:
            return {"error": True, "text": f"Ollama error {r.status_code}: {r.text}"}

        data = r.json()
        answer = data.get("response", "").strip()

        CHAT_HISTORY.append({"role": "user", "content": req.prompt})
        CHAT_HISTORY.append({"role": "assistant", "content": answer})

        return {
            "text": answer or "No response",
            "model": req.model,
            "mode": req.mode,
        }

    except requests.exceptions.ConnectionError:
        return {
            "error": True,
            "text": "Ollama is not running. Start it with: ollama serve",
        }

    except requests.exceptions.Timeout:
        return {
            "error": True,
            "text": "Model timed out. Use qwen2.5-coder:1.5b or wait longer.",
        }

    except Exception as e:
        return {
            "error": True,
            "text": f"Server error: {e}",
        }


@app.post("/ask")
def ask_legacy(req: ChatRequest):
    return api_chat(req)
