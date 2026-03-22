/*
 * Prevent mouse wheel from accidentally changing number input values.
 *
 * In HTML5, a focused <input type="number"> increments/decrements its
 * value by `step` on each scroll tick.  For financial inputs this is
 * almost always unintended — the user is just trying to scroll the page.
 *
 * Fix: blur the active number input before the scroll reaches it, so the
 * browser never applies the step change.  Uses a passive listener to avoid
 * blocking smooth scrolling elsewhere on the page.
 */
window.addEventListener('wheel', function (e) {
    if (
        document.activeElement &&
        document.activeElement.tagName === 'INPUT' &&
        document.activeElement.type === 'number'
    ) {
        document.activeElement.blur();
    }
}, { passive: true });
