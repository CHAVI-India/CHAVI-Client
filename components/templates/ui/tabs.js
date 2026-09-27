/* Tabs helper — chaviSwitchTab('pane-id') toggles [data-tab-pane] panels
   and marks the clicked [data-tab-target] button active. Loaded once per
   page when the tabs component is used with target-based tabs. */
(function () {
    if (window.chaviSwitchTab) return;

    window.chaviSwitchTab = function (targetId) {
        var btn = document.querySelector('[data-tab-target="' + targetId + '"]');
        if (!btn) return;
        var nav = btn.closest('[role="tablist"]');
        if (nav) {
            nav.querySelectorAll('[role="tab"]').forEach(function (t) {
                var active = t === btn;
                t.setAttribute('aria-selected', active ? 'true' : 'false');
                t.classList.toggle('border-chavi-primary', active);
                t.classList.toggle('text-chavi-primary', active);
                t.classList.toggle('border-transparent', !active);
                t.classList.toggle('text-gray-500', !active);
            });
        }
        document.querySelectorAll('[data-tab-pane]').forEach(function (pane) {
            pane.classList.toggle('hidden', pane.dataset.tabPane !== targetId);
        });
    };
})();
