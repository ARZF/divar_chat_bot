// Phase 3 step 12: shared seller-session module for protected pages.
//
// Protected HTML routes have no server-side auth gate: the refresh cookie is
// scoped to path=/auth, so a plain GET of a protected page never carries it
// and a server-side cookie check cannot tell an anonymous browser from a
// logged-in one. Protection is therefore this module's contract — a protected
// page loads this script and fetches its data only through authFetch():
//
//   1. use the in-memory access token if this document already has one;
//   2. on a 401, call POST /auth/refresh exactly once (single-flight: the
//      refresh token rotates, so a concurrent second call would reuse a
//      consumed token and fail);
//   3. retry the original request once with the new token;
//   4. if the refresh or the retry fails, redirect to /login — never loop.
//
// The access token lives only in this closure; it is never written to web
// storage, URLs, or the DOM, and the refresh cookie stays HttpOnly.
(() => {
    "use strict";

    let accessToken = null;
    let refreshInFlight = null;
    let redirectingToLogin = false;

    const redirectToLogin = () => {
        if (!redirectingToLogin) {
            redirectingToLogin = true;
            window.location.assign("/login");
        }
    };

    const sendWithToken = (url, options) => {
        const headers = new Headers(options.headers);
        if (accessToken) {
            headers.set("Authorization", `Bearer ${accessToken}`);
        }
        return fetch(url, { ...options, headers, credentials: "same-origin" });
    };

    const refreshOnce = async () => {
        try {
            const response = await fetch("/auth/refresh", {
                method: "POST",
                credentials: "same-origin",
            });
            if (!response.ok) {
                return false;
            }
            const data = await response.json();
            if (typeof data.access_token !== "string") {
                return false;
            }
            accessToken = data.access_token;
            return true;
        } catch {
            // A network failure counts as a failed refresh: leave, do not retry.
            return false;
        }
    };

    const refreshSingleFlight = () => {
        if (!refreshInFlight) {
            refreshInFlight = refreshOnce().finally(() => {
                refreshInFlight = null;
            });
        }
        return refreshInFlight;
    };

    const authFetch = async (url, options = {}) => {
        let response = await sendWithToken(url, options);
        if (response.status !== 401) {
            return response;
        }
        if (!(await refreshSingleFlight())) {
            redirectToLogin();
            return response;
        }
        response = await sendWithToken(url, options);
        if (response.status === 401) {
            redirectToLogin();
        }
        return response;
    };

    const logout = async () => {
        try {
            await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
        } catch {
            // Even if the call fails, leave the protected page.
        }
        accessToken = null;
        redirectToLogin();
    };

    window.DivarSession = {
        authFetch,
        logout,
        setAccessToken: (token) => {
            accessToken = token;
        },
    };
})();
