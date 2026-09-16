/* Sign-in handling shared by the /tacho office pages.
 * Office staff are recognised by their DH FleetView session (cookie, sent
 * automatically). When the API says a sign-in is needed, show one clear prompt
 * instead of a page full of failed requests. */
(function () {
  var nativeFetch = window.fetch.bind(window);
  var shown = false;

  function prompt(detail) {
    if (shown || !document.body) return;
    shown = true;
    var manager = detail.error === "not_manager";
    var box = document.createElement("div");
    box.setAttribute("role", "dialog");
    box.style.cssText = "position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:20px;background:rgba(8,12,24,.55)";
    box.innerHTML =
      '<div style="max-width:420px;width:100%;background:var(--card,#fff);color:var(--fg,#111);border:1px solid var(--line,#ddd);border-radius:16px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.3);font:15px/1.5 system-ui,sans-serif">' +
      '<div style="font-size:18px;font-weight:700;margin-bottom:6px">' + (manager ? "No access" : "Sign in required") + "</div>" +
      '<p style="margin:0 0 16px;color:var(--mut,#555)">' +
      (manager ? "Your DH FleetView account doesn't have access to the office compliance tools. Ask an administrator."
               : "Sign in to DH FleetView, then come back to this page.") + "</p>" +
      (manager ? "" : '<a href="/" style="display:block;text-align:center;padding:12px;border-radius:10px;background:var(--acc,#0369a1);color:var(--on-acc,#fff);text-decoration:none;font-weight:600">Sign in to DH FleetView</a>') +
      '<button type="button" style="display:block;width:100%;margin-top:10px;padding:10px;border-radius:10px;border:1px solid var(--line,#ddd);background:transparent;color:inherit;cursor:pointer">I\'ve signed in — reload</button>' +
      "</div>";
    box.querySelector("button").onclick = function () { location.reload(); };
    document.body.appendChild(box);
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var sameOrigin = url.indexOf("://") === -1 || url.indexOf(location.origin) === 0;
    return nativeFetch(input, init).then(function (res) {
      if (sameOrigin && (res.status === 401 || res.status === 403)) {
        res.clone().json().then(function (body) {
          var d = body && body.detail;
          if (d && (d.error === "login_required" || d.error === "not_manager")) {
            if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { prompt(d); });
            else prompt(d);
          }
        }).catch(function () {});
      }
      return res;
    });
  };
})();
