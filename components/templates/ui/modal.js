/* Modal helpers — loaded once per page when any modal component is used.
   Contract: the modal element keeps `flex` permanently; visibility is
   controlled by `hidden` alone (hidden wins over flex in Tailwind order),
   so legacy code that toggles only `hidden` stays compatible. */
(function () {
    if (window.openModal) return;

    window.openModal = function (id) {
        var modal = document.getElementById(id);
        if (!modal) return;
        modal.classList.add('flex');
        modal.classList.remove('hidden');
        var focusable = modal.querySelector('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (focusable) focusable.focus();
        if (document.activeElement && !modal.contains(document.activeElement)) {
            modal.dataset.returnFocusId = document.activeElement.id || '';
        }
    };

    window.closeModal = function (id) {
        var modal = document.getElementById(id);
        if (!modal) return;
        modal.classList.add('hidden');
    };

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            document.querySelectorAll('[role="dialog"]:not(.hidden)').forEach(function (m) {
                closeModal(m.id);
            });
        }
    });

    document.addEventListener('click', function (e) {
        document.querySelectorAll('[role="dialog"]:not(.hidden)').forEach(function (m) {
            if (e.target === m) closeModal(m.id);
        });
    });
})();
