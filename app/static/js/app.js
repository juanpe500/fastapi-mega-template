// Minimal client helper. The template is server-rendered and works without JS.
// Handles: CSRF header on writes, transparent token refresh, cookie consent,
// and the unread-notification badge.
(function () {
  "use strict";

  function getCookie(name) {
    return document.cookie
      .split("; ")
      .map(function (c) { return c.split("="); })
      .reduce(function (acc, kv) { return kv[0] === name ? decodeURIComponent(kv[1]) : acc; }, "");
  }

  // --- fetch wrapper: CSRF header + one automatic refresh on 401 -------------
  const UNSAFE = ["POST", "PUT", "PATCH", "DELETE"];
  const _fetch = window.fetch;
  let refreshing = null;

  window.fetch = async function (input, init) {
    init = init || {};
    const method = (init.method || "GET").toUpperCase();

    if (UNSAFE.indexOf(method) !== -1) {
      const token = getCookie("csrf");
      if (token) {
        init.headers = new Headers(init.headers || {});
        if (!init.headers.has("X-CSRF-Token")) init.headers.set("X-CSRF-Token", token);
      }
    }

    let res = await _fetch(input, init);
    if (res.status === 401 && !String(input).includes("/auth/refresh")) {
      refreshing = refreshing || _fetch("/auth/refresh", { method: "POST" });
      const r = await refreshing;
      refreshing = null;
      if (r.ok || r.status === 204) res = await _fetch(input, init);
    }
    return res;
  };

  // --- cookie consent -------------------------------------------------------
  const banner = document.getElementById("cookie-banner");
  if (banner) {
    banner.addEventListener("click", function (e) {
      const choice = e.target.getAttribute("data-consent");
      if (!choice) return;
      // 1 year; "all" enables analytics on the next render, "essential" does not.
      document.cookie =
        "cookie_consent=" + choice + ";path=/;max-age=" + 60 * 60 * 24 * 365 + ";SameSite=Lax";
      banner.remove();
      if (choice === "all") location.reload();
    });
  }

  // --- unread notification badge -------------------------------------------
  const link = document.getElementById("notif-link");
  if (link) {
    _fetch("/api/notifications/unread-count")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.count > 0) {
          document.getElementById("notif-count").textContent = " (" + data.count + ")";
        }
      })
      .catch(function () { /* badge is decorative; ignore failures */ });
  }
})();
