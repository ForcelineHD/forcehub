async function apiGet(url) {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

document.getElementById("loadModels").onclick = async () => {
  const out = document.getElementById("modelsOutput");
  out.textContent = "Loading...";
  try {
    const data = await apiGet("/api/models.php");
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
};

document.getElementById("sendChat").onclick = async () => {
  const out = document.getElementById("chatOutput");
  const prompt = document.getElementById("prompt").value.trim();

  if (!prompt) {
    out.textContent = "Type a prompt first.";
    return;
  }

  out.textContent = "Thinking...";
  try {
    const data = await apiPost("/api/chat.php", {
      prompt,
      model: "qwen2.5-coder:1.5b"
    });
    out.textContent = data.response || JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
};

document.getElementById("loadFiles").onclick = async () => {
  const out = document.getElementById("filesOutput");
  out.textContent = "Loading...";
  try {
    const data = await apiGet("/api/files.php?path=.");
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
};
