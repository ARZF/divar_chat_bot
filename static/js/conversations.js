// Phase 3 step 25: seller conversations page — a read-only viewer.
// All authenticated traffic goes through DivarSession (static/js/session.js):
// authFetch handles the in-memory token, the single refresh/retry on 401, and
// the redirect to /login. This page consumes ONLY the supplier-side Divar
// conversation APIs from step 24 (/api/v1/seller/post-conversations*) — the
// Buyer↔Bot conversation system is not part of the seller-facing
// Conversations feature and has no endpoints here. Read-only by design: no
// send box, no state mutation, no realtime (later steps).
(() => {
    "use strict";

    const LIST_URL = "/api/v1/seller/post-conversations";

    const $ = (selector) => document.querySelector(selector);

    const els = {
        layout: $("#conversations-layout"),
        loading: $("#conversations-loading"),
        errorBox: $("#conversations-error"),
        retryButton: $("#conversations-retry"),
        data: $("#conversations-data"),
        list: $("#conversation-list"),
        empty: $("#conversations-empty"),
        pagination: $("#conversations-pagination"),
        placeholder: $("#conversation-placeholder"),
        detailLoading: $("#conversation-loading"),
        detailError: $("#conversation-error"),
        detailErrorText: $("#conversation-error-text"),
        detailRetry: $("#conversation-retry"),
        openArea: $("#conversation-open"),
        back: $("#conversation-back"),
        detailTitle: $("#conversation-listing-title"),
        detailState: $("#conversation-state"),
        detailMeta: $("#conversation-meta"),
        messages: $("#messages-list"),
        messagesEmpty: $("#messages-empty"),
        messagesPagination: $("#messages-pagination"),
        logoutButton: $("[data-conversations-logout]"),
    };

    // Safe, API-supplied labels only. A missing listing is honest about it —
    // the conversation is still shown (§3.9.2), never a fabricated listing.
    const LISTING_FALLBACK = "آگهی در دسترس نیست";
    const STATE_LABELS = { NEW: "جدید", ACTIVE: "فعال" };
    const SENDER_LABELS = { buyer: "خریدار", bot: "دستیار خودکار" };

    let page = 1;
    let pageCount = 1;
    let selectedId = null;
    let messagePage = 1;
    let messagePageCount = 1;

    // Persian digits for page numbers; dates render in the seller's locale
    // (products.js/listings.js convention).
    const formatPage = (value) => Number(value).toLocaleString("fa-IR");
    const formatDateTime = (iso) =>
        iso
            ? new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" })
            : "—";

    // ---- selection / URL state --------------------------------------------
    // The page keeps the selected conversation in the URL query (?conversation=)
    // via history.replaceState — shareable/reloadable deep links without any
    // router. Page scripts never navigate (redirect duty is session.js's).
    const setUrlSelection = (id) => {
        const url = id
            ? `/dashboard/conversations?conversation=${encodeURIComponent(id)}`
            : "/dashboard/conversations";
        history.replaceState(null, "", url);
    };

    const markActive = () => {
        for (const item of els.list.querySelectorAll(".conversation-item")) {
            if (item.dataset.conversationId === selectedId) {
                item.setAttribute("aria-current", "true");
            } else {
                item.removeAttribute("aria-current");
            }
        }
    };

    const clearSelection = () => {
        selectedId = null;
        setUrlSelection(null);
        els.layout.classList.remove("conversations-selected");
        markActive();
        els.messages.replaceChildren();
        els.messagesPagination.hidden = true;
        els.openArea.hidden = true;
        els.detailError.hidden = true;
        els.detailLoading.hidden = true;
        els.placeholder.hidden = false;
    };

    const selectConversation = (id) => {
        selectedId = id;
        setUrlSelection(id);
        els.layout.classList.add("conversations-selected");
        markActive();
        els.placeholder.hidden = true;
        els.detailError.hidden = true;
        els.openArea.hidden = true;
        loadConversation();
    };

    // ---- conversation list -------------------------------------------------

    const showListError = () => {
        els.loading.hidden = true;
        els.data.hidden = true;
        els.errorBox.hidden = false;
    };

    const renderList = (items) => {
        els.list.replaceChildren(
            ...items.map((conv) => {
                const li = document.createElement("li");
                const button = document.createElement("button");
                button.type = "button";
                button.className = "conversation-item";
                button.dataset.conversationId = conv.conversation_id;
                // Listing context is the identity anchor of this list; the
                // API provides no buyer identity, and none is invented.
                const title = document.createElement("span");
                title.className = "conversation-item-title";
                title.textContent = conv.listing_title || LISTING_FALLBACK;
                const preview = document.createElement("span");
                preview.className = "conversation-item-preview";
                preview.textContent = conv.last_message
                    ? conv.last_message.text_content || "بدون متن"
                    : "بدون پیام";
                const meta = document.createElement("span");
                meta.className = "conversation-item-meta";
                meta.textContent =
                    `${formatDateTime(conv.updated_at)} · ` +
                    `${STATE_LABELS[conv.current_state] || conv.current_state}`;
                button.append(title, preview, meta);
                button.addEventListener("click", () => {
                    selectConversation(conv.conversation_id);
                });
                li.append(button);
                return li;
            })
        );
        markActive();
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
            loadList(page - 1);
        });

        const info = document.createElement("span");
        info.textContent = `صفحهٔ ${formatPage(page)} از ${formatPage(pageCount)}`;

        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "بعدی";
        next.disabled = page >= pageCount;
        next.addEventListener("click", () => {
            loadList(page + 1);
        });

        els.pagination.append(prev, info, next);
        els.pagination.hidden = false;
    };

    // A conversation deep-linked from the URL is opened once the list itself
    // has loaded (so the seller sees it in context), regardless of which
    // page it sits on — detail/messages fetch by id, not by list position.
    let pendingId = new URLSearchParams(window.location.search).get("conversation");

    const loadList = async (targetPage = 1) => {
        els.loading.hidden = false;
        els.errorBox.hidden = true;
        els.data.hidden = true;
        els.empty.hidden = true;
        try {
            const params = new URLSearchParams();
            params.set("page", String(targetPage));
            // The page size is intentionally never sent: the API default (the
            // bounded page this UI wants) is used — no "load everything".
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}?${params.toString()}`
            );
            if (!response.ok) {
                // A 401 with a failed refresh already redirected via session.js.
                showListError();
                return;
            }
            const data = await response.json();
            page = data.page;
            pageCount = data.page_count;
            els.loading.hidden = true;
            els.data.hidden = false;
            if (data.total === 0) {
                if (pendingId) {
                    pendingId = null;
                    setUrlSelection(null);
                }
                els.empty.hidden = false;
                return;
            }
            renderList(data.items);
            renderPagination();
            if (pendingId) {
                const id = pendingId;
                pendingId = null;
                selectConversation(id);
            }
        } catch {
            showListError();
        }
    };

    // ---- selected conversation: header + message history -------------------

    const showDetailError = (message, retryable) => {
        els.detailLoading.hidden = true;
        els.openArea.hidden = true;
        els.detailErrorText.textContent = message;
        els.detailRetry.hidden = !retryable;
        els.detailError.hidden = false;
    };

    const renderDetail = (detail) => {
        els.detailTitle.textContent = detail.listing_title || LISTING_FALLBACK;
        els.detailState.textContent =
            STATE_LABELS[detail.current_state] || detail.current_state;
        els.detailState.className =
            detail.current_state === "ACTIVE"
                ? "status status-success"
                : "status status-info";
        els.detailMeta.textContent =
            `شروع: ${formatDateTime(detail.created_at)} · ` +
            `آخرین فعالیت: ${formatDateTime(detail.updated_at)}`;
    };

    const renderMessages = (items) => {
        // Backend order is chronological (created_at ASC, id ASC) — rendered
        // as received, never reversed or reordered here.
        els.messages.replaceChildren(
            ...items.map((msg) => {
                const li = document.createElement("li");
                li.className = `message message-${msg.sender_type}`;
                const bubble = document.createElement("div");
                bubble.className = "message-bubble";
                const text = document.createElement("p");
                text.className = "message-text";
                text.textContent = msg.text_content || "بدون متن";
                const meta = document.createElement("p");
                meta.className = "message-meta";
                meta.textContent =
                    `${SENDER_LABELS[msg.sender_type] || msg.sender_type} · ` +
                    `${formatDateTime(msg.sent_at)}`;
                bubble.append(text, meta);
                li.append(bubble);
                return li;
            })
        );
    };

    const renderMessagesPagination = () => {
        els.messagesPagination.replaceChildren();
        if (messagePageCount <= 1) {
            els.messagesPagination.hidden = true;
            return;
        }

        // Page 1 is the oldest page (ASC order): "قبلی" pages toward older
        // messages, "بعدی" toward newer ones.
        const prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "پیام‌های قدیمی‌تر";
        prev.disabled = messagePage <= 1;
        prev.addEventListener("click", () => {
            messagePage -= 1;
            loadMessages();
        });

        const info = document.createElement("span");
        info.textContent = `صفحهٔ ${formatPage(messagePage)} از ${formatPage(messagePageCount)}`;

        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "پیام‌های جدیدتر";
        next.disabled = messagePage >= messagePageCount;
        next.addEventListener("click", () => {
            messagePage += 1;
            loadMessages();
        });

        els.messagesPagination.append(prev, info, next);
        els.messagesPagination.hidden = false;
    };

    const loadMessages = async () => {
        const id = selectedId;
        try {
            const params = new URLSearchParams();
            params.set("page", String(messagePage));
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}/${encodeURIComponent(id)}/messages?${params.toString()}`
            );
            if (!response.ok) {
                showDetailError("بارگذاری پیام‌ها انجام نشد. دوباره تلاش کنید.", true);
                return;
            }
            const data = await response.json();
            if (id !== selectedId) {
                return; // a different conversation was selected meanwhile
            }
            messagePage = data.page;
            messagePageCount = data.page_count;
            els.detailLoading.hidden = true;
            els.openArea.hidden = false;
            renderMessages(data.items);
            renderMessagesPagination();
            els.messagesEmpty.hidden = data.total > 0;
        } catch {
            showDetailError("ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.", true);
        }
    };

    const loadConversation = async () => {
        const id = selectedId;
        els.detailError.hidden = true;
        els.openArea.hidden = true;
        els.detailLoading.hidden = false;
        try {
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}/${encodeURIComponent(id)}`
            );
            if (!response.ok) {
                if (response.status === 404) {
                    // Same non-leaking message whether the conversation is
                    // nonexistent or another seller's (§3.14): clear the
                    // selected state, keep nothing to retry.
                    showDetailError("این گفتگو پیدا نشد.", false);
                    selectedId = null;
                    setUrlSelection(null);
                    markActive();
                } else {
                    showDetailError("بارگذاری گفتگو انجام نشد. دوباره تلاش کنید.", true);
                }
                return;
            }
            const detail = await response.json();
            if (id !== selectedId) {
                return; // a different conversation was selected meanwhile
            }
            renderDetail(detail);
            messagePage = 1;
            await loadMessages();
        } catch {
            showDetailError("ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.", true);
        }
    };

    // ---- wiring -------------------------------------------------------------

    els.retryButton.addEventListener("click", () => {
        loadList(1);
    });
    els.detailRetry.addEventListener("click", () => {
        if (selectedId) {
            loadConversation();
        }
    });
    els.back.addEventListener("click", clearSelection);
    els.logoutButton?.addEventListener("click", () => {
        window.DivarSession.logout();
    });

    loadList();
})();
