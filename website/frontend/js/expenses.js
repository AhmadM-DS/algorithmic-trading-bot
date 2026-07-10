// ============================================================
//  Noctis · Expenses (frontend only)
//  Placeholder data mirrors the SQL schema (Subscriptions + Expenses).
//  Backend hookup marked below.
// ============================================================

// ---- Placeholder data (matches your SQL columns) ---------------
const PLACEHOLDER = {
    subscriptions: [
        { Service_Name: "Alpaca Markets", Provider: "Alpaca", Purpose: "Brokerage API for trade execution",
          Cost: 0.00, Billing_Cycle: "Monthly", Payment_Method: "N/A", Start_Date: "2026-01-15", Is_Active: 1 },
        { Service_Name: "AWS EC2", Provider: "Amazon", Purpose: "Server hosting the bot 24/7",
          Cost: 18.50, Billing_Cycle: "Monthly", Payment_Method: "Visa ****4821", Start_Date: "2026-01-20", Is_Active: 1 },
        { Service_Name: "Polygon.io", Provider: "Polygon", Purpose: "Market data feed",
          Cost: 199.00, Billing_Cycle: "Yearly", Payment_Method: "Visa ****4821", Start_Date: "2026-02-01", Is_Active: 1 },
        { Service_Name: "Discord Nitro", Provider: "Discord", Purpose: "Alert webhooks / notifications",
          Cost: 9.99, Billing_Cycle: "Monthly", Payment_Method: "PayPal", Start_Date: "2026-03-10", Is_Active: 0 },
    ],
    expenses: [
        { Date: "2026-07-01", Expense_Name: "AWS EC2 - July", Provider: "Amazon", Purpose: "Monthly server cost",
          Cost: 18.50, Payment_Method: "Visa ****4821", Subscription: "AWS EC2" },
        { Date: "2026-06-15", Expense_Name: "Domain renewal", Provider: "Namecheap", Purpose: "noctisbot.com for 1 year",
          Cost: 12.98, Payment_Method: "Visa ****4821", Subscription: null },
        { Date: "2026-06-01", Expense_Name: "AWS EC2 - June", Provider: "Amazon", Purpose: "Monthly server cost",
          Cost: 18.50, Payment_Method: "Visa ****4821", Subscription: "AWS EC2" },
        { Date: "2026-02-01", Expense_Name: "Polygon annual", Provider: "Polygon", Purpose: "Market data subscription",
          Cost: 199.00, Payment_Method: "Visa ****4821", Subscription: "Polygon.io" },
    ],
};

// ---- Helpers ---------------------------------------------------
function money(n) {
    return `$${Number(n).toFixed(2)}`;
}

// Convert any billing cycle to a monthly-equivalent cost
function monthlyEquivalent(cost, cycle) {
    const c = (cycle || "").toLowerCase();
    if (c.includes("year")) return cost / 12;
    if (c.includes("quarter")) return cost / 3;
    if (c.includes("week")) return cost * 4.33;
    return cost; // monthly / default
}

function escapeHtml(str) {
    return String(str ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
}

// ---- Render subscriptions --------------------------------------
function renderSubscriptions(subs) {
    const body = document.getElementById("subs-body");
    document.getElementById("subs-count").textContent = `${subs.length} total`;

    if (!subs.length) {
        body.innerHTML = `<tr><td colspan="9" class="empty-row">No subscriptions.</td></tr>`;
        return;
    }

    body.innerHTML = subs.map(s => {
        const monthly = monthlyEquivalent(s.Cost, s.Billing_Cycle);
        const active = s.Is_Active
            ? `<span class="status-pill active">Active</span>`
            : `<span class="status-pill inactive">Inactive</span>`;
        return `
            <tr>
                <td class="nowrap">${escapeHtml(s.Service_Name)}</td>
                <td>${escapeHtml(s.Provider)}</td>
                <td class="muted">${escapeHtml(s.Purpose)}</td>
                <td class="cost">${money(s.Cost)}</td>
                <td class="nowrap">${escapeHtml(s.Billing_Cycle)}</td>
                <td class="cost muted">${money(monthly)}</td>
                <td class="nowrap">${escapeHtml(s.Payment_Method)}</td>
                <td class="nowrap">${escapeHtml(s.Start_Date)}</td>
                <td>${active}</td>
            </tr>`;
    }).join("");
}

// ---- Render expenses -------------------------------------------
function renderExpenses(expenses) {
    const body = document.getElementById("exp-body");
    document.getElementById("exp-count").textContent = `${expenses.length} total`;

    if (!expenses.length) {
        body.innerHTML = `<tr><td colspan="7" class="empty-row">No expenses.</td></tr>`;
        return;
    }

    // newest first by date
    const sorted = [...expenses].sort((a, b) => b.Date.localeCompare(a.Date));

    body.innerHTML = sorted.map(e => `
        <tr>
            <td class="nowrap">${escapeHtml(e.Date)}</td>
            <td class="nowrap">${escapeHtml(e.Expense_Name)}</td>
            <td>${escapeHtml(e.Provider)}</td>
            <td class="muted">${escapeHtml(e.Purpose)}</td>
            <td class="cost">${money(e.Cost)}</td>
            <td class="nowrap">${escapeHtml(e.Payment_Method)}</td>
            <td class="muted">${e.Subscription ? escapeHtml(e.Subscription) : "—"}</td>
        </tr>`).join("");
}

// ---- Summary totals --------------------------------------------
function renderSummary(data) {
    // Total all-time = sum of every expense row
    const totalAll = data.expenses.reduce((sum, e) => sum + Number(e.Cost), 0);

    // Monthly recurring = sum of active subs' monthly equivalents
    const monthlyRecurring = data.subscriptions
        .filter(s => s.Is_Active)
        .reduce((sum, s) => sum + monthlyEquivalent(s.Cost, s.Billing_Cycle), 0);

    // This month's spend = expenses dated in the current month
    const now = new Date();
    const ym = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const thisMonth = data.expenses
        .filter(e => e.Date.startsWith(ym))
        .reduce((sum, e) => sum + Number(e.Cost), 0);

    document.getElementById("total-all").textContent = money(totalAll);
    document.getElementById("total-monthly").textContent = money(monthlyRecurring);
    document.getElementById("total-this-month").textContent = money(thisMonth);
}

// ---- Data loader (swap in FastAPI later) -----------------------
async function loadData() {
    // TODO backend: fetch from FastAPI, which queries SQL Server.
    // const res = await fetch("/api/expenses");
    // const data = await res.json();   // { subscriptions: [...], expenses: [...] }
    // render(data); return;

    render(PLACEHOLDER);
}

function render(data) {
    renderSubscriptions(data.subscriptions);
    renderExpenses(data.expenses);
    renderSummary(data);
}

loadData();