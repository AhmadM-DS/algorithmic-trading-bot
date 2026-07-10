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

async function loadData() {
    try {
        const res = await fetch("/api/expenses");
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const data = await res.json();
        render(data);
    } catch (err) {
        console.error("Failed to load expenses:", err);
    }
}

function render(data) {
    renderSubscriptions(data.subscriptions);
    renderExpenses(data.expenses);
    renderSummary(data);
}

loadData();