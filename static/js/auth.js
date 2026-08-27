(() => {
    "use strict";

    const PHONE_STORAGE_KEY = "divar_auth_phone";

    const setHidden = (element, hidden) => {
        if (element) {
            element.hidden = hidden;
        }
    };

    const setMessage = (element, message) => {
        if (!element) {
            return;
        }
        element.textContent = message;
        setHidden(element, !message);
        if (element.id === "otp-error") {
            element.closest(".field")?.classList.toggle("has-error", Boolean(message));
        }
    };

    const setButtonBusy = (button, busy, busyText, idleText) => {
        button.disabled = busy;
        button.setAttribute("aria-disabled", String(busy));
        button.textContent = busy ? busyText : idleText;
    };

    const parseResponse = async (response) => {
        try {
            return await response.json();
        } catch {
            return {};
        }
    };

    const postJSON = (url, body) => fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });

    const normalizePhone = (value) => value.trim().replace(/[\s-]/g, "");
    const validPhone = (value) => /^09\d{9}$/.test(value);
    const validCode = (value) => /^\d{4,8}$/.test(value);

    const setupLogin = () => {
        const form = document.querySelector("[data-auth-form='request']");
        if (!form) {
            return;
        }

        const phoneInput = document.querySelector("#phone-number");
        const submitButton = form.querySelector("button[type='submit']");
        const feedback = document.querySelector("#login-feedback");
        let requestInFlight = false;

        submitButton.disabled = false;
        submitButton.setAttribute("aria-disabled", "false");

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (requestInFlight) {
                return;
            }

            const phoneNumber = normalizePhone(phoneInput.value);
            setMessage(feedback, "");
            if (!validPhone(phoneNumber)) {
                setMessage(feedback, "شمارهٔ تلفن را به‌صورت ۱۱ رقم و با ۰۹ وارد کنید.");
                phoneInput.focus();
                return;
            }

            requestInFlight = true;
            setButtonBusy(submitButton, true, "در حال ارسال...", "ارسال کد ورود");
            setMessage(feedback, "در حال ارسال کد ورود...");

            try {
                const response = await postJSON("/auth/otp/request", { phone_number: phoneNumber });
                await parseResponse(response);
                if (response.ok) {
                    sessionStorage.setItem(PHONE_STORAGE_KEY, phoneNumber);
                    window.location.assign("/login/otp");
                    return;
                }
                if (response.status === 422) {
                    setMessage(feedback, "شمارهٔ تلفن واردشده معتبر نیست.");
                } else if (response.status === 429) {
                    setMessage(feedback, "درخواست‌های زیادی ارسال شده است. کمی بعد دوباره تلاش کنید.");
                } else if (response.status === 503) {
                    setMessage(feedback, "ارسال پیامک در حال حاضر ممکن نیست. کمی بعد دوباره تلاش کنید.");
                } else {
                    setMessage(feedback, "ارسال کد ورود انجام نشد. دوباره تلاش کنید.");
                }
            } catch {
                setMessage(feedback, "ارتباط با سرور برقرار نشد. اتصال خود را بررسی و دوباره تلاش کنید.");
            } finally {
                requestInFlight = false;
                setButtonBusy(submitButton, false, "در حال ارسال...", "ارسال کد ورود");
            }
        });
    };

    const setupOTP = () => {
        const form = document.querySelector("[data-auth-form='verify']");
        if (!form) {
            return;
        }

        const phoneNumber = sessionStorage.getItem(PHONE_STORAGE_KEY);
        const phoneContext = document.querySelector("#phone-context");
        const codeInput = document.querySelector("#otp-code");
        const submitButton = form.querySelector("button[type='submit']");
        const feedback = document.querySelector("#otp-feedback");
        const error = document.querySelector("#otp-error");
        const expired = document.querySelector("#otp-expired");
        const rateLimit = document.querySelector("#otp-rate-limit");
        const retry = document.querySelector("#otp-retry");
        const retryButton = document.querySelector("#otp-retry-button");
        const loading = document.querySelector("#otp-loading");
        const success = document.querySelector("#otp-success");
        let requestInFlight = false;

        const clearFeedback = () => {
            for (const element of [error, expired, rateLimit, retry, loading, success]) {
                setMessage(element, "");
            }
            setHidden(retryButton, true);
            setHidden(feedback, true);
        };

        const showFeedback = (element, message) => {
            clearFeedback();
            setHidden(feedback, false);
            setMessage(element, message);
        };

        if (!phoneNumber || !validPhone(phoneNumber)) {
            form.hidden = true;
            showFeedback(retry, "شمارهٔ تلفن برای تأیید در دسترس نیست. به صفحهٔ ورود بازگردید.");
            return;
        }

        phoneContext.textContent = `کد ارسال‌شده به ${phoneNumber} را وارد کنید.`;
        submitButton.disabled = false;
        submitButton.setAttribute("aria-disabled", "false");

        const requestNewCode = async () => {
            if (requestInFlight) {
                return;
            }
            requestInFlight = true;
            retryButton.disabled = true;
            showFeedback(loading, "در حال درخواست کد جدید...");
            try {
                const response = await postJSON("/auth/otp/request", { phone_number: phoneNumber });
                await parseResponse(response);
                if (response.ok) {
                    showFeedback(success, "کد جدید ارسال شد.");
                } else if (response.status === 429) {
                    showFeedback(rateLimit, "برای درخواست کد جدید کمی صبر کنید.");
                } else if (response.status === 503) {
                    showFeedback(retry, "ارسال پیامک ممکن نیست. کمی بعد دوباره تلاش کنید.");
                    setHidden(retryButton, false);
                } else {
                    showFeedback(retry, "درخواست کد جدید انجام نشد. دوباره تلاش کنید.");
                    setHidden(retryButton, false);
                }
            } catch {
                showFeedback(retry, "ارتباط با سرور برقرار نشد. دوباره تلاش کنید.");
                setHidden(retryButton, false);
            } finally {
                requestInFlight = false;
                retryButton.disabled = false;
            }
        };

        retryButton.addEventListener("click", requestNewCode);

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (requestInFlight) {
                return;
            }

            const code = codeInput.value.trim();
            clearFeedback();
            if (!validCode(code)) {
                showFeedback(error, "کد ورود را فقط با رقم و بدون فاصله وارد کنید.");
                codeInput.focus();
                return;
            }

            requestInFlight = true;
            setButtonBusy(submitButton, true, "در حال بررسی...", "تأیید کد");
            showFeedback(loading, "در حال بررسی کد ورود...");

            try {
                const response = await postJSON("/auth/otp/verify", {
                    phone_number: phoneNumber,
                    code,
                });
                const data = await parseResponse(response);
                if (response.ok && typeof data.access_token === "string") {
                    // In-memory only: hand the token to the shared session module
                    // (static/js/session.js), never to web storage.
                    window.DivarSession.setAccessToken(data.access_token);
                    sessionStorage.removeItem(PHONE_STORAGE_KEY);
                    form.hidden = true;
                    showFeedback(success, "ورود با موفقیت انجام شد. بخش فروشندگان هنوز آماده نشده است.");
                    return;
                }
                if (response.status === 400) {
                    showFeedback(expired, "کد ورود نامعتبر یا منقضی شده است.");
                    setHidden(retryButton, false);
                } else if (response.status === 422) {
                    showFeedback(error, "شمارهٔ تلفن یا کد ورود معتبر نیست.");
                } else if (response.status === 429) {
                    showFeedback(rateLimit, "تلاش‌های زیادی انجام شده است. کمی بعد دوباره تلاش کنید.");
                } else {
                    showFeedback(retry, "بررسی کد ورود انجام نشد. دوباره تلاش کنید.");
                    setHidden(retryButton, false);
                }
            } catch {
                showFeedback(retry, "ارتباط با سرور برقرار نشد. دوباره تلاش کنید.");
                setHidden(retryButton, false);
            } finally {
                requestInFlight = false;
                setButtonBusy(submitButton, false, "در حال بررسی...", "تأیید کد");
            }
        });
    };

    setupLogin();
    setupOTP();
})();
