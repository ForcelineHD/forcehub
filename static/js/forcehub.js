console.log("ForceHub JS loaded");

async function forcehubGet(url) {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error(`GET ${url} failed: ${res.status}`);
  return await res.json();
}

async function forcehubPost(url) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include"
  });
  if (!res.ok) throw new Error(`POST ${url} failed: ${res.status}`);
  return await res.json();
}

async function refreshAgentStatus() {
  try {
    const data = await forcehubGet("/api/agent/status");
    console.log("Agent status:", data);
  } catch (err) {
    console.error("Agent status failed:", err);
  }
}

setInterval(refreshAgentStatus, 3000);
refreshAgentStatus();
