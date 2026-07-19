const css = getComputedStyle(document.documentElement);
const COLOR = {
    positive: css.getPropertyValue("--pl-positive").trim() || "#0DAB76",
    negative: css.getPropertyValue("--pl-negative").trim() || "#F9564F",
    accent:   css.getPropertyValue("--nav-title-color").trim() || "#1A535C",
    muted:    css.getPropertyValue("--text-muted").trim() || "#7A6A62",
    line:     css.getPropertyValue("--card-border").trim() || "#E4C79E",
};

const EMPTY_STATE = {
    risk: { maxDrawdown: "—", sharpe: "—", profitFactor: "—", avgWinLoss: "—" },
    dates: [],
    equity: [],
    cumulativePL: [],
    dailyPL: [],
    strategies: {},
    symbols: {},
    winLoss: { wins: 0, losses: 0 },
    strategyOptions: [],
    symbolOptions: [],
};

Chart.defaults.color = COLOR.muted;
Chart.defaults.font.family = "system-ui, sans-serif";

const noLegend = { plugins: { legend: { display: false } } };
const gridStyle = {
    x: { grid: { color: "rgba(0,0,0,0.05)" } },
    y: { grid: { color: "rgba(0,0,0,0.05)" } },
};

const charts = {};

function makeChart(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
}

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

function renderRisk(risk) {
    for (const [key, val] of Object.entries(risk)) {
        const el = document.querySelector(`[data-risk="${key}"]`);
        if (el) el.textContent = val;
    }
}

function fillSlicers(d) {
    const strat = document.getElementById("strategy-filter");
    const sym = document.getElementById("symbol-filter");
    d.strategyOptions.forEach(s => strat.add(new Option(s, s)));
    d.symbolOptions.forEach(s => sym.add(new Option(s, s)));

    strat.addEventListener("change", refresh);
    sym.addEventListener("change", refresh);
}

async function loadDashboard(strategy = "all", symbol = "all") {
    try {
        const res = await fetch(
            `/api/dashboard?strategy=${encodeURIComponent(strategy)}&symbol=${encodeURIComponent(symbol)}`
        );
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return await res.json();
    } catch (err) {
        console.error("Failed to load dashboard data:", err);
        return EMPTY_STATE;
    }
}

async function refresh() {
    const strategy = document.getElementById("strategy-filter").value;
    const symbol = document.getElementById("symbol-filter").value;
    const data = await loadDashboard(strategy, symbol);
    renderRisk(data.risk);
    buildCharts(data);
}

async function init() {
    const data = await loadDashboard();
    renderRisk(data.risk);
    fillSlicers(data);
    buildCharts(data);
}

init();