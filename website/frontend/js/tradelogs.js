let logs = [];
let sortKey = "time";
let sortDir = "desc";
let currentPage = 1;
const PAGE_SIZE = 30;
let selectedDate = todayISO();

function todayISO() {
    const d = new Date();
    const tz = d.getTimezoneOffset() * 60000;
    return new Date(d - tz).toISOString().slice(0, 10);
}

async function loadLogs(date = selectedDate) {
    selectedDate = date;
    const countEl = document.getElementById("logs-count");
    countEl.textContent = "Loading…";
    try {
        const res = await fetch(`/api/tradelogs?date=${encodeURIComponent(date)}`, { cache: "no-store" });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();

        logs = data.logs;
        currentPage = 1;
        renderTable();
    } catch (err) {
        logs = [];
        countEl.textContent = "";
        document.getElementById("logs-body").innerHTML =
            `<tr><td colspan="3" class="logs-empty">Could not load trade logs.</td></tr>`;
        updatePagination(0);
    }
}

function renderTable() {
    const body = document.getElementById("logs-body");
    const countEl = document.getElementById("logs-count");

    if (logs.length === 0) {
        body.innerHTML = `<tr><td colspan="3" class="logs-empty">No log entries found for this date.</td></tr>`;
        countEl.textContent = "No entries";
        updatePagination(0);
        return;
    }

    const sorted = [...logs].sort((a, b) => {
        const av = a[sortKey].toLowerCase();
        const bv = b[sortKey].toLowerCase();
        if (av < bv) return sortDir === "asc" ? -1 : 1;
        if (av > bv) return sortDir === "asc" ? 1 : -1;
        return 0;
    });

    const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    currentPage = Math.min(currentPage, totalPages);
    const start = (currentPage - 1) * PAGE_SIZE;
    const pageItems = sorted.slice(start, start + PAGE_SIZE);

    countEl.textContent = `Showing ${start + 1}–${start + pageItems.length} of ${sorted.length} entries`;

    body.innerHTML = pageItems.map(log => {
        const levelClass = (log.level || "debug").toLowerCase();
        return `
            <tr>
                <td class="col-time">${escapeHtml(log.time)}</td>
                <td class="col-level"><span class="badge ${levelClass}">${escapeHtml(log.level || "—")}</span></td>
                <td class="col-message">${escapeHtml(log.message)}</td>
            </tr>`;
    }).join("");

    updateSortArrows();
    updatePagination(totalPages);
}

function updatePagination(totalPages) {
    const info = document.getElementById("page-info");
    const prevBtn = document.getElementById("prev-page");
    const nextBtn = document.getElementById("next-page");

    if (totalPages <= 0) {
        info.textContent = "";
        prevBtn.disabled = true;
        nextBtn.disabled = true;
        return;
    }

    info.textContent = `Page ${currentPage} of ${totalPages}`;
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
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
            currentPage = 1;
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

function setupPagination() {
    document.getElementById("prev-page").addEventListener("click", () => {
        if (currentPage > 1) {
            currentPage--;
            renderTable();
        }
    });

    document.getElementById("next-page").addEventListener("click", () => {
        currentPage++;
        renderTable();
    });
}

function setupDateFilter() {
    const dateInput = document.getElementById("date-filter");
    dateInput.max = todayISO();
    dateInput.value = selectedDate;

    dateInput.addEventListener("change", () => {
        if (dateInput.value) loadLogs(dateInput.value);
    });

    document.getElementById("today-btn").addEventListener("click", () => {
        const today = todayISO();
        dateInput.value = today;
        loadLogs(today);
    });
}

document.getElementById("refresh-btn").addEventListener("click", () => loadLogs());
setupSorting();
setupPagination();
setupDateFilter();
loadLogs();
