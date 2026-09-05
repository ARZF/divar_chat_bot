// Phase 3 step 29: subscription status page.
// All authenticated traffic goes through DivarSession (static/js/
// session.js): authFetch handles the in-memory token, the single
// refresh/retry on 401, and the redirect to /login.
//
// This script renders ONLY what the step 28 APIs return — plan name,
// status, dates, limits, and the derived window-scoped usage counts.
// No plan limit, price, duration, or expiry rule is ever calculated or
// duplicated here; the backend stays the single source. Statuses are the
// four §3.10.3 values as the API reports them (ACTIVE/EXPIRED/CANCELLED/
// PENDING) — no frontend-invented states. No checkout exists (step 26
// payment boundary): the "next action" section is informational, makes no
// request, and claims no purchase.
(() => {
    "use strict";

    const SUBSCRIPTION_URL = "/api/v1/seller/subscription";
    const PLANS_URL = "/api/v1/plans";

    const $ = (selector) => document.querySelector(selector);

    const els = {
        loading: $("#subscription-loading"),
        errorBox: $("#subscription-error"),
        data: $("#subscription-data"),
        planName: $("#subscription-plan-name"),
        planDescription: $("#subscription-plan-description"),
        status: $("#subscription-status"),
        startedAt: $("#subscription-started-at"),
        expiresAt: $("#subscription-expires-at"),
        expiredNote: $("#subscription-expired-note"),
        usageTable: $("#usage-table"),
        usageTbody: $("#usage-tbody"),
        usageUnavailable: $("#usage-unavailable"),
        usageUnlimited: $("#usage-unlimited"),
        availablePlansCards: $("#available-plans-cards"),
        availablePlansEmpty: $("#available-plans-empty"),
        logoutButton: $("[data-subscription-logout]"),
    };

    const STATUS_LABELS = {
        ACTIVE: "فعال",
        EXPIRED: "پایان‌یافته",
        CANCELLED: "لغو‌شده",
        PENDING: "در انتظار",
    };

    const formatNumber = (value) => Number(value).toLocaleString("fa-IR");
    const formatDateTime = (iso) =>
        iso
            ? new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })
            : "—";
    // A nullable limit renders honestly ("—"), never as zero or unlimited.
    const formatLimit = (value) =>
        typeof value === "number" ? formatNumber(value) : "—";

    const fillSubscription = (subscription) => {
        const plan = subscription.plan || {};
        els.planName.textContent = plan.name || "—";
        els.planDescription.textContent = plan.description || "—";
        const statusValue = subscription.status || "—";
        els.status.textContent = STATUS_LABELS[statusValue] || statusValue;
        els.startedAt.textContent = formatDateTime(subscription.started_at);
        els.expiresAt.textContent = formatDateTime(subscription.expires_at);
        // Visual emphasis only — the backend already derives EXPIRED at
        // read time; nothing here recomputes or mutates it.
        els.expiredNote.hidden = statusValue !== "EXPIRED";

        const usage = subscription.usage;
        if (usage) {
            const row = (label, used, limit) => {
                const tr = document.createElement("tr");
                const tdLabel = document.createElement("td");
                tdLabel.textContent = label;
                const tdUsed = document.createElement("td");
                tdUsed.className = "num";
                tdUsed.textContent = formatNumber(used);
                const tdLimit = document.createElement("td");
                tdLimit.className = "num";
                tdLimit.textContent = limit;
                tr.append(tdLabel, tdUsed, tdLimit);
                return tr;
            };
            els.usageTbody.replaceChildren(
                row(
                    "گفتگوهای خریدار",
                    usage.buyer_conversation_count,
                    formatLimit(plan.conversation_limit)
                ),
                row(
                    "پیام‌های خریدار",
                    usage.buyer_message_count,
                    formatLimit(plan.message_limit)
                )
            );
            // At least one dimension has no package cap → say so honestly
            // instead of the "—" implying a missing value.
            els.usageUnlimited.hidden = !(
                plan.conversation_limit == null || plan.message_limit == null
            );
        } else {
            els.usageTable.hidden = true;
            els.usageUnavailable.hidden = false;
        }
    };

    const fillAvailablePlans = (items) => {
        if (!Array.isArray(items) || items.length === 0) {
            els.availablePlansEmpty.hidden = false;
            return;
        }
        // Same rendering as the public pricing page — the same central
        // catalogue, same field contract. Only the names/prices the API
        // returns are shown, nothing invented.
        const card = (plan) => {
            const article = document.createElement("article");
            article.className = "pricing-card";
            const title = document.createElement("h3");
            title.textContent = plan.name;
            const price = document.createElement("p");
            price.className = "pricing-price";
            price.textContent =
                typeof plan.price === "number" && plan.price > 0
                    ? `${formatNumber(plan.price)} تومان`
                    : "رایگان";
            article.append(title, price);
            if (plan.description) {
                const description = document.createElement("p");
                description.textContent = plan.description;
                article.append(description);
            }
            return article;
        };
        els.availablePlansCards.replaceChildren(...items.map(card));
    };

    const load = async () => {
        try {
            const [subscriptionResponse, plansResponse] = await Promise.all([
                window.DivarSession.authFetch(SUBSCRIPTION_URL),
                fetch(PLANS_URL), // public catalogue — no auth needed
            ]);
            if (!subscriptionResponse.ok) {
                // A 401 with a failed refresh already redirected via
                // session.js; anything else is a genuine load failure.
                els.errorBox.hidden = false;
                return;
            }
            fillSubscription(await subscriptionResponse.json());
            // The plans list is non-critical: a failure leaves the honest
            // empty state, never a fabricated catalogue.
            if (plansResponse.ok) {
                fillAvailablePlans((await plansResponse.json()).items);
            } else {
                els.availablePlansEmpty.hidden = false;
            }
            els.loading.hidden = true;
            els.data.hidden = false;
        } catch {
            els.errorBox.hidden = false;
        } finally {
            els.loading.hidden = true;
        }
    };

    els.logoutButton?.addEventListener("click", () => {
        window.DivarSession.logout();
    });

    load();
})();
