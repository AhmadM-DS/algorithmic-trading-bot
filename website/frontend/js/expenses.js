function money(n) {
    return `$${Number(n).toFixed(2)}`;
}

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

function fillSubscriptionSelect(subs) {
    const select = document.getElementById("exp-subscription-select");
    const current = select.value;
    select.innerHTML = `<option value="">None</option>` +
        subs.map(s => `<option value="${s.Subscription_ID}">${escapeHtml(s.Service_Name)}</option>`).join("");
    select.value = current;
}

function render(data) {
    renderSubscriptions(data.subscriptions);
    renderExpenses(data.expenses);
    renderSummary(data);
    fillSubscriptionSelect(data.subscriptions);
}

async function loadData() {
    try {
        const res = await fetch("/api/expenses");
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const data = await res.json();
        render(data);
    } catch (err) {
        console.error("Failed to load expenses:", err);
        document.getElementById("subs-body").innerHTML =
            `<tr><td colspan="9" class="empty-row">Could not load subscriptions.</td></tr>`;
        document.getElementById("exp-body").innerHTML =
            `<tr><td colspan="7" class="empty-row">Could not load expenses.</td></tr>`;
    }
}

let paymentMethods = [];

function fillPaymentSelects() {
    const options = paymentMethods.map(m => `<option value="${escapeHtml(m.Name)}">${escapeHtml(m.Name)}</option>`).join("");
    ["subs-payment-select", "exp-payment-select"].forEach(id => {
        const select = document.getElementById(id);
        const current = select.value;
        select.innerHTML = options;
        if ([...select.options].some(o => o.value === current)) select.value = current;
    });
}

async function loadPaymentMethods() {
    try {
        const res = await fetch("/api/payment-methods");
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const data = await res.json();
        paymentMethods = data.paymentMethods;
    } catch (err) {
        console.error("Failed to load payment methods:", err);
        paymentMethods = [];
    }
    fillPaymentSelects();
}

function setupPaymentMethodPicker(prefix) {
    const addBtn = document.querySelector(`.add-payment-btn[data-target="${prefix}"]`);
    const inline = document.getElementById(`${prefix}-add-payment-inline`);
    const nameInput = document.getElementById(`${prefix}-new-payment-name`);
    const saveBtn = document.getElementById(`${prefix}-new-payment-save`);
    const cancelBtn = document.getElementById(`${prefix}-new-payment-cancel`);
    const select = document.getElementById(`${prefix}-payment-select`);
    const errorEl = document.getElementById(`${prefix}-form-error`);

    addBtn.addEventListener("click", () => {
        inline.hidden = false;
        nameInput.value = "";
        nameInput.focus();
    });

    cancelBtn.addEventListener("click", () => {
        inline.hidden = true;
    });

    saveBtn.addEventListener("click", async () => {
        const name = nameInput.value.trim();
        if (!name) return;
        try {
            const created = await submitJson("/api/payment-methods", { Name: name });
            await loadPaymentMethods();
            select.value = created.Name;
            inline.hidden = true;
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });
}

function setupModal(toggleId, modalId, closeId, cancelId) {
    const toggle = document.getElementById(toggleId);
    const modal = document.getElementById(modalId);
    const closeBtn = document.getElementById(closeId);
    const cancelBtn = document.getElementById(cancelId);
    const form = modal.querySelector("form");

    const open = () => {
        form.reset();
        modal.querySelector(".form-error").textContent = "";
        modal.showModal();
    };
    const close = () => modal.close();

    toggle.addEventListener("click", open);
    closeBtn.addEventListener("click", close);
    cancelBtn.addEventListener("click", close);
}

async function submitJson(url, payload) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try {
            const body = await res.json();
            if (body.detail) {
                detail = typeof body.detail === "string"
                    ? body.detail
                    : body.detail.map(d => d.msg).join("; ");
            }
        } catch { /* ignore parse errors, keep default message */ }
        throw new Error(detail);
    }
    return res.json();
}

function setupSubscriptionForm() {
    const form = document.getElementById("subs-form");
    const errorEl = document.getElementById("subs-form-error");
    const modal = document.getElementById("subs-modal");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        errorEl.textContent = "";
        const fd = new FormData(form);
        const payload = {
            Service_Name: fd.get("Service_Name"),
            Provider: fd.get("Provider"),
            Purpose: fd.get("Purpose") || null,
            Cost: Number(fd.get("Cost")),
            Billing_Cycle: fd.get("Billing_Cycle"),
            Payment_Method: fd.get("Payment_Method"),
            Start_Date: fd.get("Start_Date"),
            Is_Active: fd.get("Is_Active") === "on",
        };
        try {
            await submitJson("/api/subscriptions", payload);
            modal.close();
            await loadData();
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });
}

function setupExpenseForm() {
    const form = document.getElementById("exp-form");
    const errorEl = document.getElementById("exp-form-error");
    const modal = document.getElementById("exp-modal");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        errorEl.textContent = "";
        const fd = new FormData(form);
        const subId = fd.get("Subscription_ID");
        const payload = {
            Expense_Name: fd.get("Expense_Name"),
            Provider: fd.get("Provider"),
            Purpose: fd.get("Purpose") || null,
            Cost: Number(fd.get("Cost")),
            Payment_Method: fd.get("Payment_Method"),
            Date: fd.get("Date"),
            Subscription_ID: subId ? Number(subId) : null,
        };
        try {
            await submitJson("/api/expenses", payload);
            modal.close();
            await loadData();
        } catch (err) {
            errorEl.textContent = err.message;
        }
    });
}

setupModal("subs-add-toggle", "subs-modal", "subs-modal-close", "subs-cancel-btn");
setupModal("exp-add-toggle", "exp-modal", "exp-modal-close", "exp-cancel-btn");
setupPaymentMethodPicker("subs");
setupPaymentMethodPicker("exp");
setupSubscriptionForm();
setupExpenseForm();
loadPaymentMethods();
loadData();
