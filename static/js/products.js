// Phase 3 step 18: product management page.
// All authenticated traffic goes through DivarSession (static/js/session.js):
// authFetch handles the in-memory token, the single refresh/retry on 401, and
// the redirect to /login. This script contains no token, refresh, redirect, or
// tenant-identifier logic — the JWT carries the tenant; no other input can.
(() => {
    "use strict";

    const LIST_URL = "/api/v1/seller/products";
    const IMPORT_URL = "/api/v1/seller/products/import";

    const $ = (selector) => document.querySelector(selector);

    const els = {
        loading: $("#products-loading"),
        errorBox: $("#products-error"),
        errorText: $("#products-error-text"),
        data: $("#products-data"),
        search: $("#product-search"),
        searchForm: $("#product-search-form"),
        addToggle: $("#product-add-button"),
        form: $("#product-form"),
        formTitle: $("#product-form-title"),
        formName: $("#product-name"),
        formPrice: $("#product-price"),
        formError: $("#product-form-error"),
        formSubmit: $("#product-form-submit"),
        formCancel: $("#product-form-cancel"),
        tableWrap: $("#products-table-wrap"),
        tbody: $("#products-tbody"),
        empty: $("#products-empty"),
        emptyText: $("#products-empty-text"),
        pagination: $("#products-pagination"),
        importToggle: $("#import-toggle"),
        importSection: $("#import-section"),
        importForm: $("#import-form"),
        importFile: $("#import-file"),
        importError: $("#import-error"),
        importFeedback: $("#import-feedback"),
        importCancel: $("#import-cancel"),
        logoutButton: $("[data-products-logout]"),
    };

    let query = "";
    let page = 1;
    let pageCount = 1;
    let editingId = null;
    let searchDebounce = null;

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

    // Western digits with separators for prices (scannable columns, §3.2.4);
    // Persian digits for page numbers and dates.
    const formatPrice = (value) => Number(value).toLocaleString("en-US");
    const formatPage = (value) => Number(value).toLocaleString("fa-IR");
    const formatDateTime = (iso) =>
        new Date(iso).toLocaleString("fa-IR", { dateStyle: "short", timeStyle: "short" });

    const cell = (text, className, label) => {
        const td = document.createElement("td");
        if (className) {
            td.className = className;
        }
        if (label) {
            // The label powers the deliberate stacked mobile representation
            // (see .table-stack in main.css); invisible on desktop.
            td.setAttribute("data-label", label);
        }
        td.textContent = text;
        return td;
    };

    const actionButton = (label, handler) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-sm";
        button.textContent = label;
        button.addEventListener("click", handler);
        return button;
    };

    const renderRows = (products) => {
        const rows = products.map((product) => {
            const tr = document.createElement("tr");
            tr.append(cell(product.item_name, "cell-name"));
            tr.append(cell(formatPrice(product.price), "num", "قیمت (تومان)"));
            tr.append(cell(formatDateTime(product.updated_at), null, "آخرین به‌روزرسانی"));

            const actions = document.createElement("td");
            actions.className = "cell-actions";
            actions.append(actionButton("ویرایش", () => startEdit(product)));
            actions.append(actionButton("حذف", () => removeProduct(product)));
            tr.append(actions);
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
            if (query) {
                params.set("q", query);
            }
            params.set("page", String(targetPage));
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}?${params.toString()}`
            );
            if (!response.ok) {
                // A 401 with a failed refresh already redirected via session.js.
                showListError("بارگذاری محصولات انجام نشد. دوباره تلاش کنید.");
                return;
            }
            const data = await response.json();
            page = data.page;
            pageCount = data.page_count;
            els.loading.hidden = true;
            els.data.hidden = false;
            if (data.total === 0) {
                els.emptyText.textContent = query
                    ? "محصولی با این عبارت پیدا نشد."
                    : "هنوز محصولی ثبت نشده است.";
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

    // ---- add / edit (one form, two modes; no modal library) ----------------

    const closeForm = () => {
        editingId = null;
        els.form.reset();
        els.formTitle.textContent = "افزودن محصول";
        els.formSubmit.textContent = "افزودن";
        setAlert(els.formError, null);
        els.form.hidden = true;
        els.addToggle.setAttribute("aria-expanded", "false");
    };

    const openForm = () => {
        setAlert(els.formError, null);
        els.form.hidden = false;
        els.addToggle.setAttribute("aria-expanded", "true");
        els.formName.focus();
    };

    const startAdd = () => {
        editingId = null;
        els.form.reset();
        els.formTitle.textContent = "افزودن محصول";
        els.formSubmit.textContent = "افزودن";
        openForm();
    };

    const startEdit = (product) => {
        editingId = product.id;
        els.formName.value = product.item_name;
        els.formPrice.value = String(product.price);
        els.formTitle.textContent = "ویرایش محصول";
        els.formSubmit.textContent = "ذخیرهٔ تغییرات";
        openForm();
    };

    els.form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const wasEditing = editingId !== null;
        const payload = {
            item_name: els.formName.value.trim(),
            price: Number(els.formPrice.value),
        };
        const options = {
            method: wasEditing ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        };
        const url = wasEditing ? `${LIST_URL}/${editingId}` : LIST_URL;
        try {
            const response = await window.DivarSession.authFetch(url, options);
            if (response.ok) {
                closeForm();
                await load(wasEditing ? page : 1);
            } else if (response.status === 409) {
                // The server deliberately does not say which product conflicts.
                setAlert(els.formError, "محصولی با این نام از قبل در فهرست شما ثبت شده است.");
            } else if (response.status === 422) {
                setAlert(els.formError, "نام محصول و قیمت معتبر وارد کنید.");
            } else {
                setAlert(els.formError, "ذخیرهٔ محصول انجام نشد. دوباره تلاش کنید.");
            }
        } catch {
            setAlert(els.formError, "ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        }
    });

    // ---- delete (explicit confirmation; never a single silent click) -------

    const removeProduct = async (product) => {
        const confirmed = window.confirm(
            `محصول «${product.item_name}» حذف شود؟ این کار بازگشت ندارد.`
        );
        if (!confirmed) {
            return;
        }
        try {
            const response = await window.DivarSession.authFetch(
                `${LIST_URL}/${product.id}`,
                { method: "DELETE" }
            );
            if (response.status === 204) {
                // Deleting the last row of a non-first page steps back a page.
                const target = els.tbody.rows.length === 1 && page > 1 ? page - 1 : page;
                await load(target);
            } else if (!response.ok) {
                showListError("حذف محصول انجام نشد. دوباره تلاش کنید.");
            }
        } catch {
            showListError("ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        }
    };

    // ---- import (replace-all acknowledged twice: visible warning + confirm) -

    const setImportOpen = (open) => {
        els.importSection.hidden = !open;
        els.importToggle.setAttribute("aria-expanded", String(open));
        if (open) {
            els.importFile.focus();
        }
    };

    els.importForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        setAlert(els.importError, null);
        setAlert(els.importFeedback, null);
        const file = els.importFile.files[0];
        if (!file) {
            setAlert(els.importError, "ابتدا یک فایل اکسل انتخاب کنید.");
            return;
        }
        // The replace-all warning is also permanently visible above the form;
        // this confirm makes the destructive step explicit before sending.
        const confirmed = window.confirm(
            "ورود فایل همهٔ محصولات فعلی شما را حذف و با محتوای فایل جایگزین می‌کند. ادامه می‌دهید؟"
        );
        if (!confirmed) {
            return;
        }
        const formData = new FormData();
        formData.append("file", file);
        try {
            const response = await window.DivarSession.authFetch(IMPORT_URL, {
                method: "POST",
                body: formData,
            });
            if (response.ok) {
                const data = await response.json();
                els.importForm.reset();
                setAlert(
                    els.importFeedback,
                    `ورود انجام شد و ${formatPage(data.rows_loaded)} محصول بارگذاری شد.`
                );
                await load(1);
            } else if (response.status === 413) {
                setAlert(els.importError, "حجم فایل بیشتر از حد مجاز (۵ مگابایت) است.");
            } else if (response.status === 400) {
                setAlert(els.importError, "فایل پذیرفته نشد. یک فایل اکسل معتبر با ستون‌های product و price انتخاب کنید.");
            } else {
                setAlert(els.importError, "ورود فایل انجام نشد. دوباره تلاش کنید.");
            }
        } catch {
            setAlert(els.importError, "ارتباط با سرور برقرار نشد. اتصال خود را بررسی کنید.");
        }
    });

    // ---- wiring -------------------------------------------------------------

    els.search.addEventListener("input", () => {
        window.clearTimeout(searchDebounce);
        searchDebounce = window.setTimeout(() => {
            query = els.search.value.trim();
            load(1);
        }, 250);
    });

    els.searchForm.addEventListener("submit", (event) => {
        // Search reacts to input already; Enter must not reload the page.
        event.preventDefault();
        window.clearTimeout(searchDebounce);
        query = els.search.value.trim();
        load(1);
    });

    els.addToggle.addEventListener("click", startAdd);
    els.formCancel.addEventListener("click", closeForm);
    els.importToggle.addEventListener("click", () => {
        setImportOpen(els.importSection.hidden);
    });
    els.importCancel.addEventListener("click", () => {
        setImportOpen(false);
    });
    els.logoutButton?.addEventListener("click", () => {
        window.DivarSession.logout();
    });

    load();
})();
