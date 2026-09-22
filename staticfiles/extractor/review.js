(function () {
    const form = document.getElementById('review-form');
    if (!form) return;
    const $ = window.jQuery;
    const errorBox = document.getElementById('review-load-error');
    const submit = form.querySelector('[data-review-submit]');
    if (!$ || !$.fn.select2) {
        errorBox.textContent = 'The review controls could not load. Reload the page before saving.';
        errorBox.hidden = false;
        return;
    }
    const cards = Array.from(form.querySelectorAll('[data-review-record]'));
    const states = new Map(cards.map(card => [card, {loading: false, error: false, version: 0}]));
    let dirty = false;
    let ready = false;

    function own(card, selector) {
        return Array.from(card.querySelectorAll(selector)).filter(el => el.closest('[data-review-record]') === card);
    }

    function operation(card) {
        return own(card, '[data-review-operation]')[0].value;
    }

    function setValue(control, value, label) {
        value = value == null ? '' : String(value);
        if (control.tagName === 'SELECT') {
            if (value && !Array.from(control.options).some(option => option.value === value)) {
                control.add(new Option(label || value, value));
            }
            control.value = value;
            if (label && value) control.selectedOptions[0].textContent = label;
            $(control).trigger('change.select2');
        } else {
            control.value = value;
        }
    }

    function fieldValue(wrap) {
        const control = wrap.querySelector('[data-field-id]');
        const action = wrap.querySelector('[data-field-action]').value;
        if (action !== 'apply') return {action, value: ''};
        const value = wrap.dataset.separateExtraction === 'true' && control.value === ''
            ? wrap.dataset.baseline : control.value;
        return {action, value};
    }

    function comparable(value, kind) {
        if (kind === 'boolean') return value.toLowerCase();
        if (['integer', 'decimal'].includes(kind) && /^[+-]?\d+(\.\d+)?$/.test(value)) {
            let [whole, fraction = ''] = value.replace(/^\+/, '').split('.');
            const negative = whole.startsWith('-');
            whole = whole.replace(/^-/, '').replace(/^0+(?=\d)/, '');
            fraction = fraction.replace(/0+$/, '');
            return (negative && (whole !== '0' || fraction) ? '-' : '') + whole + (fraction ? '.' + fraction : '');
        }
        return value;
    }

    function updateFieldStatus(wrap) {
        const {action, value} = fieldValue(wrap);
        const original = wrap.dataset.original;
        let text;
        if (action === 'preserve') text = 'Keep database value';
        else if (wrap.dataset.sourceState === 'unresolved') text = value ? 'Edited extracted value' : 'Unresolved lookup';
        else if (comparable(value, wrap.dataset.inputKind) === comparable(original, wrap.dataset.inputKind)) text = 'Accepted unchanged';
        else if (original === '') text = 'Filled missing value';
        else text = value === '' ? 'Cleared value' : 'Edited extracted value';
        wrap.querySelector('[data-field-status]').textContent = text;
    }

    function updateCounts() {
        const counts = {create: 0, update: 0, link: 0, skip: 0};
        cards.forEach(card => { counts[operation(card)] += 1; });
        document.getElementById('review-counts').textContent =
            `${counts.create} create · ${counts.update} update · ${counts.link} link · ${counts.skip} pending`;
        submit.disabled = !ready || cards.some(card => ['update', 'link'].includes(operation(card)) &&
            (states.get(card).loading || states.get(card).error));
    }

    function updateCard(card) {
        const mode = operation(card);
        const editing = mode === 'create' || mode === 'update';
        const existing = mode === 'update' || mode === 'link';
        own(card, '[data-target-wrap]')[0].hidden = !existing;
        own(card, '[data-review-target]')[0].disabled = !existing;
        own(card, '[data-parent-field]').forEach(select => {
            select.disabled = mode !== 'create';
            $(select).trigger('change.select2');
        });
        own(card, '[data-review-field-wrap]').forEach(wrap => {
            wrap.querySelectorAll('input, textarea, select, button').forEach(el => {
                if (el.type !== 'hidden') el.disabled = !editing;
            });
            wrap.querySelector('[data-preserve-field]').hidden = mode !== 'update';
            const select = wrap.querySelector('select');
            if (select) $(select).trigger('change.select2');
            updateFieldStatus(wrap);
        });
        const notice = own(card, '[data-record-notice]')[0];
        const state = states.get(card);
        notice.textContent = state.error && existing
            ? 'Could not load the selected database record. Select it again or reload before saving.'
            : mode === 'skip' ? 'Left pending. Edits to this record will not be saved.'
            : mode === 'link' ? 'The selected database record will be used without changing its values.'
            : mode === 'update' ? 'Blank values are preserved. Use Clear to remove a value. The existing parent cannot change.' : '';
        updateCounts();
    }

    async function options(card, parameters) {
        const url = new URL(form.dataset.optionsUrl, window.location.origin);
        url.search = new URLSearchParams({record_id: card.dataset.reviewRecord, ...parameters});
        const response = await fetch(url, {cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('Review choices unavailable');
        return response.json();
    }

    async function loadExisting(card) {
        const state = states.get(card);
        const version = ++state.version;
        const target = own(card, '[data-review-target]')[0];
        const needsValues = ['update', 'link'].includes(operation(card)) && target.value;
        state.loading = Boolean(needsValues);
        state.error = false;
        updateCard(card);
        let data = {fields: {}, parents: {}};
        try {
            if (needsValues) data = await options(card, {kind: 'values', selected_pk: target.value});
            if (version !== state.version) return;
            own(card, '[data-review-field-wrap]').forEach(wrap => {
                const control = wrap.querySelector('[data-field-id]');
                const current = data.fields[control.dataset.fieldId];
                wrap.querySelector('[data-database-wrap]').hidden = !current;
                wrap.querySelector('[data-database-value]').textContent = current ? current.text : '';
                if (wrap.dataset.separateExtraction !== 'true' && wrap.dataset.touched !== 'true') {
                    setValue(control, current ? current.value : wrap.dataset.baseline, current && current.text);
                    wrap.querySelector('[data-field-action]').value = current ? 'preserve' : 'apply';
                }
                updateFieldStatus(wrap);
            });
            own(card, '[data-parent-field]').forEach(select => {
                const value = data.parents[select.dataset.parentField];
                setValue(select, value ? `existing:${value}` : select.dataset.initialParent,
                         value ? `Existing parent (${value})` : undefined);
            });
        } catch (error) {
            if (version === state.version) state.error = true;
        } finally {
            if (version === state.version) {
                state.loading = false;
                updateCard(card);
            }
        }
    }

    function initializeSelect(select) {
        const card = select.closest('[data-review-record]');
        const kind = select.hasAttribute('data-lookup-field') ? 'lookup'
            : select.hasAttribute('data-review-target') ? 'target'
            : select.hasAttribute('data-parent-field') ? 'parent' : null;
        const config = {
            width: '100%', dropdownCssClass: 'review-select2-dropdown',
            placeholder: select.dataset.placeholder || undefined,
            allowClear: Boolean(select.dataset.placeholder), minimumResultsForSearch: 0,
        };
        if (kind) {
            const extractedParents = Array.from(select.options).filter(option => option.value.startsWith('record:'))
                .map(option => ({id: option.value, text: option.textContent}));
            let term = '';
            let page = 1;
            config.ajax = {
                url: form.dataset.optionsUrl, dataType: 'json', delay: 200, cache: false,
                data(params) {
                    term = params.term || '';
                    page = params.page || 1;
                    return {record_id: card.dataset.reviewRecord, kind,
                        field_id: select.dataset.fieldId || select.dataset.parentFieldId,
                        q: term, page};
                },
                processResults(data) {
                    if (kind !== 'parent') return data;
                    const results = data.results.map(option => ({...option, id: `existing:${option.id}`}));
                    if (page === 1) {
                        results.unshift(...extractedParents.filter(option => option.text.toLowerCase().includes(term.toLowerCase())));
                    }
                    return {...data, results};
                },
            };
        }
        $(select).select2(config);
    }

    function collect() {
        return {
            schema_version: 1,
            job_revision: Number(document.getElementById('review-job-revision').value),
            source_token: document.getElementById('review-source-token').value,
            records: cards.map(card => {
                const entry = {id: Number(card.dataset.reviewRecord), operation: operation(card),
                    target_pk: own(card, '[data-review-target]')[0].value, fields: {}, parents: {}};
                own(card, '[data-parent-field]').forEach(select => {
                    if (!select.value) return;
                    const colon = select.value.indexOf(':');
                    const kind = select.value.slice(0, colon);
                    const value = select.value.slice(colon + 1);
                    entry.parents[select.dataset.parentField] = kind === 'record'
                        ? {kind, record_id: Number(value)} : {kind, pk: value};
                });
                own(card, '[data-review-field-wrap]').forEach(wrap => {
                    entry.fields[wrap.querySelector('[data-field-id]').dataset.fieldId] = fieldValue(wrap);
                });
                return entry;
            }),
        };
    }

    function changed(event) {
        const control = event.target;
        const card = control.closest('[data-review-record]');
        if (!card) return;
        dirty = true;
        if (control.matches('[data-field-id]')) {
            const wrap = control.closest('[data-review-field-wrap]');
            wrap.dataset.touched = 'true';
            wrap.querySelector('[data-field-action]').value = 'apply';
            updateFieldStatus(wrap);
        }
        if (control.matches('[data-review-operation], [data-review-target]')) loadExisting(card);
        else updateCard(card);
    }

    form.addEventListener('input', event => { if (event.target.tagName !== 'SELECT') changed(event); });
    $(form).on('change', 'select', changed);
    form.addEventListener('click', event => {
        const button = event.target.closest('button');
        if (!button) return;
        if (button.matches('[data-expand-records], [data-collapse-records]')) {
            cards.forEach(card => { card.open = button.hasAttribute('data-expand-records'); });
            return;
        }
        const wrap = button.closest('[data-review-field-wrap]');
        if (!wrap) return;
        const control = wrap.querySelector('[data-field-id]');
        const action = wrap.querySelector('[data-field-action]');
        if (button.hasAttribute('data-clear-field')) {
            setValue(control, '');
            action.value = 'clear';
        } else if (button.hasAttribute('data-restore-field')) {
            wrap.dataset.baseline = wrap.dataset.original;
            setValue(control, wrap.dataset.separateExtraction === 'true' ? '' : wrap.dataset.original);
            action.value = 'apply';
        } else if (button.hasAttribute('data-preserve-field')) {
            setValue(control, '');
            action.value = 'preserve';
        } else return;
        wrap.dataset.touched = 'true';
        dirty = true;
        updateFieldStatus(wrap);
    });
    form.addEventListener('submit', event => {
        if (submit.disabled) { event.preventDefault(); return; }
        document.getElementById('review-payload').value = JSON.stringify(collect());
        dirty = false;
    });
    window.addEventListener('beforeunload', event => {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = '';
    });

    async function initialize() {
        cards.forEach(card => own(card, '[data-parent-field]').forEach(select => {
            select.dataset.initialParent = select.value;
        }));
        const posted = document.getElementById('posted-payload');
        if (posted) {
            const payload = JSON.parse(posted.textContent);
            (payload.records || []).forEach(entry => {
                const card = cards.find(item => item.dataset.reviewRecord === String(entry.id));
                if (!card) return;
                setValue(own(card, '[data-review-operation]')[0], entry.operation);
                setValue(own(card, '[data-review-target]')[0], entry.target_pk);
                own(card, '[data-parent-field]').forEach(select => {
                    const parent = (entry.parents || {})[select.dataset.parentField];
                    if (!parent) return;
                    const value = parent.kind === 'record' ? `record:${parent.record_id}` : `existing:${parent.pk}`;
                    setValue(select, value);
                    select.dataset.initialParent = value;
                });
                own(card, '[data-review-field-wrap]').forEach(wrap => {
                    const control = wrap.querySelector('[data-field-id]');
                    const field = (entry.fields || {})[control.dataset.fieldId];
                    if (!field) return;
                    const unchanged = wrap.dataset.separateExtraction === 'true' && String(field.value) === wrap.dataset.baseline;
                    setValue(control, unchanged || field.action !== 'apply' ? '' : field.value);
                    wrap.querySelector('[data-field-action]').value = field.action;
                    wrap.dataset.touched = 'true';
                });
            });
        }
        form.querySelectorAll('select').forEach(initializeSelect);
        await Promise.all(cards.map(loadExisting));
        ready = true;
        updateCounts();
    }
    initialize().catch(() => {
        errorBox.textContent = 'The review controls could not be restored. Reload the page before saving.';
        errorBox.hidden = false;
        submit.disabled = true;
    });
})();
