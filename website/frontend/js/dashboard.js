// ============================================================
//  Noctis · Dashboard (frontend only)
//  Charts render from PLACEHOLDER. Backend hookup marked below.
// ============================================================

// ---- Theme colors pulled from CSS variables --------------------
const css = getComputedStyle(document.documentElement);
const COLOR = {
    positive: css.getPropertyValue("--pl-positive").trim() || "#0DAB76",
    negative: css.getPropertyValue("--pl-negative").trim() || "#F9564F",
    accent:   css.getPropertyValue("--nav-title-color").trim() || "#1A535C",
    muted:    css.getPropertyValue("--text-muted").trim() || "#7A6A62",
    line:     css.getPropertyValue("--card-border").trim() || "#E4C79E",
};

// ---- Placeholder data (replace with API later) -----------------
const PLACEHOLDER = {
    risk: { maxDrawdown: "-8.4%", sharpe: "1.62", profitFactor: "1.85", avgWinLoss: "1.4 : 1" },

    // time series
    dates: ["Jul 1", "Jul 2", "Jul 3", "Jul 4", "Jul 7", "Jul 8", "Jul 9", "Jul 10"],
    equity: [10000, 10082, 10037, 10167, 10297, 10357, 10262, 10426],
    cumulativePL: [0, 82, 37, 167, 297, 357, 262, 426],
    dailyPL: [0, 82, -45, 130, 130, 60, -95, 164],

    // categorical
    strategies: { "Mean Reversion": 310, "Breakout": 180, "Momentum": -64 },
    symbols: { AAPL: 210, TSLA: -45, NVDA: 190, MSFT: 71 },
    winLoss: { wins: 12, losses: 6 },

    // slicer options
    strategyOptions: ["Mean Reversion", "Breakout", "Momentum"],
    symbolOptions: ["AAPL", "TSLA", "NVDA", "MSFT"],
};

// ---- Common Chart.js options -----------------------------------
Chart.defaults.color = COLOR.muted;
Chart.defaults.font.family = "system-ui, sans-serif";

const noLegend = { plugins: { legend: { display: false } } };
const gridStyle = {
    x: { grid: { color: "rgba(0,0,0,0.05)" } },
    y: { grid: { color: "rgba(0,0,0,0.05)" } },
};

// Keep references so we can destroy/rebuild on slicer change
const charts = {};

function makeChart(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
}

// ---- Build each chart ------------------------------------------
function buildCharts(d) {
    // Equity curve (line)
    makeChart("equityChart", {
        type: "line",
        data: {
            labels: d.dates,
            datasets: [{
                data: d.equity,
                borderColor: COLOR.accent,
                backgroundColor: "rgba(26,83,92,0.08)",
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }],
        },
        options: { ...noLegend, maintainAspectRatio: false, scales: gridStyle },
    });

    // Cumulative P/L (line)
    makeChart("cumulativeChart", {
        type: "line",
        data: {
            labels: d.dates,
            datasets: [{
                data: d.cumulativePL,
                borderColor: COLOR.positive,
                backgroundColor: "rgba(13,171,118,0.08)",
                fill: true,
                tension: 0.3,
                pointRadius: 2,
            }],
        },
        options: { ...noLegend, maintainAspectRatio: false, scales: gridStyle },
    });

    // Daily P/L (bars, colored by sign)
    makeChart("dailyChart", {
        type: "bar",
        data: {
            labels: d.dates,
            datasets: [{
                data: d.dailyPL,
                backgroundColor: d.dailyPL.map(v => v >= 0 ? COLOR.positive : COLOR.negative),
            }],
        },
        options: { ...noLegend, maintainAspectRatio: false, scales: gridStyle },
    });

    // P/L by strategy (horizontal bars)
    const stratKeys = Object.keys(d.strategies);
    const stratVals = Object.values(d.strategies);
    makeChart("strategyChart", {
        type: "bar",
        data: {
            labels: stratKeys,
            datasets: [{
                data: stratVals,
                backgroundColor: stratVals.map(v => v >= 0 ? COLOR.positive : COLOR.negative),
            }],
        },
        options: { ...noLegend, maintainAspectRatio: false, indexAxis: "y", scales: gridStyle },
    });

    // P/L by symbol (horizontal bars)
    const symKeys = Object.keys(d.symbols);
    const symVals = Object.values(d.symbols);
    makeChart("symbolChart", {
        type: "bar",
        data: {
            labels: symKeys,
            datasets: [{
                data: symVals,
                backgroundColor: symVals.map(v => v >= 0 ? COLOR.positive : COLOR.negative),
            }],
        },
        options: { ...noLegend, maintainAspectRatio: false, indexAxis: "y", scales: gridStyle },
    });

    // Win/Loss (donut)
    makeChart("winLossChart", {
        type: "doughnut",
        data: {
            labels: ["Wins", "Losses"],
            datasets: [{
                data: [d.winLoss.wins, d.winLoss.losses],
                backgroundColor: [COLOR.positive, COLOR.negative],
            }],
        },
        options: { maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } },
    });
}

// ---- Risk KPI cards --------------------------------------------
function renderRisk(risk) {
    for (const [key, val] of Object.entries(risk)) {
        const el = document.querySelector(`[data-risk="${key}"]`);
        if (el) el.textContent = val;
    }
}

// ---- Slicers ---------------------------------------------------
function fillSlicers(d) {
    const strat = document.getElementById("strategy-filter");
    const sym = document.getElementById("symbol-filter");
    d.strategyOptions.forEach(s => strat.add(new Option(s, s)));
    d.symbolOptions.forEach(s => sym.add(new Option(s, s)));

    strat.addEventListener("change", refresh);
    sym.addEventListener("change", refresh);
}

// ---- Refresh (re-fetch filtered data) --------------------------
function refresh() {
    const strategy = document.getElementById("strategy-filter").value;
    const symbol = document.getElementById("symbol-filter").value;

    // TODO backend: fetch filtered data from FastAPI, e.g.
    // const res = await fetch(`/api/dashboard?strategy=${strategy}&symbol=${symbol}`);
    // const data = await res.json();
    // renderRisk(data.risk); buildCharts(data);

    // For now just rebuild with placeholder (filters are visual only)
    console.log("Slicer changed:", { strategy, symbol });
    buildCharts(PLACEHOLDER);
}

// ---- Init ------------------------------------------------------
function init(data) {
    renderRisk(data.risk);
    fillSlicers(data);
    buildCharts(data);
}

init(PLACEHOLDER);