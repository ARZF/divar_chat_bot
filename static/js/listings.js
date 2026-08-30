// Phase 3 step 22: listing management page.
// All authenticated traffic goes through DivarSession (static/js/session.js):
// authFetch handles the in-memory token, the single refresh/retry on 401, and
// the redirect to /login. This script renders ONLY the fields the step 19/21
// APIs actually supply — no cost, no lifecycle status, no edit or delete
// (unsupported on Divar), no fabricated metadata (§3.8.3: unsupported actions
// must not be displayed as if they work). The availability toggle changes only
// this project's own chatbot behavior; it never claims to change anything on
// Divar itself.
(() => {
    "use strict";

    const LIST_URL = "/api/v1/seller/listings";
    const SYNC_URL = "/api/v1/seller/listings/sync";
    // Best-effort link: the verified capability matrix (step 19) found no
    // endpoint exposing the seo-slug, so only the token-only form is used.
    const DIVAR_POST_URL = "https://divar.ir/v/";

    const $ = (selector) => document.querySelector(selector);

    const els = {
        loading: $("#listings-loading"),
        errorBox: $("#listings-error"),
        errorText: $("#listings-error-text"),
        data: $("#listings-data"),
        syncButton: $("#listings-sync-button"),
        syncError: $("#listings-sync-error"),
        syncSkipped: $("#listings-sync-skipped"),
        syncFeedback: $("#listings-sync-feedback"),
        tableWrap: $("#listings-table-wrap"),
        tbody: $("#listings-tbody"),
        empty: $("#listings-empty"),
        pagination: $("#listings-pagination"),
        logoutButton: $("[data-listings-logout]"),
    };

    let page = 1;
    let pageCount = 1;

    const setAlert = (element, message) => {
        if (!element) {
            return;
        }
        element.hidden = !message;
        element.querySelector("p").textContent = message || "";
    };

    const showListError = (message) => {
        els.loading.hidden = true;
        els.data.hidden = true;
        if (els.errorText) {
            els.errorText.textContent = message;
        }
        els.errorBox.hidden = false;
    };

    // Persian digits for page numbers and dates (products.js convention);
    // dates render in the seller's locale, a null sync time renders as "—".
    const formatPage = (value) => Number(value).toLocaleString("fa-IR");
    const formatDateTime = (iso) =>
        iso
            ? new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })
            : "—";

    const cell = (text, className, label) => {
        const td = document.createElement("td");
        if (className) {
            td.className = className;
        }
        if (label) {
            // Powers the deliberate stacked mobile representation (.table-stack).
            td.setAttribute("data-label", label);
        }
        td.textContent = text;
        return td;
    };

    const nameCell = (listing) => {
        const td = document.createElement("td");
        td.className = "cell-name";
        td.setAttribute("data-label", "آگهی");
        const box = document.createElement("div");
        const title = document.createElement("div");
        // An unsynced-yet row has no title; the token is the honest fallback.
        title.textContent = listing.title || listing.post_token;
        box.append(title);
        if (listing.category) {
            const sub = document.createElement("div");
            sub.className = "cell-sub num";
            // Divar's raw category slug — shown as-is, never translated into
            // an invented Persian category name.
            sub.textContent = listing.category;
            box.append(sub);
        }
        td.append(box);
        return td;
    };

    const presenceCell = (listing) => {
        const td = document.createElement("td");
        td.setAttribute("data-label", "وضعیت در دیوار");
        const status = document.createElement("span");
        status.className = listing.present_on_divar
            ? "status status-success"
            : "status status-warning";
        status.textContent = listing.present_on_divar
            ? "روی دیوار"
            : "دیگر روی دیوار نیست";
        td.append(status);
        return td;
    };

    const linkCell = (listing) => {
        const td = document.createElement("td");
        td.setAttribute("data-label", "لینک");
        const link = document.createElement("a");
        link.href = DIVAR_POST_URL + encodeURIComponent(listing.post_token);
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "مشاهده در دیوار";
        td.append(link);
        return td;
    };

    const toggleCell = (listing) => {
        // §3.8.4: the seller's own chatbot toggle. Reversible, so unlike
        // products' delete there is no confirmation — but the control is
        // disabled while its PATCH is in flight and failures show their own
        // small error and revert the checkbox.
        const td = document.createElement("td");
        td.setAttribute("data-label", "پاسخ‌گوی خودکار");
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = listing.is_available;
        input.setAttribute(
            "aria-label",
            `پاسخ‌گوی خودکار برای ${listing.title || listing.post_token}`
        );
        const text = document.createElement("span");
        text.textContent = listing.is_available ? "فعال" : "غیرفعال";
        label.append(input, text);
        const error = document.createElement("span");
        error.className = "toggle-error";
        error.hidden = true;

        const render = (value) => {
            input.checked = value;
            text.textContent = value ? "فعال" : "غیرفعال";
        };

        input.addEventListener("change", async () => {
            const next = input.checked;
            input.disabled = true;
            error.hidden = true;
            try {
                const response = await window.DivarSession.authFetch(
                    `${LIST_URL}/${encodeURIComponent(listing.post_token)}/availability`,
                    {
                        method: "PATCH",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ is_available: next }),
                    }
                );
                if (response.ok) {
                    const data = await response.json();
                    render(data.is_available);
                } else {
                    render(!next);
                    error.textContent =
                        response.status === 404
                            ? "این آگهی در فهرست شما پیدا نشد."
                            : "ذخیرهٔ تنظیم انجام نشد. دوباره تلاش کنید.";
                    error.hidden = false;
                }
            } catch {
                render(!next);
                error.textContent = "ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.";
                error.hidden = false;
            } finally {
                input.disabled = false;
            }
        });

        td.append(label, error);
        return td;
    };

    const renderRows = (listings) => {
        const rows = listings.map((listing) => {
            const tr = document.createElement("tr");
            // Soft-sync design (step 21): a listing absent from the latest
            // sync stays visible — muted, informational — never hidden.
            if (!listing.present_on_divar) {
                tr.className = "row-absent";
            }
            tr.append(nameCell(listing));
            tr.append(presenceCell(listing));
            tr.append(
                cell(
                    listing.chat_enabled == null
                        ? "—"
                        : listing.chat_enabled
                            ? "فعال"
                            : "غیرفعال",
                    null,
                    "دستیار چت دیوار"
                )
            );
            tr.append(
                cell(
                    listing.is_phone_hidden == null
                        ? "—"
                        : listing.is_phone_hidden
                            ? "مخفی"
                            : "آشکار",
                    null,
                    "شمارهٔ تماس"
                )
            );
            tr.append(
                cell(formatDateTime(listing.last_synced_at), "num", "آخرین همگام‌سازی")
            );
            tr.append(toggleCell(listing));
            tr.append(linkCell(listing));
            return tr;
        });
        els.tbody.replaceChildren(...rows);
    };

    const renderPagination = () => {
        els.pagination.replaceChildren();
        if (pageCount <= 1) {
            els.pagination.hidden = true;
            return;
        }

        const prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "قبلی";
        prev.disabled = page <= 1;
        prev.addEventListener("click", () => {
            load(page - 1);
        });

        const info = document.createElement("span");
        info.textContent = `صفحهٔ ${formatPage(page)} از ${formatPage(pageCount)}`;

        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "بعدی";
        next.disabled = page >= pageCount;
        next.addEventListener("click", () => {
            load(page + 1);
        });

        els.pagination.append(prev, info, next);
        els.pagination.hidden = false;
    };

    const load = async (targetPage = 1) => {
        els.loading.hidden = false;
        els.errorBox.hidden = true;
        els.tableWrap.hidden = true;
        els.empty.hidden = true;
        els.pagination.hidden = true;
        try {
            const params = new URLSearchParams();
            params.set("page", String(targetPage));
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}?${params.toString()}`
            );
            if (!response.ok) {
                // A 401 with a failed refresh already redirected via session.js.
                showListError("بارگذاری آگهی‌ها انجام نشد. دوباره تلاش کنید.");
                return;
            }
            const data = await response.json();
            page = data.page;
            pageCount = data.page_count;
            els.loading.hidden = true;
            els.data.hidden = false;
            if (data.total === 0) {
                // The API cannot distinguish "never synced" from "synced but
                // zero posts", so the empty state stays honestly generic.
                els.empty.hidden = false;
                return;
            }
            renderRows(data.items);
            renderPagination();
            els.tableWrap.hidden = false;
        } catch {
            showListError("ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        }
    };

    // ---- explicit sync trigger (never automatic: per-app Divar rate limits) -

    const syncNow = async () => {
        els.syncButton.disabled = true;
        els.syncButton.textContent = "در حال همگام‌سازی…";
        setAlert(els.syncError, null);
        setAlert(els.syncFeedback, null);
        els.syncSkipped.hidden = true;
        try {
            const response = await window.DivarSession.authFetch(SYNC_URL, {
                method: "POST",
            });
            if (response.ok) {
                const data = await response.json();
                if (data.status === "skipped") {
                    // OTP-only seller (never completed Divar OAuth): guidance,
                    // not an error — and nothing was written server-side.
                    els.syncSkipped.hidden = false;
                } else {
                    setAlert(
                        els.syncFeedback,
                        `همگام‌سازی انجام شد: ${formatPage(data.registered)} آگهی جدید،` +
                            ` ${formatPage(data.updated)} به‌روزرسانی شد،` +
                            ` ${formatPage(data.marked_absent)} دیگر روی دیوار نیست.`
                    );
                    // Reload so titles, presence, and last_synced_at refresh.
                    await load(1);
                }
            } else if (response.status === 502) {
                setAlert(
                    els.syncError,
                    "همگام‌سازی با دیوار انجام نشد؛ فهرست آگهی‌ها تغییر نکرد."
                );
            } else {
                setAlert(els.syncError, "همگام‌سازی انجام نشد. دوباره تلاش کنید.");
            }
        } catch {
            setAlert(els.syncError, "ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        } finally {
            els.syncButton.disabled = false;
            els.syncButton.textContent = "همگام‌سازی با دیوار";
        }
    };

    // ---- wiring -------------------------------------------------------------

    els.syncButton.addEventListener("click", syncNow);
    els.logoutButton?.addEventListener("click", () => {
        window.DivarSession.logout();
    });

    load();
})();
