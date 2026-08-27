// Phase 3 step 13: dashboard shell data loading.
// All authenticated traffic goes through DivarSession (static/js/session.js):
// authFetch handles the in-memory token, the single refresh/retry on 401, and
// the redirect to /login. This script contains no token or redirect logic.
(() => {
    "use strict";

    const SUMMARY_URL = "/api/v1/seller/dashboard/summary";

    const loading = document.querySelector("#dashboard-loading");
    const errorBox = document.querySelector("#dashboard-error");
    const errorText = document.querySelector("#dashboard-error-text");
    const data = document.querySelector("#dashboard-data");
    const sellerPhone = document.querySelector("#seller-phone");
    const postCount = document.querySelector("#post-count");
    const conversationCount = document.querySelector("#conversation-count");
    const postConversationCount = document.querySelector("#post-conversation-count");
    const logoutButton = document.querySelector("[data-dashboard-logout]");

    const showError = (message) => {
        if (loading) {
            loading.hidden = true;
        }
        if (data) {
            data.hidden = true;
        }
        if (errorBox && errorText) {
            errorText.textContent = message;
            errorBox.hidden = false;
        }
    };

    const formatCount = (value) => (typeof value === "number" ? String(value) : "—");

    const fill = (summary) => {
        if (sellerPhone) {
            sellerPhone.textContent = summary.phone_number ?? "—";
        }
        if (postCount) {
            postCount.textContent = formatCount(summary.post_count);
        }
        if (conversationCount) {
            conversationCount.textContent = formatCount(summary.conversation_count);
        }
        if (postConversationCount) {
            postConversationCount.textContent = formatCount(summary.post_conversation_count);
        }
        if (loading) {
            loading.hidden = true;
        }
        if (data) {
            data.hidden = false;
        }
    };

    const load = async () => {
        try {
            const response = await window.DivarSession.authFetch(SUMMARY_URL);
            if (!response.ok) {
                // A 401 with a failed refresh already redirected via session.js;
                // anything else is a genuine load failure.
                showError("بارگذاری اطلاعات میزکار انجام نشد. دوباره تلاش کنید.");
                return;
            }
            fill(await response.json());
        } catch {
            showError("ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        }
    };

    logoutButton?.addEventListener("click", () => {
        window.DivarSession.logout();
    });

    load();
})();
