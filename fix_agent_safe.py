from pathlib import Path
from datetime import datetime
import shutil
import re
import sys

TARGET = Path("app/main.py")
BACKUP = Path(f"app/main.py.agent-fix-bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

text = TARGET.read_text(encoding="utf-8")
original = text

shutil.copy2(TARGET, BACKUP)

# 1. imports
if "import threading" not in text:
    text = text.replace("import time", "import threading\nimport time")

# 2. globals after LAST_DEBUG, supports both styles
if "AGENT_STATE" not in text:
    text = re.sub(
        r"LAST_DEBUG(?::[^\n=]+)?\s*=\s*\{\}",
        '''LAST_DEBUG = {}

AGENT_STATE = {
    "running": False,
    "step": "idle",
    "logs": [],
    "project": "",
    "model": "",
}
AGENT_THREAD = None''',
        text,
        count=1,
    )

# 3. fix bad escape if present
text = text.replace(
    r"files=$(find . -type f \( -name '*.cpp' -o -name '*.cc' -o -name '*.cxx' \) | head -20)",
    r"files=$(find . -type f \\( -name '*.cpp' -o -name '*.cc' -o -name '*.cxx' \\) | head -20)",
)

# 4. add sidebar agent panel if missing
if 'id="agent-meta"' not in text:
    text = text.replace(
        '<label>Search</label>',
        '''
<h3>Agent Mode</h3>
<button class="secondary" onclick="startAgent()">Start Agent</button>
<button class="secondary" onclick="stopAgent()">Stop Agent</button>
<button class="secondary" onclick="refreshAgent()">Refresh Agent</button>
<div id="agent-meta" class="small">idle</div>
<br>

<label>Search</label>''',
        1,
    )

# 5. add log panel above inputbar if missing
if 'id="agent-log"' not in text:
    text = text.replace(
        '<div class="inputbar">',
        '''
<div id="agent-panel" style="display:none;background:#0b0d12;padding:10px 16px;border-top:1px solid #252b3a">
  <div class="small">Agent Log <button onclick="document.getElementById('agent-panel').style.display='none'">x</button></div>
  <pre id="agent-log" style="max-height:220px;overflow:auto;white-space:pre-wrap"></pre>
</div>

<div class="inputbar">''',
        1,
    )

# 6. backend functions/endpoints
if '@app.post("/api/agent/start")' not in text:
    block = r'''

def agent_log(msg: str):
    AGENT_STATE["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    AGENT_STATE["logs"] = AGENT_STATE["logs"][-300:]


def run_agent(project: str = DEFAULT_PROJECT, model: str = "auto"):
    global AGENT_STATE
    try:
        AGENT_STATE.update({
            "running": True,
            "step": "starting",
            "logs": [],
            "project": project,
            "model": model,
        })

        agent_log("Agent started")
        AGENT_STATE["step"] = "reading project"
        context = build_project_context(project)
        agent_log(f"Loaded project context: {len(context)} chars")

        AGENT_STATE["step"] = "analyzing"
        analysis, used_model, elapsed = ask_with_fallback(
            f"Analyze this project and list practical issues:\n\n{context}",
            model,
        )
        agent_log(f"Analysis done using {used_model} in {elapsed}s")

        AGENT_STATE["step"] = "writing report"
        root = safe_project_path(project)
        report = root / "data" / "agent_report.md"
        report.parent.mkdir(exist_ok=True)
        report.write_text(
            f"# Agent Report\n\nProject: {project}\n\nModel: {used_model}\n\n{analysis}\n",
            encoding="utf-8",
        )
        agent_log(f"Wrote report: {report}")

        AGENT_STATE["step"] = "done"
        agent_log("Agent finished")

    except Exception as e:
        AGENT_STATE["step"] = "error"
        agent_log(f"ERROR: {e}")
    finally:
        AGENT_STATE["running"] = False


@app.post("/api/agent/start")
def api_agent_start(project: str = DEFAULT_PROJECT, model: str = "auto"):
    global AGENT_THREAD

    if AGENT_STATE["running"]:
        return {"error": True, "text": "Agent already running"}

    AGENT_THREAD = threading.Thread(target=run_agent, args=(project, model), daemon=True)
    AGENT_THREAD.start()
    return {"status": "started", "project": project, "model": model}


@app.post("/api/agent/stop")
def api_agent_stop():
    AGENT_STATE["running"] = False
    AGENT_STATE["step"] = "stopped"
    agent_log("Stop requested")
    return {"text": "stop requested"}


@app.get("/api/agent/status")
def api_agent_status():
    return AGENT_STATE
'''
    text = text.replace('\n@app.post("/ask")', block + '\n\n@app.post("/ask")')

# 7. frontend JS
if "async function startAgent()" not in text:
    js = r'''
async function startAgent(){
  const project = projectSelect.value || "forcehub";
  const model = modelSelect.value || "auto";
  document.getElementById("agent-panel").style.display = "block";
  const r = await fetch("/api/agent/start?project=" + encodeURIComponent(project) + "&model=" + encodeURIComponent(model), {method:"POST"});
  const j = await r.json();
  document.getElementById("agent-meta").textContent = j.status || j.text || j.error || JSON.stringify(j);
  await refreshAgent();
}

async function stopAgent(){
  const r = await fetch("/api/agent/stop", {method:"POST"});
  const j = await r.json();
  document.getElementById("agent-meta").textContent = j.text || JSON.stringify(j);
  await refreshAgent();
}

async function refreshAgent(){
  const r = await fetch("/api/agent/status");
  const j = await r.json();
  document.getElementById("agent-meta").textContent =
    (j.running ? "🟢 " : "⚪ ") + "step=" + j.step + " | project=" + j.project + " | model=" + j.model;

  const logEl = document.getElementById("agent-log");
  logEl.textContent = (j.logs || []).join("\\n");
  logEl.scrollTop = logEl.scrollHeight;

  if ((j.logs || []).length > 0) {
    document.getElementById("agent-panel").style.display = "block";
  }
}

setInterval(() => {
  refreshAgent().catch(() => {});
}, 2000);
'''
    text = text.replace("async function clearChat()", js + "\n\nasync function clearChat()", 1)

TARGET.write_text(text, encoding="utf-8")
print(f"Patched. Backup: {BACKUP}")
