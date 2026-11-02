/* Click acknowledgement for every button on the hand-built pages.
 *
 * These pages are plain HTML, so unlike the Material web app their buttons had
 * no press feedback - a tap that triggered a download or a slow fetch looked
 * like nothing had happened, and people tapped again. This gives every
 * interactive control the same unmistakable "yes, I got that" pulse: it dims,
 * shrinks slightly and gains a faint ring the instant it is pressed.
 *
 * Injected into every page's <head> centrally (main.py), so it covers all the
 * pages at once and keeps working as new buttons are added.
 *
 * Design notes:
 *  - The cue is applied on pointerdown in the capture phase, so it shows even
 *    for a control that stops propagation or navigates away a moment later.
 *  - brightness()/scale() work on a button of any colour, so no page needs to
 *    declare a "pressed" colour of its own; specificity is kept out of the way
 *    with :where(), and the pulse itself wins with !important.
 *  - A floor of ~180ms means a quick tap still flashes long enough to see.
 */
(function () {
  if (window.__uiFeedback) return;          // injected once, even if double-linked
  window.__uiFeedback = true;

  var SELECTOR = 'button, .btn, [role="button"], a.btn, summary, [data-t], [onclick]';

  var style = document.createElement('style');
  style.textContent =
    ':where(button,.btn,[role="button"],a.btn,summary,[data-t],[onclick]){' +
    'transition:filter .12s ease,transform .08s ease,box-shadow .12s ease;' +
    '-webkit-tap-highlight-color:transparent;}' +
    /* hold-to-press, pure CSS, for anyone holding the pointer down */
    ':where(button,.btn,[role="button"],a.btn,[data-t]):active{transform:scale(.96);}' +
    /* the click pulse, added by JS - wins over any page rule */
    '.ui-pressed{filter:brightness(.82) saturate(1.1)!important;transform:scale(.96)!important;' +
    'box-shadow:0 0 0 3px rgba(128,128,128,.28)!important;}' +
    '@media (prefers-reduced-motion:reduce){.ui-pressed{transform:none!important;}}';
  (document.head || document.documentElement).appendChild(style);

  function pressable(el) {
    if (!el) return null;
    if (el.disabled || el.getAttribute && el.getAttribute('aria-disabled') === 'true') return null;
    return el;
  }

  function pulse(el) {
    el.classList.add('ui-pressed');
    clearTimeout(el.__uiT);
    el.__uiT = setTimeout(function () { el.classList.remove('ui-pressed'); }, 190);
  }

  // Capture phase so nothing can swallow it before we see it.
  document.addEventListener('pointerdown', function (e) {
    var el = pressable(e.target.closest && e.target.closest(SELECTOR));
    if (el) pulse(el);
  }, true);

  // Keyboard activation (Enter/Space on a focused button) deserves the same nod.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var el = pressable(e.target.closest && e.target.closest(SELECTOR));
    if (el) pulse(el);
  }, true);
})();
