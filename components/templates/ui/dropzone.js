/* Dropzone — shared drag-and-drop handler for all [data-dropzone] areas. */
(function () {
    function prevent(e) { e.preventDefault(); e.stopPropagation(); }

    function highlight(zone, on) {
        zone.classList.toggle('border-chavi-primary', on);
        zone.classList.toggle('bg-chavi-primary-50', on);
        zone.classList.toggle('border-gray-300', !on);
    }

    function showFiles(zone, files) {
        var label = zone.querySelector('[data-dropzone-filename]');
        if (!label || !files || !files.length) return;
        var parts = [];
        for (var i = 0; i < files.length; i++) {
            var mb = (files[i].size / 1024 / 1024).toFixed(2);
            parts.push(files[i].name + ' (' + mb + ' MB)');
        }
        label.textContent = 'Selected: ' + parts.join(', ');
    }

    document.querySelectorAll('[data-dropzone]').forEach(function (zone) {
        var input = document.getElementById(zone.dataset.input);
        if (!input) return;

        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function (ev) {
            zone.addEventListener(ev, prevent, false);
        });
        ['dragenter', 'dragover'].forEach(function (ev) {
            zone.addEventListener(ev, function () { highlight(zone, true); }, false);
        });
        ['dragleave', 'drop'].forEach(function (ev) {
            zone.addEventListener(ev, function () { highlight(zone, false); }, false);
        });

        zone.addEventListener('drop', function (e) {
            if (e.dataTransfer.files.length) {
                input.files = e.dataTransfer.files;
                showFiles(zone, input.files);
            }
        });

        input.addEventListener('change', function () {
            showFiles(zone, input.files);
        });
    });
})();
