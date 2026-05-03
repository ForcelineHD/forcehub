async function apiGet(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[c]));
}

function jsArg(s) {
  return String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

async function loadModels() {
  const out = document.getElementById("modelsOutput");
  out.textContent = "Loading...";
  try {
    const data = await apiGet("/api/models");
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
}

async function loadFiles(path = ".") {
  const out = document.getElementById("filesOutput");
  out.textContent = "Loading...";

  try {
    const data = await apiGet("/api/files?path=" + encodeURIComponent(path));

    if (data.type === "file") {
      out.innerHTML =
        "<strong>" + escapeHtml(data.path) + "</strong>\n\n" +
        "<pre>" + escapeHtml(data.content) + "</pre>";
      return;
    }

    let html = "<strong>Directory: " + escapeHtml(data.path) + "</strong><br><br>";

    if (data.path !== ".") {
      const parent = data.path.split("/").slice(0, -1).join("/") || ".";
      html += "<button onclick=\"loadFiles('" + jsArg(parent) + "')\">..</button><br>";
    }

    for (const item of data.items) {
      const icon = item.type === "dir" ? "[DIR]" : "[FILE]";
      html += "<button onclick=\"loadFiles('" + jsArg(item.path) + "')\">" +
        icon + " " + escapeHtml(item.name) +
        "</button><br>";
    }

    out.innerHTML = html;
  } catch (e) {
    out.textContent = e.message;
  }
}

async function sendChat() {
  const out = document.getElementById("chatOutput");
  const prompt = document.getElementById("prompt").value.trim();

  if (!prompt) {
    out.textContent = "Type a prompt first.";
    return;
  }

  out.textContent = "Thinking...";
  try {
    const data = await apiPost("/api/chat", {
      model: "qwen2.5-coder:1.5b",
      prompt: "You are ForceHub, a local AI coding assistant. Only answer about this project, code, files, Linux, Git, C++, PHP, JavaScript, FastAPI, Ollama, and development tasks. If the question asks about public facts, companies, news, countries, products, or anything requiring internet knowledge, say: 'I am a local coding assistant and I should not answer that without web search.'\\n\\nUser request:\\n" + prompt,
      stream: false
    });
    out.textContent = data.response || JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("loadModels").addEventListener("click", loadModels);
  document.getElementById("loadFiles").addEventListener("click", () => loadFiles("."));
  document.getElementById("sendChat").addEventListener("click", sendChat);
});
