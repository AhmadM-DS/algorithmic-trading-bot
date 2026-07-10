let logs = [];
let sortKey = "time";
let sortDir = "desc";


async function loadLogs() {
    const countEl = document.getElementById("logs-count");
    try {
        const res = await fetch("/api/tradelogs", { cache: "no-store" });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();

        logs = data.logs;
        countEl.textContent = `Showing ${logs.length} most recent entries`;
        renderTable();
    } catch (err) {
        logs = [];
        countEl.textContent = "";
        document.getElementById("logs-body").innerHTML =
            `<tr><td colspan="3" class="logs-empty">Could not load trade logs.</td></tr>`;
    }
}

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

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

document.getElementById("refresh-btn").addEventListener("click", loadLogs);
setupSorting();
loadLogs();