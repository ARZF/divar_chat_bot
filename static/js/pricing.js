// Phase 3 step 29: public pricing page.
// Fetches the central plan catalogue (GET /api/v1/plans — the step 28 API)
// and renders exactly what it returns. No plan name, price, limit, or
// duration is ever hard-coded here: the API is the only source. Empty
// response → the honest "nothing to show" state; no invented packages.
// No checkout exists (step 26 payment boundary) — this page offers no
// purchase action at all.
(() => {
    "use strict";

    const PLANS_URL = "/api/v1/plans";

    const $ = (selector) => document.querySelector(selector);

    const els = {
        loading: $("#pricing-loading"),
        errorBox: $("#pricing-error"),
        empty: $("#pricing-empty"),
        data: $("#pricing-data"),
        cards: $("#pricing-cards"),
    };

    const formatNumber = (value) => Number(value).toLocaleString("fa-IR");

    // A nullable limit renders honestly ("—"), never as zero or unlimited.
    const formatLimit = (value) =>
        typeof value === "number" ? formatNumber(value) : "—";

    const row = (label, value) => {
        const tr = document.createElement("tr");
        const th = document.createElement("th");
        th.scope = "row";
        th.textContent = label;
        const td = document.createElement("td");
        td.className = "num";
        td.textContent = value;
        tr.append(th, td);
        return tr;
    };

    const card = (plan) => {
        const article = document.createElement("article");
        article.className = "pricing-card";

        const title = document.createElement("h3");
        title.textContent = plan.name;
        article.append(title);

        const price = document.createElement("p");
        price.className = "pricing-price";
        // The API is the price source; a zero price is shown as رایگان,
        // a non-zero one as-is with the toman unit. No invented discounts.
        price.textContent =
            typeof plan.price === "number" && plan.price > 0
                ? `${formatNumber(plan.price)} تومان`
                : "رایگان";
        article.append(price);

        // Billing period / duration only when the plan actually has one.
        if (typeof plan.duration_days === "number" && plan.duration_days > 0) {
            const duration = document.createElement("p");
            duration.textContent = `مدت: ${formatNumber(plan.duration_days)} روز`;
            article.append(duration);
        }
        if (plan.billing_period) {
            const period = document.createElement("p");
            period.textContent = `دورهٔ صورت‌حساب: ${plan.billing_period}`;
            article.append(period);
        }

        if (plan.description) {
            const description = document.createElement("p");
            description.textContent = plan.description;
            article.append(description);
        }

        const table = document.createElement("div");
        table.className = "table-wrap";
        const tbody = document.createElement("tbody");
        tbody.append(row("گفتگوهای خریدار", formatLimit(plan.conversation_limit)));
        tbody.append(row("پیام‌های خریدار", formatLimit(plan.message_limit)));
        tbody.append(row("آگهی‌ها", formatLimit(plan.listing_limit)));
        tbody.append(row("محصولات", formatLimit(plan.product_limit)));
        const tableEl = document.createElement("table");
        tableEl.append(tbody);
        table.append(tableEl);
        article.append(table);

        if (Array.isArray(plan.features) && plan.features.length > 0) {
            const ul = document.createElement("ul");
            ul.className = "pricing-features";
            for (const feature of plan.features) {
                const li = document.createElement("li");
                li.textContent = feature;
                ul.append(li);
            }
            article.append(ul);
        }

        return article;
    };

    const load = async () => {
        try {
            const response = await fetch(PLANS_URL);
            if (!response.ok) {
                els.errorBox.hidden = false;
                return;
            }
            const data = await response.json();
            els.loading.hidden = true;
            if (!Array.isArray(data.items) || data.items.length === 0) {
                els.empty.hidden = false;
                return;
            }
            els.cards.replaceChildren(...data.items.map(card));
            els.data.hidden = false;
        } catch {
            els.errorBox.hidden = false;
        } finally {
            els.loading.hidden = true;
        }
    };

    load();
})();
