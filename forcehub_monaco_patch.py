#!/usr/bin/env python3
"""
ForceHub Monaco Editor Patch
Safely replaces textarea editor with Monaco editor.

Fixes:
  - Moves editor OUT of #chat div (fixed panel, not scroll content)
  - Removes broken editor=getElementById ref from const chain
  - Updates viewFile / previewDiff / saveFile / clearChat
  - Adds Monaco loader, init, setEditorContent, saveFromMonaco
  - Adds editor panel toolbar (Save / Diff / Close)

Run from: ~/projects/forcehub/
"""

import sys
import shutil
from pathlib import Path
from datetime import datetime

TARGET = Path("app/main.py")
BACKUP = Path(f"app/main.py.monaco-bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

if not TARGET.exists():
    print("ERROR: app/main.py not found. Run from ~/projects/forcehub/")
    sys.exit(1)

original = TARGET.read_text(encoding="utf-8")
patched = original
patches = []

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 1: Remove textarea from inside #chat div
#          (Monaco needs a fixed-height container, not a scrolling chat item)
# ──────────────────────────────────────────────────────────────────────────────
OLD1 = (
    '<div id="chat" class="chat">\n'
    '<div class="msg ai">Ready. Streaming is enabled. Use the editor for safe file changes.</div>\n'
    '<textarea id="editor" class="editor" placeholder="File content appears here after View file..."></textarea>\n'
    '</div>'
)
NEW1 = (
    '<div id="chat" class="chat">\n'
    '<div class="msg ai">Ready. Streaming is enabled. Use the editor for safe file changes.</div>\n'
    '</div>'
)
patches.append(("Remove textarea from #chat div", OLD1, NEW1))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 2: Add Monaco editor panel above #agent-panel
#          Fixed-height panel with toolbar: filename | Save | Diff | Close
# ──────────────────────────────────────────────────────────────────────────────
OLD2 = '<div id="agent-panel"'
NEW2 = (
    '<div id="editor-panel" style="display:none;border-top:1px solid var(--border);background:#0b0d12;flex-shrink:0">\n'
    '  <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 14px;border-bottom:1px solid var(--border)">\n'
    '    <span id="editor-filename" style="font-size:12px;color:var(--muted);font-family:Consolas,monospace">No file loaded</span>\n'
    '    <div style="display:flex;gap:6px">\n'
    '      <button onclick="saveFromMonaco()" style="font-size:11px;padding:3px 10px;border-radius:6px;border:0;background:#26385f;color:#fff;cursor:pointer">Save</button>\n'
    '      <button onclick="diffFromMonaco()" style="font-size:11px;padding:3px 10px;border-radius:6px;border:0;background:#2a3040;color:#fff;cursor:pointer">Diff</button>\n'
    '      <button onclick="document.getElementById(\'editor-panel\').style.display=\'none\'" style="font-size:14px;padding:2px 8px;border-radius:6px;border:0;background:none;color:var(--muted);cursor:pointer">&#x2715;</button>\n'
    '    </div>\n'
    '  </div>\n'
    '  <div id="monaco-container" style="height:320px"></div>\n'
    '</div>\n'
    '<div id="agent-panel"'
)
patches.append(("Add Monaco editor panel above agent-panel", OLD2, NEW2))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 3: Remove `editor=document.getElementById("editor")` from JS const chain
#          Keeping it would set editor=null (div gone), breaking clearChat
# ──────────────────────────────────────────────────────────────────────────────
OLD3 = (
    ',fileSelect=document.getElementById("file")'
    ',searchBox=document.getElementById("search")'
    ',editor=document.getElementById("editor");'
)
NEW3 = (
    ',fileSelect=document.getElementById("file")'
    ',searchBox=document.getElementById("search");'
)
patches.append(("Remove editor from JS const chain", OLD3, NEW3))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 4: Update viewFile() — set Monaco content, show editor panel
# ──────────────────────────────────────────────────────────────────────────────
OLD4 = (
    'async function viewFile()'
    '{const res=await fetch("/api/file-content?project="+encodeURIComponent(projectSelect.value)+"&file="+encodeURIComponent(fileSelect.value));'
    'const data=await res.json();'
    'editor.value=data.content||"";'
    'addMessage("Loaded file: "+fileSelect.value,"ai")}'
)
NEW4 = (
    'async function viewFile(){\n'
    '  const fname=fileSelect.value;\n'
    '  const res=await fetch("/api/file-content?project="+encodeURIComponent(projectSelect.value)+"&file="+encodeURIComponent(fname));\n'
    '  const data=await res.json();\n'
    '  setEditorContent(data.content||"", fname);\n'
    '  document.getElementById("editor-panel").style.display="block";\n'
    '  document.getElementById("editor-filename").textContent=fname;\n'
    '  addMessage("Loaded: "+fname,"ai");\n'
    '}'
)
patches.append(("Update viewFile() for Monaco", OLD4, NEW4))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 5: Update previewDiff() — read from monacoEditor.getValue()
# ──────────────────────────────────────────────────────────────────────────────
OLD5 = (
    'async function previewDiff()'
    '{const res=await fetch("/api/diff-content",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content:editor.value})});'
    'const data=await res.json();addMessage(data.text||data.error||"No diff",data.error?"ai error":"ai")}'
)
NEW5 = (
    'async function previewDiff(){\n'
    '  const content=monacoEditor?monacoEditor.getValue():"";\n'
    '  const res=await fetch("/api/diff-content",{method:"POST",headers:{"Content-Type":"application/json"},\n'
    '    body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content})});\n'
    '  const data=await res.json();\n'
    '  addMessage(data.text||data.error||"No diff",data.error?"ai error":"ai");\n'
    '}'
)
patches.append(("Update previewDiff() for Monaco", OLD5, NEW5))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 6: Update saveFile() — read from monacoEditor.getValue()
# ──────────────────────────────────────────────────────────────────────────────
OLD6 = (
    'async function saveFile()'
    '{if(!confirm("Save file with timestamped .bak backup?"))return;'
    'const res=await fetch("/api/save-file",{method:"POST",headers:{"Content-Type":"application/json"},'
    'body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content:editor.value,backup:true})});'
    'const data=await res.json();addMessage(data.text||data.error||"Saved",data.error?"ai error":"ai")}'
)
NEW6 = (
    'async function saveFile(){\n'
    '  if(!confirm("Save file with timestamped .bak backup?"))return;\n'
    '  const content=monacoEditor?monacoEditor.getValue():"";\n'
    '  const res=await fetch("/api/save-file",{method:"POST",headers:{"Content-Type":"application/json"},\n'
    '    body:JSON.stringify({project:projectSelect.value,file:fileSelect.value,content,backup:true})});\n'
    '  const data=await res.json();\n'
    '  addMessage(data.text||data.error||"Saved",data.error?"ai error":"ai");\n'
    '}'
)
patches.append(("Update saveFile() for Monaco", OLD6, NEW6))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 7: Update clearChat() — remove broken chat.appendChild(editor) + editor.value=""
# ──────────────────────────────────────────────────────────────────────────────
OLD7 = (
    'async function clearChat()'
    '{await fetch("/api/reset",{method:"POST"});'
    'chat.innerHTML="";'
    'chat.appendChild(editor);'
    'editor.value="";'
    'addMessage("Memory cleared.","ai")}'
)
NEW7 = (
    'async function clearChat(){\n'
    '  await fetch("/api/reset",{method:"POST"});\n'
    '  chat.innerHTML="";\n'
    '  if(monacoEditor) monacoEditor.setValue("");\n'
    '  document.getElementById("editor-filename").textContent="No file loaded";\n'
    '  addMessage("Memory cleared.","ai");\n'
    '}'
)
patches.append(("Update clearChat() for Monaco", OLD7, NEW7))

# ──────────────────────────────────────────────────────────────────────────────
# PATCH 8: Add Monaco loader + init + helpers before </body>
# ──────────────────────────────────────────────────────────────────────────────
OLD8 = '</body>\n</html>\n'
NEW8 = (
    '<script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs/loader.js"></script>\n'
    '<script>\n'
    'let monacoEditor = null;\n'
    '\n'
    'require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs" } });\n'
    'require(["vs/editor/editor.main"], function () {\n'
    '  monacoEditor = monaco.editor.create(document.getElementById("monaco-container"), {\n'
    '    value: "",\n'
    '    language: "python",\n'
    '    theme: "vs-dark",\n'
    '    automaticLayout: true,\n'
    '    minimap: { enabled: false },\n'
    '    fontSize: 13,\n'
    '    scrollBeyondLastLine: false,\n'
    '    wordWrap: "off",\n'
    '    renderLineHighlight: "line",\n'
    '    lineNumbers: "on",\n'
    '    folding: true,\n'
    '    readOnly: false,\n'
    '  });\n'
    '});\n'
    '\n'
    'function setEditorContent(content, filename) {\n'
    '  if (!monacoEditor) { setTimeout(() => setEditorContent(content, filename), 200); return; }\n'
    '  monacoEditor.setValue(content || "");\n'
    '  monacoEditor.setScrollPosition({ scrollTop: 0 });\n'
    '  const ext = (filename || "").split(".").pop().toLowerCase();\n'
    '  const langMap = {\n'
    '    py:"python", js:"javascript", ts:"typescript", tsx:"typescript",\n'
    '    json:"json", md:"markdown", html:"html", css:"css",\n'
    '    cpp:"cpp", cc:"cpp", cxx:"cpp", h:"cpp", hpp:"cpp",\n'
    '    c:"c", sh:"shell", bash:"shell", yaml:"yaml", yml:"yaml",\n'
    '    toml:"ini", txt:"plaintext",\n'
    '  };\n'
    '  monaco.editor.setModelLanguage(monacoEditor.getModel(), langMap[ext] || "plaintext");\n'
    '}\n'
    '\n'
    'async function saveFromMonaco() {\n'
    '  if (!monacoEditor) return;\n'
    '  if (!confirm("Save file with timestamped .bak backup?")) return;\n'
    '  const fname = document.getElementById("editor-filename").textContent;\n'
    '  if (!fname || fname === "No file loaded") { addMessage("No file loaded in editor.", "ai error"); return; }\n'
    '  const content = monacoEditor.getValue();\n'
    '  const res = await fetch("/api/save-file", {\n'
    '    method: "POST", headers: { "Content-Type": "application/json" },\n'
    '    body: JSON.stringify({ project: projectSelect.value, file: fname, content, backup: true })\n'
    '  });\n'
    '  const data = await res.json();\n'
    '  addMessage(data.text || data.error || "Saved", data.error ? "ai error" : "ai");\n'
    '}\n'
    '\n'
    'async function diffFromMonaco() {\n'
    '  if (!monacoEditor) return;\n'
    '  const fname = document.getElementById("editor-filename").textContent;\n'
    '  if (!fname || fname === "No file loaded") { addMessage("No file loaded in editor.", "ai error"); return; }\n'
    '  const content = monacoEditor.getValue();\n'
    '  const res = await fetch("/api/diff-content", {\n'
    '    method: "POST", headers: { "Content-Type": "application/json" },\n'
    '    body: JSON.stringify({ project: projectSelect.value, file: fname, content })\n'
    '  });\n'
    '  const data = await res.json();\n'
    '  addMessage(data.text || data.error || "No diff", data.error ? "ai error" : "ai");\n'
    '}\n'
    '</script>\n'
    '</body>\n'
    '</html>\n'
)
patches.append(("Add Monaco loader + init + helpers before </body>", OLD8, NEW8))

# ──────────────────────────────────────────────────────────────────────────────
# Apply patches
# ──────────────────────────────────────────────────────────────────────────────
print(f"\nForceHub Monaco Editor Patcher")
print(f"Target : {TARGET}")
print(f"Backup : {BACKUP}\n")

errors = []
for name, old, new in patches:
    count = patched.count(old)
    if count == 0:
        errors.append(f"  FAIL [{name}]: pattern not found — already patched or file differs")
    elif count > 1:
        errors.append(f"  FAIL [{name}]: pattern matched {count} times — ambiguous, skipping")
    else:
        patched = patched.replace(old, new)
        print(f"  OK   [{name}]")

if errors:
    print("\nPATCH ERRORS — nothing written:")
    for e in errors:
        print(e)
    sys.exit(1)

shutil.copy2(TARGET, BACKUP)
TARGET.write_text(patched, encoding="utf-8")

print(f"\nAll {len(patches)} patches applied.")
print(f"Backup : {BACKUP}")
print("\nVerify:")
print("  python -m py_compile app/main.py && echo SYNTAX OK")
print("  uvicorn app.main:app --reload --host 127.0.0.1 --port 8000")
