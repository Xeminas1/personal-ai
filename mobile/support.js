const statusLabel = document.getElementById("status");
const keyArea = document.getElementById("keyArea");
const keyInput = document.getElementById("key");
const enableButton = document.getElementById("enable");
const disableButton = document.getElementById("disable");

async function call(path, method = "GET") {
  const response = await fetch(`/api/support/${path}`, {
    method, headers: {"Content-Type": "application/json"},
    ...(method === "POST" ? {body: "{}"} : {}),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || "Request failed");
  return data;
}

function render(data) {
  statusLabel.textContent = data.enabled
    ? `Read-only access is enabled until ${new Date(data.expires_at).toLocaleString()}.`
    : "Read-only access is off.";
  disableButton.disabled = !data.enabled;
  if (data.endpoints) {
    document.getElementById("endpoints").textContent = data.endpoints.length
      ? `Private support address: ${data.endpoints.join(" or ")}`
      : "No private Tailscale support route was found on this installation.";
  }
}

async function changeAccess(action) {
  enableButton.disabled = disableButton.disabled = true;
  keyInput.value = "";
  keyArea.hidden = true;
  try {
    const data = await call(action, "POST");
    render(data);
    if (data.token) { keyInput.value = data.token; keyArea.hidden = false; }
  } catch (error) { statusLabel.textContent = error.message; }
  finally { enableButton.disabled = false; }
}

enableButton.addEventListener("click", () => changeAccess("enable"));
disableButton.addEventListener("click", () => changeAccess("disable"));
document.getElementById("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(keyInput.value); }
  catch { keyInput.type = "text"; keyInput.select(); }
});
window.addEventListener("pagehide", () => { keyInput.value = ""; });
call("settings").then(render).catch(error => { statusLabel.textContent = error.message; });
