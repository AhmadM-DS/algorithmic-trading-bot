const STATUS_POLL_MS = 30000;
const STATUS_CLASS = { green: "good", yellow: "idle", red: "bad" };

function applyStatus(key, level) {
    const el = document.querySelector(`.dot[data-status="${key}"]`);
    if (!el) return;
    el.classList.remove("good", "idle", "bad");
    el.classList.add(STATUS_CLASS[level] || "bad");
}

async function refreshStatus() {
    try {
        const res = await fetch("/api/status", { cache: "no-store" });
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const data = await res.json();
        applyStatus("bot", data.bot);
        applyStatus("server", data.server);
        applyStatus("webHost", data.webHost);
    } catch (err) {
        console.error("Failed to load status:", err);
        applyStatus("bot", "red");
        applyStatus("server", "red");
        applyStatus("webHost", "red");
    }
}

refreshStatus();
setInterval(refreshStatus, STATUS_POLL_MS);
