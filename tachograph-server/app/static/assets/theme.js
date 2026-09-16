/* DH FleetView light/dark theme switch, shared by every /tacho page.
 * The choice is stored under "dhfv-theme" on this origin, the same key the main
 * DHFleetView web app reads, so switching in one place switches everywhere.
 * With no stored choice the page follows the device setting. */
(function () {
  var KEY = "dhfv-theme";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function stored() { try { var v = localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : null; } catch (e) { return null; } }
  function effective() { return stored() || (media && media.matches ? "dark" : "light"); }
  function apply() {
    var t = effective();
    root.setAttribute("data-theme", t);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "dark" ? "#0b1220" : "#ffffff");
    var btns = document.querySelectorAll("[data-theme-toggle]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].innerHTML = t === "dark" ? MOON : SUN;
      btns[i].setAttribute("aria-label", t === "dark" ? "Switch to light mode" : "Switch to dark mode");
      btns[i].title = btns[i].getAttribute("aria-label");
    }
    document.dispatchEvent(new CustomEvent("themechange", { detail: { theme: t } }));
  }
  function set(t) { try { localStorage.setItem(KEY, t); } catch (e) {} apply(); }
  function toggle() { set(effective() === "dark" ? "light" : "dark"); }

  var SUN = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><circle cx="12" cy="12" r="4.5" fill="#f5a524"/><g stroke="#f5a524" stroke-width="2" stroke-linecap="round"><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></g></svg>';
  var MOON = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1z" fill="#a5b4fc"/></svg>';

  apply(); // before first paint: this script sits in <head>
  if (media && media.addEventListener) media.addEventListener("change", function () { if (!stored()) apply(); });
  window.addEventListener("storage", function (e) { if (e.key === KEY) apply(); });

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-theme-toggle]");
    if (b) { e.preventDefault(); toggle(); }
  });

  // Pages that don't place their own toggle get one in their <header> (or floating).
  document.addEventListener("DOMContentLoaded", function () {
    if (!document.querySelector("[data-theme-toggle]") && !document.body.hasAttribute("data-no-theme-toggle")) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "theme-toggle";
      b.setAttribute("data-theme-toggle", "");
      var header = document.querySelector("body > header, header");
      var display = header ? getComputedStyle(header).display : "";
      if (header && (display === "flex" || display === "inline-flex")) {
        var hs = getComputedStyle(header);
        if (hs.justifyContent === "space-between" && header.children.length >= 2) {
          // Keep the header's last item on the right: group it with the toggle.
          var group = document.createElement("span");
          group.style.cssText = "display:inline-flex;align-items:center;gap:12px";
          header.appendChild(group);
          group.appendChild(header.children[header.children.length - 2]);
          group.appendChild(b);
        } else { b.classList.add("in-header"); header.appendChild(b); }
      }
      else { b.classList.add("floating"); document.body.appendChild(b); }
    }
    apply();
  });

  window.dhfvTheme = { get: effective, set: set, toggle: toggle };
})();
