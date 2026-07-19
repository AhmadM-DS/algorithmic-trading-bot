function tickClock() {
    const now = new Date();
    document.getElementById("clock-time").textContent =
        now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    document.getElementById("clock-date").textContent =
        now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}
tickClock();
setInterval(tickClock, 1000);

function money(n) {
    const sign = n < 0 ? "-" : "";
    return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function setKpi(key, text, value) {
    const el = document.querySelector(`[data-kpi="${key}"]`);
    if (!el) return;
    el.textContent = text;
    el.classList.remove("positive", "negative");
    if (value > 0) el.classList.add("positive");
    if (value < 0) el.classList.add("negative");
}

function renderList(id, items, render) {
    const ul = document.getElementById(id);
    if (!items || !items.length) {
        ul.innerHTML = `<li><span>—</span><span class="tag">no data</span></li>`;
        return;
    }
    ul.innerHTML = items.map(render).join("");
}

function buildCalendar(plByDay) {
    const grid = document.getElementById("calendar-grid");
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const firstDay = new Date(year, month, 1).getDay();      // 0 = Sun
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    let html = "";
    for (let i = 0; i < firstDay; i++) html += `<div class="day empty"></div>`;

    for (let d = 1; d <= daysInMonth; d++) {
        const pl = plByDay[d];
        let cls = "day";
        let plText = "";
        if (pl !== undefined) {
            cls += pl >= 0 ? " positive" : " negative";
            plText = `<span class="pl">${money(pl)}</span>`;
        }
        html += `<div class="${cls}"><span class="date">${d}</span>${plText}</div>`;
    }
    grid.innerHTML = html;
}

function render(data) {
    setKpi("accountBalance", money(data.accountBalance), data.accountBalance);
    setKpi("dailyPL", money(data.dailyPL), data.dailyPL);
    setKpi("winRate", `${data.winRate}%`, 0);
    setKpi("tradesToday", data.tradesToday, 0);
    setKpi("openPositions", data.openPositions, 0);

    renderList("stocks-list", data.stocks,
        (s) => `<li><span>${s.symbol}</span><span class="tag">${s.side}</span></li>`);
    renderList("strategy-list", data.strategy,
        (s) => `<li><span>${s.name}</span><span class="tag">${s.detail}</span></li>`);
    renderList("orders-list", data.orders,
        (o) => `<li><span>${o.symbol}</span><span class="tag">${o.type}</span></li>`);

    buildCalendar(data.calendar || {});
}

async function loadData() {
    try {
        const res = await fetch("/api/account-overview");
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const data = await res.json();
        render(data);
    } catch (err) {
        console.error("Failed to load account overview:", err);
    }
}

loadData();