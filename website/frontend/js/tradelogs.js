// ============================================================
//  Noctis · Trade Logs (frontend only)
//  Reads tradelogs.txt over the local server, shows newest 50.
//  Log line format:
//  2026-07-06 14:44:29,757 - INFO - message text here
// ============================================================

const LOG_FILE = "../../logs/trading_bot.log";
const MAX_LINES = 50;

let logs = [];               // parsed log objects
let sortKey = "time";        // current sort column
let sortDir = "desc";        // 'asc' | 'desc'

// ---- Parse one line into { time, level, message, raw } ---------
function parseLine(line) {
    // Split on the first two " - " separators: TIMESTAMP - LEVEL - MESSAGE
    const parts = line.split(" - ");
    if (parts.length >= 3) {
        return {
            time: parts[0].trim(),
            level: parts[1].trim(),
            message: parts.slice(2).join(" - ").trim(), // message may contain " - "
            raw: line,
        };
    }
    // Fallback: line doesn't match expected format
    return { time: "", level: "", message: line.trim(), raw: line };
}

// ---- Load the file ---------------------------------------------
async function loadLogs() {
    const countEl = document.getElementById("logs-count");
    try {
        const res = await fetch(LOG_FILE, { cache: "no-store" });
        if (!res.ok) throw new Error(res.status);
        const text = await res.text();

        const lines = text
            .split("\n")
            .map(l => l.trim())
            .filter(l => l.length > 0);

        // newest lines are at the bottom of a log file -> take last N, reverse
        const recent = lines.slice(-MAX_LINES).reverse();
        logs = recent.map(parseLine);

        countEl.textContent = `Showing ${logs.length} most recent entries`;
        renderTable();
    } catch (err) {
        logs = [];
        countEl.textContent = "";
        document.getElementById("logs-body").innerHTML =
            `<tr><td colspan="3" class="logs-empty">
                Could not load ${LOG_FILE}. Make sure the file is in the project
                folder and you're viewing this over a local server (not file://).
            </td></tr>`;
    }
}

// ---- Render the table ------------------------------------------
function renderTable() {
    const body = document.getElementById("logs-body");

    if (logs.length === 0) {
        body.innerHTML = `<tr><td colspan="3" class="logs-empty">No log entries found.</td></tr>`;
        return;
    }

    const sorted = [...logs].sort((a, b) => {
        const av = a[sortKey].toLowerCase();
        const bv = b[sortKey].toLowerCase();
        if (av < bv) return sortDir === "asc" ? -1 : 1;
        if (av > bv) return sortDir === "asc" ? 1 : -1;
        return 0;
    });

    body.innerHTML = sorted.map(log => {
        const levelClass = (log.level || "debug").toLowerCase();
        return `
            <tr>
                <td class="col-time">${escapeHtml(log.time)}</td>
                <td class="col-level"><span class="badge ${levelClass}">${escapeHtml(log.level || "—")}</span></td>
                <td class="col-message">${escapeHtml(log.message)}</td>
            </tr>`;
    }).join("");

    updateSortArrows();
}

// ---- Sorting ---------------------------------------------------
function setupSorting() {
    document.querySelectorAll("th[data-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const key = th.dataset.sort;
            if (sortKey === key) {
                sortDir = sortDir === "asc" ? "desc" : "asc";
            } else {
                sortKey = key;
                sortDir = "desc";
            }
            renderTable();
        });
    });
}

function updateSortArrows() {
    document.querySelectorAll("th[data-sort]").forEach(th => {
        const arrow = th.querySelector(".arrow");
        if (th.dataset.sort === sortKey) {
            arrow.textContent = sortDir === "asc" ? "↑" : "↓";
            arrow.style.opacity = "1";
        } else {
            arrow.textContent = "";
        }
    });
}

// ---- Escape HTML so log text can't break the page --------------
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// ---- Init ------------------------------------------------------
document.getElementById("refresh-btn").addEventListener("click", loadLogs);
setupSorting();
loadLogs();