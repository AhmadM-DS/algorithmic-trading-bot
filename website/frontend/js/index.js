// ============================================================
//  Noctis · Account Overview (frontend only)
//  Backend not wired yet. Placeholder data lives in PLACEHOLDER.
//  When FastAPI is ready, see loadData() at the bottom.
// ============================================================

// ---- 1. Live clock ---------------------------------------------
function tickClock() {
    const now = new Date();
    document.getElementById("clock-time").textContent =
        now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    document.getElementById("clock-date").textContent =
        now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}
tickClock();
setInterval(tickClock, 1000);

// ---- 3. Placeholder data (replace with API later) --------------
const PLACEHOLDER = {
    accountBalance: 10425.60,
    dailyPL: 125.40,
    winRate: 66,
    tradesToday: 6,
    todaysProfit: 125.40,
    stocks: [
        { symbol: "AAPL", side: "Long" },
        { symbol: "TSLA", side: "Short" },
        { symbol: "NVDA", side: "Long" },
    ],
    strategy: [
        { name: "Mean Reversion", detail: "RSI < 30" },
        { name: "Breakout", detail: "20-day high" },
    ],
    orders: [
        { symbol: "AAPL", type: "Buy 10 @ 192.30" },
        { symbol: "TSLA", type: "Sell 5 @ 244.10" },
        { symbol: "NVDA", type: "Buy 8 @ 118.75" },
    ],
    // Daily P/L keyed by day number of the current month
    calendar: { 3: 82, 4: -45, 7: 130, 8: 60, 10: -20, 14: 210, 15: -95, 17: 40, 21: 155 },
};

// ---- 4. Render helpers -----------------------------------------
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
    // blank cells before day 1
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

// ---- 5. Paint the page -----------------------------------------
function render(data) {
    setKpi("accountBalance", money(data.accountBalance), data.accountBalance);
    setKpi("dailyPL", money(data.dailyPL), data.dailyPL);
    setKpi("winRate", `${data.winRate}%`, 0);
    setKpi("tradesToday", data.tradesToday, 0);
    setKpi("todaysProfit", money(data.todaysProfit), data.todaysProfit);

    renderList("stocks-list", data.stocks,
        (s) => `<li><span>${s.symbol}</span><span class="tag">${s.side}</span></li>`);
    renderList("strategy-list", data.strategy,
        (s) => `<li><span>${s.name}</span><span class="tag">${s.detail}</span></li>`);
    renderList("orders-list", data.orders,
        (o) => `<li><span>${o.symbol}</span><span class="tag">${o.type}</span></li>`);

    buildCalendar(data.calendar);
}

// ---- 6. Data loader (swap in FastAPI later) --------------------
async function loadData() {
    // TODO backend: uncomment when FastAPI endpoint exists.
    // const res = await fetch("/api/account-overview");
    // const data = await res.json();
    // render(data);
    // return;

    render(PLACEHOLDER); // using placeholder for now
}

loadData();