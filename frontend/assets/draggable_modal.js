/**
 * draggable_modal.js
 * Makes Bootstrap modals with class "tech-add-modal-dialog" or
 * "tech-config-modal-dialog" draggable by their header.
 */
(function () {
    'use strict';

    const DRAGGABLE_CLASSES = [
        'tech-add-modal-dialog',
        'tech-config-modal-dialog',
    ];

    function makeDraggable(modalEl) {
        const dialog = modalEl.querySelector('.modal-dialog');
        const header = modalEl.querySelector('.modal-header');
        if (!dialog || !header) return;

        let startX = 0, startY = 0, origLeft = 0, origTop = 0;
        let dragging = false;

        header.addEventListener('mousedown', function (e) {
            // Only drag on left-button, ignore close button clicks
            if (e.button !== 0) return;
            if (e.target.closest('.btn-close')) return;

            dragging = true;
            const rect = dialog.getBoundingClientRect();
            startX = e.clientX;
            startY = e.clientY;
            origLeft = rect.left;
            origTop = rect.top;

            // Switch dialog to absolute positioning within the fixed modal overlay
            dialog.style.position = 'absolute';
            dialog.style.margin = '0';
            dialog.style.left = origLeft + 'px';
            dialog.style.top = origTop + 'px';
            dialog.style.transform = 'none';

            document.body.classList.add('modal-dragging');

            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            dialog.style.left = (origLeft + dx) + 'px';
            dialog.style.top = (origTop + dy) + 'px';
        });

        document.addEventListener('mouseup', function () {
            if (dragging) {
                dragging = false;
                document.body.classList.remove('modal-dragging');
            }
        });
    }

    function resetPosition(modalEl) {
        const dialog = modalEl.querySelector('.modal-dialog');
        if (!dialog) return;
        // Reset to centered on next open
        dialog.style.position = '';
        dialog.style.margin = '';
        dialog.style.left = '';
        dialog.style.top = '';
        dialog.style.transform = '';
    }

    function initModal(modalEl) {
        makeDraggable(modalEl);
        // Reset position each time the modal is hidden so it re-centers on next open
        modalEl.addEventListener('hidden.bs.modal', function () {
            resetPosition(modalEl);
        });
    }

    function attachToExisting() {
        DRAGGABLE_CLASSES.forEach(function (cls) {
            document.querySelectorAll('.' + cls).forEach(function (el) {
                if (!el.dataset.draggableInit) {
                    el.dataset.draggableInit = '1';
                    initModal(el);
                }
            });
        });
    }

    // Attach once DOM is ready and re-check whenever Dash re-renders
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachToExisting);
    } else {
        attachToExisting();
    }

    // MutationObserver to catch Dash's dynamic renders
    const observer = new MutationObserver(attachToExisting);
    observer.observe(document.body, { childList: true, subtree: true });
})();
