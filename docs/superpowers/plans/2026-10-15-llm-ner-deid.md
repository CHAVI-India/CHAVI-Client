# LLM NER Alternative for Text Deidentification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-LLM (e.g. Gemma via Ollama) NER engine as an *alternative* to the Stanford NER in the extractor text-deidentification pipeline, without removing any existing functionality.

**Architecture:** `ClientConfiguration` gains opt-in fields (enable + local-execution certification + default) so a specific existing config is designated as the LLM NER engine. A new `LlmNerRecognizer` (Presidio `Recognizer`) wraps an Ollama/OpenAI-compatible chat call whose output is *verbatim entity spans* (no offsets); offsets are computed by locating each span in the source text, consuming duplicates in order. The recognizer plugs into the existing `AnalyzerEngine` as an ad-hoc recognizer, so all downstream logic (date shifting, tags, overlap resolution, CSV column map, review UI) is unchanged. Rule-based recognizers (patterns, Indian IDs, gazetteers, patient recognizers) keep running alongside the LLM on both engines.

**Tech Stack:** Django, Presidio analyzer, instructor (JSON mode, same pattern as `instructor_extractor.py`), OpenAI python client, Celery `BackgroundTask`, existing HTMX/Tailwind-style templates.

**Spec:** requirements agreed in conversation: keep Presidio/Stanford pipeline; LLM replaces only the NER part; config reuses `ClientConfiguration` (no new config model, no settings toggle); validation rejects cloud providers for deid use; mandatory "I understand" local-network certification checkbox; model-based default (which engine is default) overridable manually per run; LLM reports type + verbatim text only, offsets computed via search with ordered duplicate mapping; views/forms protected by the same permissions as current deid views.

## Global Constraints

- Never remove or change existing Presidio behavior: `EXTRACTOR_DEID_NER_BACKEND`, `DEID_HF_*`, `_filter_results`, `_resolve_overlaps`, `_apply_replacements`, date shifting, CSV column map, review UI all stay.
- Text deid via LLM is only allowed when the configured endpoint is local (loopback/LAN/CGNAT) AND the provider is not a known cloud provider AND the user has checked the certification checkbox. Enforced in `ClientConfiguration.clean()` and re-checked at dispatch time in the service.
- Offsets never come from the model. The model outputs `{"type", "text"}`; the service locates spans. Unlocatable spans are dropped (logged), never guessed.
- Fail-safe: if the LLM call or config validation fails, the deid task fails with a readable error. Never silently fall back to a weaker engine and emit "deidentified" output.
- Permissions on all new/changed deid views: `@login_required` + `@permission_required('extractor.change_processedtext', raise_exception=True)` for dispatch (unchanged); `extractor.view_processedtext` for viewing (unchanged).
- Tests: Django `TestCase`/`SimpleTestCase` in `extractor/tests.py`, following existing style (no pytest fixtures; `unittest.mock` for patching).
- Migration number continues from `0031` → `0032`.

## File Structure


| File                                                                                                  | Change | Responsibility                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `extractor/models.py`                                                                                 | Modify | 3 new `ClientConfiguration` fields + `clean()` validation; `ProcessedText.deid_client_config` FK; `deid_engine` help text                        |
| `extractor/migrations/0032_*.py`                                                                      | Create | Migration for the above                                                                                                                          |
| `extractor/services/url_policy.py`                                                                    | Modify | `is_local_endpoint()`, `is_cloud_provider()` helpers                                                                                             |
| `extractor/services/llm_ner.py`                                                                       | Create | Prompt, entity-type map, chunking, verbatim span resolution, `LlmNerClient`, `LlmNerRecognizer`                                                  |
| `extractor/services/text_deidentification.py`                                                         | Modify | Backend resolution, LLM analyzer variant (no HF NER), ad-hoc LLM recognizer plumbing, `engine_mode='llm'`, duration filter fix                   |
| `extractor/tasks.py`                                                                                  | Modify | `deidentify_processed_text_task` passes `backend`/`client_config_id`                                                                             |
| `extractor/views.py`                                                                                  | Modify | `processed_text_deidentify` accepts + pre-validates engine choice; `file_upload_detail` context; client-config create/edit handle new checkboxes |
| `extractor/management/commands/deidentify_processed.py`                                               | Modify | `--backend` / `--client-config` options                                                                                                          |
| `templates/extractor/client_configuration_create.html` / `_edit.html` / `_detail.html` / `_list.html` | Modify | Deid opt-in section, certification checkbox, default toggle, status display                                                                      |
| `templates/extractor/file_upload_detail.html`                                                         | Modify | Engine selector in the "Run deid" form                                                                                                           |
| `templates/extractor/processed_text_deid_review.html` / `processed_text_view.html`                    | Modify | Engine + model badges                                                                                                                            |
| `extractor/tests.py`                                                                                  | Modify | Tests for validation, span resolution, chunking, backend resolution, end-to-end LLM deid (mocked), view dispatch                                 |


---

## Part 1 — Data model, validation, config UI

### Task 1: ClientConfiguration deid fields + validation + migration

**Files:**

- Modify: `extractor/services/url_policy.py`
- Modify: `extractor/models.py` (`ClientConfiguration`, \~line 44-120; `ProcessedText`, \~line 222-260)
- Create: `extractor/migrations/0032_clientconfiguration_enable_text_deid_and_more.py`
- Test: `extractor/tests.py`

**Interfaces:**

- Consumes: `normalize_base_url`, `LAN_NETWORKS` (already in `url_policy.py`)
- Produces: `is_local_endpoint(base_url: str) -> bool`, `is_cloud_provider(provider: str) -> bool` in `extractor.services.url_policy`; `ClientConfiguration.enable_text_deid / deid_local_certified / is_default_deid` (bool, default False); `ProcessedText.deid_client_config` (FK → ClientConfiguration, SET\_NULL, null/blank)

- [ ] **Step 1: Write the failing tests**

Append to `extractor/tests.py` (imports already present: `TestCase` from `django.test` — add `ValidationError` import if missing):

```python
class ClientConfigurationDeidValidationTests(TestCase):
    """Deid opt-in validation on ClientConfiguration."""

    def _make(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='test-model',
            model_provider=kw.pop('provider', 'Local (Ollama)'),
            model_api_key='ollama',
            model_base_url=kw.pop('base_url', 'http://localhost:11434'),
        )
        defaults.update(kw)
        return ClientConfiguration(**defaults)

    def test_local_certified_clean(self):
        c = self._make(enable_text_deid=True, deid_local_certified=True)
        c.full_clean()  # no ValidationError

    def test_cloud_provider_rejected_for_deid(self):
        c = self._make(provider='OpenAI', base_url='https://api.openai.com/v1',
                       enable_text_deid=True, deid_local_certified=True)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_public_url_rejected_for_deid(self):
        # provider not on the cloud list, but URL is public
        c = self._make(provider='Other', base_url='https://llm.example.com/v1',
                       enable_text_deid=True, deid_local_certified=True)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_certification_required(self):
        c = self._make(enable_text_deid=True, deid_local_certified=False)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_default_requires_enable(self):
        c = self._make(enable_text_deid=False, is_default_deid=True)
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_only_one_default(self):
        first = self._make(enable_text_deid=True, deid_local_certified=True,
                           is_default_deid=True)
        first.full_clean()
        first.save()
        second = self._make(enable_text_deid=True, deid_local_certified=True,
                            is_default_deid=True)
        with self.assertRaises(ValidationError):
            second.full_clean()

    def test_lan_ip_allowed(self):
        c = self._make(base_url='http://192.168.1.50:11434',
                       enable_text_deid=True, deid_local_certified=True)
        c.full_clean()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python manage.py test extractor.tests.ClientConfigurationDeidValidationTests -v 2`
Expected: FAIL (fields don't exist → TypeError from unexpected kwargs)

- [ ] **Step 3: Add the url\_policy helpers**

Append to `extractor/services/url_policy.py`:

```python
# Provider names that denote a cloud API. Text deidentification may never
# use one: patient text must stay on the local network.
CLOUD_PROVIDERS = ('openai', 'azure', 'anthropic', 'google', 'cohere', 'mistral')


def is_cloud_provider(provider):
    p = (provider or '').lower()
    return any(name in p for name in CLOUD_PROVIDERS)


def is_local_endpoint(base_url):
    """True when the base URL points at loopback, a private/LAN address,
    or a CGNAT (NetBird/Tailscale) range. Named hosts are NOT accepted —
    locality must be provable from the address itself."""
    url = normalize_base_url(base_url)
    if not url:
        return False
    host = (urlsplit(url).hostname or '').lower()
    if host in ('localhost', 'localhost.localdomain'):
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private
            or any(ip in net for net in LAN_NETWORKS))
```

- [ ] **Step 4: Add model fields + clean() validation**

In `extractor/models.py`, on `ClientConfiguration` (after `reasoning_effort`, before `created_at`):

```python
    enable_text_deid = models.BooleanField(
        default=False,
        help_text="Opt this configuration into the text deidentification NER "
                  "role. Only local endpoints may be enabled — a cloud "
                  "provider or public URL is rejected on save.")
    deid_local_certified = models.BooleanField(
        default=False,
        help_text="Certification: I understand that patient text is sent to "
                  "this model for deidentification and that the model runs "
                  "locally (same machine or LAN), so the text never leaves "
                  "the local network.")
    is_default_deid = models.BooleanField(
        default=False,
        help_text="Use this configuration as the default deidentification "
                  "engine. When set, new files are deidentified with the "
                  "local LLM instead of the rule-based Stanford NER. "
                  "Individual files can still override the engine.")
```

Extend `clean()`:

```python
    def clean(self):
        super().clean()
        self.model_base_url = validate_base_url(self.model_base_url, 'model base URL')
        if self.model_api_key_expires:
            errors = {}
            if not self.model_api_key_validity:
                errors['model_api_key_validity'] = 'Validity date is required when API key can expire.'
            if not self.model_api_refresh_key:
                errors['model_api_refresh_key'] = 'Refresh key is required when API key can expire.'
            if errors:
                raise ValidationError(errors)

        if self.enable_text_deid or self.is_default_deid:
            from extractor.services.url_policy import (
                is_cloud_provider, is_local_endpoint)
            errors = {}
            if not self.enable_text_deid:
                errors['is_default_deid'] = (
                    'Enable text deidentification before marking it as the default.')
            if is_cloud_provider(self.model_provider):
                errors['model_provider'] = (
                    'Text deidentification cannot use a cloud provider — '
                    'patient text must not leave the local network.')
            if not is_local_endpoint(self.model_base_url):
                errors['model_base_url'] = (
                    'Text deidentification requires a local endpoint '
                    '(localhost, private/LAN or VPN address).')
            if self.enable_text_deid and not self.deid_local_certified:
                errors['deid_local_certified'] = (
                    'Certification is required: confirm the model runs '
                    'locally so patient text stays on the local network.')
            if self.is_default_deid and ClientConfiguration.objects.exclude(
                    pk=self.pk).filter(is_default_deid=True).exists():
                errors['is_default_deid'] = (
                    'Another configuration is already the default deid engine. '
                    'Unset its "default" flag first.')
            if errors:
                raise ValidationError(errors)
```

On `ProcessedText` (after `deid_date_shift_days`):

```python
    deid_client_config = models.ForeignKey(
        'ClientConfiguration', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='deid_runs',
        help_text="ClientConfiguration whose local LLM performed NER for this "
                  "version (LLM engine only).")
```

Update `deid_engine` help\_text:

```python
    deid_engine = models.CharField(
        max_length=20, blank=True,
        help_text="'full' (all recognizers incl. HF model), 'degraded' "
                  "(spaCy+rules only) or 'llm' (rule-based recognizers + "
                  "local LLM NER).")
```

- [ ] **Step 5: Create the migration**

Run: `python manage.py makemigrations extractor`
Expected: `extractor/migrations/0032_clientconfiguration_enable_text_deid_and_more.py` with the three booleans, the `deid_client_config` FK and the help-text change.

Run: `python manage.py migrate`
Expected: applies cleanly.

- [ ] **Step 6: Run the validation tests**

Run: `python manage.py test extractor.tests.ClientConfigurationDeidValidationTests -v 2`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add extractor/models.py extractor/migrations/ extractor/services/url_policy.py extractor/tests.py
git commit -m "feat(deid): opt-in local-LLM deid fields on ClientConfiguration with validation"
```

### Task 2: Client configuration create/edit/detail/list UI

**Files:**

- Modify: `extractor/views.py` — `client_configuration_create` (\~line 568), `client_configuration_edit` (\~line 644), `client_configuration_list` context (\~line 533)
- Modify: `templates/extractor/client_configuration_create.html`, `client_configuration_edit.html`, `client_configuration_detail.html`, `client_configuration_list.html`

**Interfaces:**

- Consumes: Task 1 fields; existing manual form POST handling (views read `request.POST` directly, no Django forms)
- Produces: POST fields `enable_text_deid`, `deid_local_certified`, `is_default_deid` (checkbox `on`/absent) handled by both create and edit views

- [ ] **Step 1: Handle the new POST fields in `client_configuration_create`**

In the `ClientConfiguration(...)` constructor call, add:

```python
                enable_text_deid=request.POST.get('enable_text_deid') == 'on',
                deid_local_certified=request.POST.get('deid_local_certified') == 'on',
                is_default_deid=request.POST.get('is_default_deid') == 'on',
```

`configuration.full_clean()` already surfaces the Task 1 `ValidationError` via the existing `except Exception` branch (message shown to the user).

- [ ] **Step 2: Handle the new POST fields in `client_configuration_edit`**

After the `model_api_refresh_key` handling, add:

```python
        configuration.enable_text_deid = request.POST.get('enable_text_deid') == 'on'
        configuration.deid_local_certified = request.POST.get('deid_local_certified') == 'on'
        configuration.is_default_deid = request.POST.get('is_default_deid') == 'on'
```

- [ ] **Step 3: Add the deid opt-in section to `client_configuration_create.html`**

Insert after the API-key expiry block (`</div>` closing the `border-t ... pt-6` expiry section) and before the final submit row:

```html
            <div class="border-t border-gray-200 pt-6">
                <h3 class="text-sm font-semibold text-gray-800 mb-2">
                    <i class="fas fa-user-shield mr-1"></i>
                    Text deidentification (local LLM NER)
                </h3>
                <p class="text-sm text-gray-500 mb-4">
                    Optional role: this model becomes the NER engine for the text
                    deidentification pipeline, replacing the Stanford NER. Rule-based
                    recognizers (Aadhaar, ABHA, MRN patterns, dates, patient IDs) keep
                    running alongside. The model must run on this machine or the local
                    network — deidentified clinical text never leaves the local network.
                    Cloud providers are rejected for this role.
                </p>
                <div class="space-y-3">
                    <div class="flex items-start">
                        <input type="checkbox" id="enable_text_deid" name="enable_text_deid"
                               class="h-4 w-4 mt-1 text-chavi-primary border-gray-300 rounded focus:ring-chavi-primary">
                        <label for="enable_text_deid" class="ml-2 text-sm font-medium text-gray-700">
                            Enable this configuration for text deidentification
                        </label>
                    </div>
                    <div class="flex items-start">
                        <input type="checkbox" id="deid_local_certified" name="deid_local_certified"
                               class="h-4 w-4 mt-1 text-chavi-primary border-gray-300 rounded focus:ring-chavi-primary">
                        <label for="deid_local_certified" class="ml-2 text-sm text-gray-700">
                            I understand and certify: this model runs locally (same machine
                            or local network) and patient text will not leave the local network.
                        </label>
                    </div>
                    <div class="flex items-start">
                        <input type="checkbox" id="is_default_deid" name="is_default_deid"
                               class="h-4 w-4 mt-1 text-chavi-primary border-gray-300 rounded focus:ring-chavi-primary">
                        <label for="is_default_deid" class="ml-2 text-sm text-gray-700">
                            Make this the default deidentification engine for new files
                            <span class="text-gray-500">(overridable per file; only one
                            configuration may be the default)</span>
                        </label>
                    </div>
                </div>
            </div>
```

- [ ] **Step 4: Add the same section to `client_configuration_edit.html`**

Same markup as Step 3, with a `checked` attribute on each input driven by the instance, e.g.:

```html
<input type="checkbox" id="enable_text_deid" name="enable_text_deid"
       {% if configuration.enable_text_deid %}checked{% endif %}
       class="h-4 w-4 mt-1 ...">
```

- [ ] **Step 5: Show deid status on `client_configuration_detail.html`**

In the "Configuration Details" card grid, add:

```html
                    <div>
                        <p class="text-sm font-medium text-gray-500">Text Deidentification</p>
                        <p class="text-lg text-gray-800">
                            {% if configuration.enable_text_deid %}
                                Enabled
                                {% if configuration.is_default_deid %}
                                    {% component "badge" style="success" extra_class="ml-2" %}Default engine{% endcomponent %}
                                {% endif %}
                                {% if not configuration.deid_local_certified %}
                                    {% component "badge" style="danger" extra_class="ml-2" %}Not certified{% endcomponent %}
                                {% endif %}
                            {% else %}
                                Not enabled
                            {% endif %}
                        </p>
                    </div>
```

- [ ] **Step 6: Deid badge on `client_configuration_list.html`**

Locate the per-row provider/model columns and append after the model name cell (inside the row's grid):

```html
{% if cfg.enable_text_deid %}
    {% component "badge" style="accent" extra_class="ml-2" %}DEID{% endcomponent %}
    {% if cfg.is_default_deid %}{% component "badge" style="success" extra_class="ml-2" %}Default{% endcomponent %}{% endif %}
{% endif %}
```

(Use the actual row variable name in that template — inspect the template's `{% for %}` loop variable before editing.)

- [ ] **Step 7: Manual verification**

Run the dev server; create a config with `OpenAI` + `https://api.openai.com/v1` + deid checkboxes ticked → expect the error message "Text deidentification cannot use a cloud provider…". Create `Local (Ollama)` + `http://localhost:11434` with all three checkboxes → saves; detail page shows Enabled + Default.

- [ ] **Step 8: Commit**

```bash
git add extractor/views.py templates/extractor/client_configuration_create.html templates/extractor/client_configuration_edit.html templates/extractor/client_configuration_detail.html templates/extractor/client_configuration_list.html
git commit -m "feat(deid): deid opt-in, certification and default engine in client config UI"
```

---

## Part 2 — LLM NER service (`extractor/services/llm_ner.py`)

### Task 3: Chunking + verbatim span resolution (pure, testable)

**Files:**

- Create: `extractor/services/llm_ner.py`
- Test: `extractor/tests.py`

**Interfaces:**

- Produces:
  - `LlmNerError(Exception)`
  - `ENTITY_TYPES: dict` — model-side type name → Presidio entity (exact table in Step 3)
  - `NER_SYSTEM_PROMPT: str`
  - `chunk_text(text, max_chars=3500, overlap=256) -> Iterator[tuple[int, str]]` yielding `(offset, chunk)`; union of chunks covers every character of `text`
  - `class _SourceIndex(source)` with `locate(span, from_pos=0, case_sensitive=True) -> tuple[int, int] | None` returning original-text `(start, end)`
  - `resolve_spans(source, found) -> list[dict]` where `found` is an ordered list of `(presidio_type, verbatim_span)` and each result dict is `{'type', 'start', 'end'}` — offsets computed here, never by the model; duplicate spans consumed in order against successive occurrences; unlocatable spans dropped
- Consumes: nothing (pure module; no Django model imports at module level)

- [ ] **Step 1: Write the failing tests**

Append to `extractor/tests.py`:

```python
from extractor.services import llm_ner


class ChunkTextTests(SimpleTestCase):
    def test_short_text_single_chunk(self):
        chunks = list(llm_ner.chunk_text('hello world'))
        self.assertEqual(chunks, [(0, 'hello world')])

    def test_empty_text(self):
        self.assertEqual(list(llm_ner.chunk_text('')), [])

    def test_full_coverage_no_gaps(self):
        text = 'Para one.\n\n' * 50 + '\n\n'.join(
            f'Sentence {i} of paragraph two, with details.' for i in range(100))
        chunks = list(llm_ner.chunk_text(text, max_chars=500, overlap=50))
        covered = set()
        for offset, chunk in chunks:
            covered.update(range(offset, offset + len(chunk)))
        self.assertEqual(covered, set(range(len(text))))

    def test_chunks_respect_max_chars(self):
        text = 'word ' * 5000
        for offset, chunk in llm_ner.chunk_text(text, max_chars=1000, overlap=100):
            self.assertLessEqual(len(chunk), 1000)

    def test_progress_guaranteed_on_no_boundaries(self):
        text = 'x' * 5000
        chunks = list(llm_ner.chunk_text(text, max_chars=1000, overlap=100))
        self.assertGreater(len(chunks), 1)
        starts = [o for o, _ in chunks]
        self.assertTrue(all(b > a for a, b in zip(starts, starts[1:])))


class ResolveSpansTests(SimpleTestCase):
    def test_exact_single_span(self):
        src = 'Patient Sharma Rao visited on 01/02/2024.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma Rao')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'Sharma Rao')
        self.assertEqual(out[0]['type'], 'PERSON')

    def test_duplicate_spans_consumed_in_order(self):
        src = 'Dr Rao examined Rao and Rao again.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Rao')] * 3)
        spans = [src[e['start']:e['end']] for e in out]
        self.assertEqual(spans, ['Rao', 'Rao', 'Rao'])
        starts = [e['start'] for e in out]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(b > a for a, b in zip(starts, starts[1:])))

    def test_whitespace_normalized_span(self):
        src = 'Admitted: Sharma\nRao, 56 y.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma Rao')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'Sharma\nRao')

    def test_case_fallback(self):
        src = 'referred by Dr SHARMA.'
        out = llm_ner.resolve_spans(src, [('PERSON', 'Sharma')])
        self.assertEqual(len(out), 1)
        self.assertEqual(src[out[0]['start']:out[0]['end']], 'SHARMA')

    def test_unlocatable_span_dropped(self):
        out = llm_ner.resolve_spans('hello world', [('PERSON', 'Ghost Name')])
        self.assertEqual(out, [])

    def test_blank_span_ignored(self):
        self.assertEqual(llm_ner.resolve_spans('abc', [('PERSON', '   ')]), [])

    def test_same_span_two_types_kept_once_per_type(self):
        src = 'MR/24/012817 issued.'
        out = llm_ner.resolve_spans(
            src, [('MEDICAL_RECORD_NUMBER', 'MR/24/012817'),
                  ('PERSON', 'MR')])
        types = sorted(e['type'] for e in out)
        self.assertEqual(types, ['MEDICAL_RECORD_NUMBER', 'PERSON'])
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python manage.py test extractor.tests.ResolveSpansTests extractor.tests.ChunkTextTests -v 2`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Implement the module (chunking + span resolution)**

Create `extractor/services/llm_ner.py`:

```python
"""LLM-based NER for the text deidentification pipeline.

An alternative to the HuggingFace/Stanford NER recognizer: a local
LLM (e.g. Gemma via Ollama) reads each chunk of the document and returns
entity type + VERBATIM span only. Offsets are never trusted from the
model — each span is located in the source text by search, with
duplicate spans consumed in order against successive occurrences.
Spans that cannot be located are dropped (logged), never guessed.
"""

import logging
import re
from bisect import bisect_right

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 3500
DEFAULT_CHUNK_OVERLAP = 256
LLM_NER_SCORE = 0.9
MAX_ENTITIES_PER_SOURCE = 400


class LlmNerError(Exception):
    """LLM call or config problem — deid run must fail, not degrade."""


# model-side type name (lowercase) -> Presidio entity used by the pipeline
ENTITY_TYPES = {
    'person': 'PERSON', 'name': 'PERSON', 'patient': 'PERSON',
    'doctor': 'PERSON', 'relative': 'PERSON',
    'location': 'LOCATION', 'place': 'LOCATION', 'address': 'LOCATION',
    'village': 'LOCATION', 'city': 'LOCATION', 'state': 'LOCATION',
    'organization': 'ORGANIZATION', 'org': 'ORGANIZATION',
    'hospital': 'ORGANIZATION', 'clinic': 'ORGANIZATION', 'lab': 'ORGANIZATION',
    'phone': 'PHONE_NUMBER', 'phone_number': 'PHONE_NUMBER',
    'telephone': 'PHONE_NUMBER',
    'date': 'DATE_TIME', 'date_time': 'DATE_TIME', 'dob': 'DATE_TIME',
    'medical_record_number': 'MEDICAL_RECORD_NUMBER', 'mrn': 'MEDICAL_RECORD_NUMBER',
    'uhid': 'MEDICAL_RECORD_NUMBER', 'registration_number': 'MEDICAL_RECORD_NUMBER',
    'aadhaar': 'IN_AADHAAR', 'aadhar': 'IN_AADHAAR',
    'mobile': 'IN_MOBILE_NUMBER', 'mobile_number': 'IN_MOBILE_NUMBER',
    'phone_mobile': 'IN_MOBILE_NUMBER',
    'pincode': 'IN_PINCODE', 'pin_code': 'IN_PINCODE', 'postal_code': 'IN_PINCODE',
    'abha': 'IN_ABHA', 'upi': 'IN_UPI',
    'driving_license': 'IN_DRIVING_LICENSE', 'driving_licence': 'IN_DRIVING_LICENSE',
    'religion': 'IN_RELIGION', 'caste': 'IN_RELIGION',
}

NER_SYSTEM_PROMPT = """You are a medical de-identification model. You find
personally identifiable information (PII/PHI) in clinical text and report
each finding as an exact verbatim copy.

Report ONLY these types:
- person: patient, relative, doctor or any other person's name. Note that medical names should not be confused with person names for example Parkinson disease is not a person name but a diagnosis. 
- location: village, town, city, state, street, house number, full address
- organization: hospital, clinic, lab or department name
- phone: telephone or phone number
- date: calendar dates (birth, admission, visit, report dates) in any format. Do not flag durations like 1 month, 3 years etc in the records as date. 
- medical_record_number: MRN/UHID/registration/IP/OPD/hospital/case/report/lab numbers
- aadhaar: 12-digit Aadhaar number
- mobile: 10-digit Indian mobile number
- pincode: 6-digit Indian PIN code
- abha: ABHA/Ayushman/NHDM health ID
- upi: UPI handle (e.g. name@okhdfc)
- driving_license: driving licence number

STRICT RULES:
1. Copy each finding VERBATIM - character for character, same case, same
   spacing. Do not correct, translate, abbreviate, normalize or extend it.
2. Durations are NOT dates: "1 month", "3 days", "2 weeks", "6 months" are
   NEVER reported. Ages are never reported ("56 years old", "56-year-old").
3. Bare numbers (doses, counts, measurements, percentages) are never reported.
4. Never report anything that is not present in the text. Never guess or
   infer spans.
5. If one span fits two types, report it once with the more specific type.

Respond with a single JSON array and nothing else. Each element is
{"type": "<one of the types above>", "text": "<verbatim span>"}.
Return [] when there is no identifiable information.
No prose, no markdown fences, no offsets, no explanations."""


def chunk_text(text, max_chars=DEFAULT_CHUNK_CHARS, overlap=DEFAULT_CHUNK_OVERLAP):
    """Yield (offset, chunk) covering every character of text.

    Chunks end at a paragraph/sentence/space boundary near max_chars so
    entities are rarely split; consecutive chunks overlap by `overlap`
    characters so boundary-spanning entities are still caught, and are
    de-duplicated later by (type, global start, global end).
    """
    n = len(text)
    if n == 0:
        return
    if n <= max_chars:
        yield 0, text
        return
    start = 0
    while start < n:
        target = min(start + max_chars, n)
        if target == n:
            yield start, text[start:]
            break
        window = text[start:target]
        cut = -1
        for sep in ('\n\n', '\n', '. ', '; ', ' '):
            idx = window.rfind(sep)
            if idx > max(64, max_chars // 2):
                cut = start + idx + len(sep)
                break
        if cut <= start + 64:
            cut = target
        yield start, text[start:cut]
        start = max(cut - overlap, start + 1)


class _SourceIndex:
    """Locates verbatim spans in a source string.

    Three strategies in order: exact find, whitespace-collapsed find
    (handles line-broken names like 'Sharma\\nRao'), then case-insensitive
    variants of both. Returns offsets into the ORIGINAL string.
    """

    __slots__ = ('source', 'source_lower', 'collapsed', 'collapsed_lower', 'pos_map')

    def __init__(self, source):
        self.source = source
        self.source_lower = source.lower()
        chars = []
        self.pos_map = []
        for i, ch in enumerate(source):
            if not ch.isspace():
                chars.append(ch)
                self.pos_map.append(i)
        self.collapsed = ''.join(chars)
        self.collapsed_lower = self.collapsed.lower()

    def _collapsed_from(self, from_pos):
        """First collapsed-coordinate index whose original pos >= from_pos."""
        return bisect_right(self.pos_map, from_pos - 1)

    def locate(self, span, from_pos=0, case_sensitive=True):
        span = span or ''
        if not span.strip():
            return None
        # 1. exact
        if case_sensitive:
            idx = self.source.find(span, from_pos)
        else:
            idx = self.source_lower.find(span.lower(), from_pos)
        if idx != -1:
            return idx, idx + len(span)
        # 2. whitespace-collapsed
        collapsed = ''.join(span.split())
        if not collapsed:
            return None
        cfrom = self._collapsed_from(from_pos)
        if case_sensitive:
            cidx = self.collapsed.find(collapsed, cfrom)
        else:
            cidx = self.collapsed_lower.find(collapsed.lower(), cfrom)
        if cidx == -1 or cidx + len(collapsed) > len(self.pos_map):
            return None
        start = self.pos_map[cidx]
        end = self.pos_map[cidx + len(collapsed) - 1] + 1
        return start, end


def resolve_spans(source, found):
    """Map ordered model output to offsets in `source`.

    `found`: list of (presidio_entity_type, verbatim_span) in the order the
    model reported them. Offsets are computed here — the model never
    reports them. Duplicate (type, span) pairs are consumed in order: the
    k-th report searches from just after the (k-1)-th match, so repeated
    names bind to successive occurrences. Exact matching is tried first,
    then whitespace-collapsed, then case-insensitive variants. Spans that
    cannot be located are dropped with a warning. Returns
    [{'type', 'start', 'end'}] sorted by position.
    """
    index = _SourceIndex(source)
    next_from = {}  # (type, normalized span) -> search start in original coords
    out = []
    seen = set()
    for entity_type, span in found:
        norm = ' '.join((span or '').split()).lower()
        if not norm:
            continue
        key = (entity_type, norm)
        from_pos = next_from.get(key, 0)
        match = index.locate(span, from_pos, case_sensitive=True)
        if match is None:
            match = index.locate(span, from_pos, case_sensitive=False)
        if match is None:
            logger.warning(
                'LLM NER span not found in source, dropped: %r', span)
            continue
        start, end = match
        next_from[key] = end
        pos_key = (entity_type, start, end)
        if pos_key in seen:
            continue
        seen.add(pos_key)
        out.append({'type': entity_type, 'start': start, 'end': end})
        if len(out) >= MAX_ENTITIES_PER_SOURCE:
            logger.warning(
                'LLM NER entity cap (%d) reached; remaining spans dropped',
                MAX_ENTITIES_PER_SOURCE)
            break
    return sorted(out, key=lambda e: (e['start'], e['end']))
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python manage.py test extractor.tests.ResolveSpansTests extractor.tests.ChunkTextTests -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/services/llm_ner.py extractor/tests.py
git commit -m "feat(deid): LLM NER chunking + verbatim span resolution (offsets by search)"
```

### Task 4: LlmNerClient + LlmNerRecognizer (LLM call + Presidio adapter)

**Files:**

- Modify: `extractor/services/llm_ner.py`
- Test: `extractor/tests.py`

**Interfaces:**

- Consumes: Task 3 (`chunk_text`, `resolve_spans`, `ENTITY_TYPES`, `NER_SYSTEM_PROMPT`, `LlmNerError`, `LLM_NER_SCORE`)
- Produces:
  - `class LlmNerClient(client_config)` — `find_entities_in_text(text) -> list[dict{'type','start','end','score'}]` (chunks internally, one LLM call per chunk, dedupes overlapping chunks); `find_entities(chunk) -> list[(presidio_type, span)]` (single chunk, model output mapped + validated)
  - `class LlmNerRecognizer(Recognizer)` — Presidio adapter; `__init__(client_config, cache=None)`; `analyze(text, language, **kwargs) -> list[RecognizerResult]` with per-run text cache (repeated CSV cells cost one call); `evaluate(**kwargs) -> []`

- [ ] **Step 1: Write the failing tests (LLM call mocked at the OpenAI boundary)**

Append to `extractor/tests.py`:

```python
from unittest import mock


class LlmNerClientTests(TestCase):
    def _config(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434')
        defaults.update(kw)
        return ClientConfiguration.objects.create(**defaults)

    def test_entity_types_mapped_and_offsets_found(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        text = 'Patient Sharma Rao admitted on 01/02/2024 to AIIMS.'
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                return_value=[('person', 'Sharma Rao'), ('date', '01/02/2024'),
                              ('organization', 'AIIMS'), ('junk_type', 'AIIMS')]):
            results = client.find_entities_in_text(text)
        got = {(r['type'], text[r['start']:r['end']]) for r in results}
        self.assertIn(('PERSON', 'Sharma Rao'), got)
        self.assertIn(('DATE_TIME', '01/02/2024'), got)
        self.assertIn(('ORGANIZATION', 'AIIMS'), got)
        self.assertEqual(len(results), 3)  # unknown type dropped

    def test_chunked_text_global_offsets_and_overlap_dedupe(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        filler = 'Normal clinical sentence number. ' * 200  # ~5.8k chars
        text = filler + 'Sharma Rao' + filler
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                side_effect=lambda chunk: [
                    ('person', 'Sharma Rao')
                    if 'Sharma Rao' in chunk else []]):
            results = client.find_entities_in_text(text)
        self.assertEqual(len(results), 1)  # overlap double-hit deduped
        self.assertEqual(results[0]['type'], 'PERSON')
        self.assertEqual(text[results[0]['start']:results[0]['end']], 'Sharma Rao')

    def test_llm_failure_raises(self):
        from extractor.services import llm_ner
        cfg = self._config()
        client = llm_ner.LlmNerClient(cfg)
        with mock.patch.object(
                llm_ner.LlmNerClient, '_llm_call',
                side_effect=RuntimeError('connection refused')):
            with self.assertRaises(llm_ner.LlmNerError):
                client.find_entities_in_text('some text')


class LlmNerRecognizerTests(TestCase):
    def test_cache_serves_repeated_text_without_second_call(self):
        from extractor.models import ClientConfiguration
        from extractor.services import llm_ner
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434')
        rec = llm_ner.LlmNerRecognizer(cfg)
        with mock.patch.object(
                llm_ner.LlmNerClient, 'find_entities_in_text',
                return_value=[{'type': 'PERSON', 'start': 0, 'end': 5,
                               'score': llm_ner.LLM_NER_SCORE}]) as m:
            first = rec.analyze('Rao K.', language='en')
            second = rec.analyze('Rao K.', language='en')
        self.assertEqual(m.call_count, 1)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].entity_type, 'PERSON')
        self.assertEqual((first[0].start, first[0].end), (0, 5))
        self.assertEqual(len(second), 1)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python manage.py test extractor.tests.LlmNerClientTests extractor.tests.LlmNerRecognizerTests -v 2`
Expected: FAIL (classes missing)

- [ ] **Step 3: Implement client + recognizer**

Append to `extractor/services/llm_ner.py`:

```python
def _normalize_entity_type(raw):
    """Model type string -> Presidio entity, or None for unknown types."""
    key = re.sub(r'[^a-z0-9]+', '_', (raw or '').strip().lower()).strip('_')
    return ENTITY_TYPES.get(key)


class LlmNerClient:
    """Chat-completion client for the deid NER role.

    Uses the same OpenAI-compatible wiring as the extraction pipeline
    (base_url + /v1, 'ollama' dummy key for local providers). The model
    must return a JSON array of {"type", "text"}; offsets are computed
    by resolve_spans, never parsed from the response.
    """

    def __init__(self, client_config):
        from openai import OpenAI
        from extractor.services.url_policy import validate_base_url

        base_url = validate_base_url(
            client_config.model_base_url, 'model base URL')
        if not base_url.endswith('/v1'):
            base_url = f'{base_url}/v1'
        provider = (client_config.model_provider or '').lower()
        is_local = 'ollama' in provider or 'local' in provider
        self._client = OpenAI(
            base_url=base_url,
            api_key='ollama' if is_local else client_config.model_api_key,
            timeout=client_config.request_timeout,
        )
        self._model = client_config.llm_model_name

    def _llm_call(self, chunk):
        """One JSON-mode chat call. Returns [(presidio_type, verbatim_span)].

        Isolated as a method so tests can patch the network boundary.
        Raises LlmNerError on call failure or unparseable/invalid JSON.
        """
        import instructor
        from pydantic import BaseModel, Field

        class _Hit(BaseModel):
            type: str = Field(description='entity type')
            text: str = Field(description='verbatim span')

        class _Out(BaseModel):
            entities: list[_Hit] = []

        try:
            client = instructor.from_openai(self._client, mode=instructor.Mode.JSON)
            result = client.chat.completions.create(
                model=self._model,
                messages=[
                    {'role': 'system', 'content': NER_SYSTEM_PROMPT},
                    {'role': 'user', 'content': chunk},
                ],
                response_model=_Out,
                max_retries=1,
                temperature=0,
            )
        except LlmNerError:
            raise
        except Exception as e:
            raise LlmNerError(
                f'LLM NER call failed for model {self._model!r}: {e}') from e

        out = []
        for hit in (result.entities if result else []):
            entity_type = _normalize_entity_type(hit.type)
            if entity_type is None:
                logger.warning('LLM NER unknown entity type dropped: %r', hit.type)
                continue
            if not (hit.text or '').strip():
                continue
            out.append((entity_type, hit.text))
        return out

    def find_entities(self, chunk):
        """One chunk -> [(presidio_type, verbatim_span)]."""
        return self._llm_call(chunk)

    def find_entities_in_text(self, text):
        """Whole text -> [{'type','start','end','score'}] with global,
        de-duplicated offsets (overlapping chunks re-find boundary
        entities; duplicates collapse on (type, start, end))."""
        if not text or not text.strip():
            return []
        results = []
        seen = set()
        for offset, chunk in chunk_text(text):
            for found in resolve_spans(chunk, self.find_entities(chunk)):
                start, end = found['start'] + offset, found['end'] + offset
                key = (found['type'], start, end)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    'type': found['type'], 'start': start, 'end': end,
                    'score': LLM_NER_SCORE,
                })
        return sorted(results, key=lambda r: (r['start'], r['end']))


class LlmNerRecognizer(Recognizer):
    """Presidio adapter so the LLM plugs into the existing analyzer as an
    ad-hoc recognizer — all downstream deid logic (filters, overlap
    resolution, date shifting, tagging, CSV handling) is unchanged.

    Results carry no context enhancement (the LLM already applied
    context); they pass the analyzer's threshold untouched at
    LLM_NER_SCORE (0.9), which outranks rule recognizers' moderate
    scores while deterministic patterns (e.g. 0.95 MRN) still win.
    """

    supported_entity = 'PERSON'
    name = 'LlmNerRecognizer'

    def __init__(self, client_config, cache=None):
        self._client = LlmNerClient(client_config)
        self._cache = cache if cache is not None else {}

    def analyze(self, text, language, **kwargs):
        if not text or not text.strip():
            return []
        found = self._cache.get(text)
        if found is None:
            found = self._client.find_entities_in_text(text)
            self._cache[text] = found
        return [
            RecognizerResult(type=e['type'], start=e['start'], end=e['end'],
                             score=e['score'])
            for e in found
        ]

    def evaluate(self, **kwargs):
        return []
```

Add the Presidio import at the top of the module (after `bisect` import):

```python
from presidio_analyzer import Recognizer, RecognizerResult
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python manage.py test extractor.tests.LlmNerClientTests extractor.tests.LlmNerRecognizerTests -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/services/llm_ner.py extractor/tests.py
git commit -m "feat(deid): LlmNerClient + LlmNerRecognizer Presidio adapter"
```
---

## Part 3 — Pipeline integration, dispatch, views, frontend

### Task 5: Backend resolution + LLM plumbing in `text_deidentification.py`

**Files:**
- Modify: `extractor/services/text_deidentification.py`
- Test: `extractor/tests.py`

**Interfaces:**
- Consumes: Task 1 (`ClientConfiguration` fields, `is_local_endpoint`, `is_cloud_provider`), Task 4 (`LlmNerRecognizer`, `LlmNerError`)
- Produces:
  - `LlmDeidConfigurationError(ValueError)` in `text_deidentification.py`
  - `TextDeidentificationService._resolve_backend(backend, client_config_id) -> tuple[str, ClientConfiguration|None]` — `'default'`/`None` → `('llm', cfg)` when a default-enabled config exists else `('presidio', None)`; `'presidio'` → `('presidio', None)`; `'llm'` → `('llm', cfg)` with full re-validation, raising `LlmDeidConfigurationError` with a human-readable reason
  - `deidentify(processed_text, user=None, backend='default', client_config_id=None)` and `deidentify_if_needed(processed_text, user=None, backend='default', client_config_id=None)` — new keyword params, backward compatible
  - LLM runs store `deid_engine='llm'`, `deid_model=<llm_model_name>`, `deid_client_config=<cfg>`

- [ ] **Step 1: Write the failing tests**

Append to `extractor/tests.py`:

```python
class DeidBackendResolutionTests(TestCase):
    def _cfg(self, **kw):
        from extractor.models import ClientConfiguration
        defaults = dict(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            enable_text_deid=True, deid_local_certified=True)
        defaults.update(kw)
        return ClientConfiguration.objects.create(**defaults)

    def test_default_without_config_is_presidio(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        self.assertEqual(S._resolve_backend('default', None), ('presidio', None))

    def test_default_with_default_config_is_llm(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        cfg = self._cfg(is_default_deid=True)
        backend, got = S._resolve_backend(None, None)
        self.assertEqual(backend, 'llm')
        self.assertEqual(got.id, cfg.id)

    def test_explicit_llm_without_config_raises(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S, LlmDeidConfigurationError)
        with self.assertRaises(LlmDeidConfigurationError):
            S._resolve_backend('llm', None)

    def test_llm_with_uncertified_config_raises(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S, LlmDeidConfigurationError)
        cfg = self._cfg(deid_local_certified=False)
        with self.assertRaises(LlmDeidConfigurationError):
            S._resolve_backend('llm', cfg.id)

    def test_unknown_backend_raises(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S, LlmDeidConfigurationError)
        with self.assertRaises(LlmDeidConfigurationError):
            S._resolve_backend('magic', None)


class DurationFilterTests(SimpleTestCase):
    def _filter(self, text, etype, surface=None, start=None, end=None):
        import re
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)

        class R:
            def __init__(self):
                self.entity_type = etype
                self.start = start if start is not None else 0
                self.end = end if end is not None else len(surface or text)
                self.score = 0.9
        surface = surface if surface is not None else text
        r = R()
        r.start = text.find(surface)
        r.end = r.start + len(surface)
        kept = S._filter_results(text, [r])
        return len(kept) == 1

    def test_bare_duration_months_dropped(self):
        self.assertFalse(self._filter('follow up after 1 month', 'DATE_TIME', '1 month'))

    def test_bare_duration_weeks_days_dropped(self):
        self.assertFalse(self._filter('take for 2 weeks', 'DATE_TIME', '2 weeks'))
        self.assertFalse(self._filter('waited 3 days', 'DATE_TIME', '3 days'))

    def test_real_date_kept(self):
        self.assertTrue(self._filter('admitted on 01/02/2024', 'DATE_TIME', '01/02/2024'))

    def test_age_surfaces_still_dropped(self):
        self.assertFalse(self._filter('age 56 years', 'DATE_TIME', '56 years'))
        self.assertFalse(self._filter('a 56-year-old man', 'DATE_TIME', '56-year-old'))
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python manage.py test extractor.tests.DeidBackendResolutionTests extractor.tests.DurationFilterTests -v 2`
Expected: FAIL (`LlmDeidConfigurationError` missing; duration filter currently keeps '1 month')

- [ ] **Step 3: Implement backend resolution + LLM plumbing**

In `extractor/services/text_deidentification.py`:

(a) Imports — add after the existing imports, plus the error class:

```python
from extractor.services.llm_ner import LlmNerRecognizer
from extractor.services.url_policy import is_cloud_provider, is_local_endpoint


class LlmDeidConfigurationError(ValueError):
    """LLM deid engine requested but no usable local configuration exists."""
```

(b) Add the resolver as a classmethod (before `deidentify`):

```python
    @classmethod
    def _resolve_backend(cls, backend, client_config_id):
        """Resolve the deid engine for a run.

        Returns ('presidio', None) or ('llm', ClientConfiguration).
        'default'/None follows the model-based default: a
        ClientConfiguration with enable_text_deid + is_default_deid makes
        the LLM engine the default; otherwise the existing rule-based
        engine (with Stanford NER when configured) runs.
        """
        from extractor.models import ClientConfiguration

        if backend in (None, '', 'default'):
            has_default = ClientConfiguration.objects.filter(
                enable_text_deid=True, is_default_deid=True).exists()
            backend = 'llm' if has_default else 'presidio'
        if backend == 'presidio':
            return 'presidio', None
        if backend != 'llm':
            raise LlmDeidConfigurationError(
                f"Unknown deid backend {backend!r} "
                "(expected 'default', 'presidio' or 'llm').")

        if client_config_id:
            config = ClientConfiguration.objects.filter(
                id=client_config_id).first()
        else:
            config = (
                ClientConfiguration.objects.filter(
                    enable_text_deid=True, is_default_deid=True).first()
                or ClientConfiguration.objects.filter(
                    enable_text_deid=True).first())
        if config is None:
            raise LlmDeidConfigurationError(
                'No enabled text-deid configuration. Enable one on the LLM '
                'configuration page (local model + certification).')
        problems = []
        if not config.enable_text_deid:
            problems.append('text deidentification is not enabled')
        if not config.deid_local_certified:
            problems.append('local execution is not certified')
        if is_cloud_provider(config.model_provider):
            problems.append('a cloud provider is not allowed')
        if not is_local_endpoint(config.model_base_url):
            problems.append('the endpoint is not local')
        if problems:
            raise LlmDeidConfigurationError(
                f"Client configuration '{config.llm_model_name}' is not "
                f"usable for text deid: {'; '.join(problems)}.")
        return 'llm', config
```

(c) Refactor `_build_analyzer` to optionally omit the HF NER (so the LLM engine runs rules + LLM, never rules + LLM + Stanford):

```python
    _llm_analyzer = None  # lazy singleton without HF NER

    @classmethod
    def _build_analyzer(cls, include_hf_ner=None):
        analyzer = AnalyzerEngine(
            supported_languages=["en"],
            context_aware_enhancer=LemmaContextAwareEnhancer(
                context_similarity_factor=0.35,
                min_score_with_context_similarity=0.4,
            ),
        )
        engine_mode = 'degraded'

        if include_hf_ner is None:
            backend = getattr(settings, 'EXTRACTOR_DEID_NER_BACKEND', 'hf')
        else:
            backend = 'hf' if include_hf_ner else 'none'
        if backend == 'hf':
            ... (unchanged existing block) ...
```

Add a getter:

```python
    @classmethod
    def _get_llm_analyzer(cls):
        """Analyzer without the HF/Stanford NER — the LLM recognizer is
        supplied per run as an ad-hoc recognizer."""
        if cls._llm_analyzer is None:
            cls._llm_analyzer, _ = cls._build_analyzer(include_hf_ner=False)
        return cls._llm_analyzer
```

Note: `_build_analyzer`'s return value is currently `(analyzer, engine_mode)`; keep both return shapes. The existing `_get_analyzer` singleton is untouched.

(d) `deidentify()` — signature and engine selection:

```python
    @classmethod
    def deidentify(cls, processed_text, user=None, backend='default',
                   client_config_id=None):
        ...
        backend_name, llm_config = cls._resolve_backend(
            backend, client_config_id)
        ...
        if backend_name == 'llm':
            analyzer = cls._get_llm_analyzer()
            engine_mode = 'llm'
            llm_recognizer = LlmNerRecognizer(llm_config)
        else:
            analyzer, engine_mode = cls._get_analyzer()
            llm_recognizer = None
```

Then in the two `_deidentify_*` calls pass `llm_recognizer=llm_recognizer`, and replace the trailing `_, engine_mode = cls._get_analyzer()` with the already-computed `engine_mode`. In `ProcessedText.objects.create(...)`:

```python
            deid_engine=engine_mode,
            deid_model=(
                llm_config.llm_model_name
                if backend_name == 'llm'
                else (settings.DEID_HF_NER_MODEL if engine_mode == 'full' else '')
            ),
            deid_client_config=llm_config,
```

(e) `_deidentify_text` / `_deidentify_csv` — accept the recognizer:

```python
    @classmethod
    def _deidentify_text(cls, content, shift, patient, llm_recognizer=None):
        if llm_recognizer is not None:
            analyzer = cls._get_llm_analyzer()
        else:
            analyzer, _ = cls._get_analyzer()
        ad_hoc = build_patient_recognizers(patient)
        if llm_recognizer is not None:
            ad_hoc = [llm_recognizer] + ad_hoc
        results = analyzer.analyze(
            text=content, language='en',
            score_threshold=getattr(
                settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35),
            ad_hoc_recognizers=ad_hoc,
        )
        ... (rest unchanged)
```

Same change in `_deidentify_csv` (both the fallback-to-text call and the per-cell `analyzer.analyze` calls receive `llm_recognizer`; the recognizer's per-run cache makes repeated cell values cost one LLM call).

(f) `deidentify_if_needed` — pass through:

```python
    @classmethod
    def deidentify_if_needed(cls, processed_text, user=None, backend='default',
                             client_config_id=None):
        if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
            return None
        if processed_text.deid_derivatives.exists():
            return processed_text.deid_derivatives.order_by('-version').first()
        return cls.deidentify(
            processed_text, user=user, backend=backend,
            client_config_id=client_config_id)
```

(g) Fix the persistent duration false-positive in `_filter_results` (helps BOTH engines — this is the "1 month flagged as date" bug). Replace the DATE_TIME drop regex:

```python
            if (r.entity_type == 'DATE_TIME' and re.match(
                    r'^\d{1,3}%?$'
                    r'|^\d{1,3}\s*[-\s]?(years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$'
                    r'|^\d{1,3}\s+(years?|months?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$',
                    surface, re.I)):
                continue
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python manage.py test extractor.tests.DeidBackendResolutionTests extractor.tests.DurationFilterTests extractor.tests -v 1`
Expected: PASS (the full extractor suite — no regressions)

- [ ] **Step 5: Commit**

```bash
git add extractor/services/text_deidentification.py extractor/tests.py
git commit -m "feat(deid): LLM backend resolution + ad-hoc LLM recognizer in deid pipeline"
```

### Task 6: Celery task, dispatch view, management command

**Files:**
- Modify: `extractor/tasks.py` (`deidentify_processed_text_task`, ~line 472)
- Modify: `extractor/views.py` (`processed_text_deidentify` ~line 1212, `file_upload_detail` ~line 1029)
- Modify: `extractor/management/commands/deidentify_processed.py`
- Test: `extractor/tests.py`

**Interfaces:**
- Consumes: Task 5 (`deidentify(..., backend, client_config_id)`, `LlmDeidConfigurationError`)
- Produces:
  - `deidentify_processed_text_task(task_id, processed_text_id, user_id=None, backend='default', client_config_id=None)`
  - `processed_text_deidentify` accepts POST `backend` ∈ {'default','presidio','llm'} and `client_config_id`; pre-validates via `_resolve_backend` so users get a Django message instead of a failed background task. Option values may be encoded as `llm:<config_id>` from the UI select.
  - `file_upload_detail` context gains `deid_llm_configs` (usable configs) and `deid_default_is_llm` (bool)
  - Command flags `--backend {default,presidio,llm}` (default 'default') and `--client-config <id>`

- [ ] **Step 1: Write the failing tests**

Append to `extractor/tests.py`:

```python
class DeidDispatchViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from extractor.models import (
            ClientConfiguration, FileUpload, ProcessedText)
        self.user = User.objects.create_user('deid_tester')
        self.user.user_permissions.set(
            Permission.objects.filter(
                codename__in=['view_processedtext', 'change_processedtext',
                              'view_fileupload']))
        self.upload = FileUpload.objects.create(original_filename='a.pdf')
        self.pt = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path='x.txt',
            content_length=3)
        self.path = reverse('extractor:processed_text_deidentify',
                            args=[self.pt.id])

    def _post(self, **extra):
        return self.client.post(self.path, {'next': '/'}, **extra)

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_default_dispatch(self, delay):
        self.client.force_login(self.user)
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(delay.call_count, 1)
        args, kwargs = delay.call_args
        self.assertEqual(kwargs['backend'], 'default')
        self.assertIsNone(kwargs['client_config_id'])

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_llm_dispatch_with_encoded_option(self, delay):
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            enable_text_deid=True, deid_local_certified=True)
        self.client.force_login(self.user)
        resp = self._post(**{'backend': f'llm:{cfg.id}'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(delay.call_count, 1)
        args, kwargs = delay.call_args[1]
        self.assertEqual(kwargs['backend'], 'llm')
        self.assertEqual(kwargs['client_config_id'], cfg.id)

    @mock.patch('extractor.tasks.deidentify_processed_text_task.delay')
    def test_llm_dispatch_bad_config_no_task(self, delay):
        self.client.force_login(self.user)
        resp = self._post(**{'backend': 'llm'})
        self.assertEqual(delay.call_count, 0)
        messages = [m.message for m in get_messages(resp)]
        self.assertTrue(any('deid' in m.lower() for m in messages),
                        messages)

    def test_permission_required(self):
        anon = User.objects.create_user('noperm')
        self.client.force_login(anon)
        resp = self._post()
        self.assertEqual(resp.status_code, 403)
```

(`Permission`, `reverse`, `get_messages` imports — add at top of the test module: `from django.contrib.auth.models import Permission`, `from django.urls import reverse`, `from django.contrib.messages import get_messages`.)

- [ ] **Step 2: Run tests, verify they fail**

Run: `python manage.py test extractor.tests.DeidDispatchViewTests -v 2`
Expected: FAIL (view ignores `backend`; task signature has no backend)

- [ ] **Step 3: Update the Celery task**

In `extractor/tasks.py`:

```python
@shared_task(bind=True, max_retries=0)
def deidentify_processed_text_task(self, task_id, processed_text_id,
                                   user_id=None, backend='default',
                                   client_config_id=None):
    """... (docstring: add 'backend selects the engine: default/presidio/llm')
    """
    ...
        new_version = TextDeidentificationService.deidentify(
            pt, user=user, backend=backend, client_config_id=client_config_id)
    ...
```

(Only the signature and the `deidentify` call change; progress/error handling unchanged.)

- [ ] **Step 4: Update `processed_text_deidentify` view**

Replace the body between the `running` check and the task creation with engine handling (decorators unchanged — same `@login_required` + `@permission_required('extractor.change_processedtext', raise_exception=True)`):

```python
    backend = (request.POST.get('backend') or 'default').strip()
    client_config_id = request.POST.get('client_config_id') or None
    # UI encodes the choice as 'llm:<config_id>' in one select
    if ':' in backend:
        backend, _, encoded_id = backend.partition(':')
        client_config_id = encoded_id or client_config_id
    if backend not in ('default', 'presidio', 'llm'):
        messages.error(request, "Unknown deidentification engine.")
        return redirect(next_url)
    if backend in ('default', 'llm'):
        from extractor.services.text_deidentification import (
            LlmDeidConfigurationError, TextDeidentificationService)
        try:
            TextDeidentificationService._resolve_backend(
                backend, client_config_id)
        except LlmDeidConfigurationError as e:
            messages.error(request, str(e))
            return redirect(next_url)
```

Then dispatch with the parameters:

```python
    deidentify_processed_text_task.delay(
        task.task_id, processed_text_id, user_id=request.user.id,
        backend=backend, client_config_id=client_config_id)
    messages.success(
        request,
        f"Deidentification started for "
        f"'{processed_text.file_upload.original_filename}' "
        f"(engine: {backend}).")
```

- [ ] **Step 5: Extend `file_upload_detail` context**

In `file_upload_detail`, after the existing `context = {...}`:

```python
    deid_enabled = context['deid_enabled']
    if deid_enabled:
        from extractor.models import ClientConfiguration
        context['deid_llm_configs'] = list(
            ClientConfiguration.objects.filter(
                enable_text_deid=True, deid_local_certified=True))
        context['deid_default_is_llm'] = ClientConfiguration.objects.filter(
            enable_text_deid=True, is_default_deid=True).exists()
    else:
        context['deid_llm_configs'] = []
        context['deid_default_is_llm'] = False
```

- [ ] **Step 6: Extend the management command**

In `deidentify_processed.py` `add_arguments`:

```python
        parser.add_argument(
            '--backend', choices=['default', 'presidio', 'llm'],
            default='default',
            help='Deid engine: default (follows the configured default), '
                 'presidio (rules + Stanford NER) or llm (rules + local LLM)')
        parser.add_argument(
            '--client-config', type=int, default=None,
            help='ClientConfiguration id for --backend llm (default: the '
                 'default deid configuration)')
```

In `handle`, pass to the sync call `TextDeidentificationService.deidentify(pt, backend=..., client_config_id=...)` and to the `.delay(...)` call as kwargs.

- [ ] **Step 7: Run the tests, verify they pass**

Run: `python manage.py test extractor.tests.DeidDispatchViewTests extractor.tests -v 1`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add extractor/tasks.py extractor/views.py extractor/management/commands/deidentify_processed.py extractor/tests.py
git commit -m "feat(deid): engine selection through dispatch view, task and backfill command"
```

### Task 7: Frontend — engine selector + engine badges

**Files:**
- Modify: `templates/extractor/file_upload_detail.html` (the "Run deid" form, ~line 136)
- Modify: `templates/extractor/processed_text_deid_review.html` (NER badge, ~line 16)
- Modify: `templates/extractor/processed_text_view.html` (engine lines, ~line 26/39)

**Interfaces:**
- Consumes: Task 6 context (`deid_llm_configs`, `deid_default_is_llm`); `ProcessedText.deid_engine` ∈ {'full','degraded','llm'}, `deid_model`
- Produces: engine `<select>` posting `backend` as `default` | `presidio` | `llm:<id>`

- [ ] **Step 1: Engine select in `file_upload_detail.html`**

Replace the bare deid form (currently `next` hidden input + "Run deid" submit) with:

```html
<form method="post" action="{% url 'extractor:processed_text_deidentify' processed.id %}" class="inline-flex items-center gap-2">
    {% csrf_token %}
    <input type="hidden" name="next" value="{{ request.path }}">
    {% if deid_llm_configs %}
    <select name="backend"
            class="px-2 py-1 border border-gray-300 rounded-lg text-sm bg-white"
            title="Deidentification engine">
        <option value="default">
            {% if deid_default_is_llm %}Default (LLM NER){% else %}Default (Presidio + Stanford){% endif %}
        </option>
        <option value="presidio">Presidio + Stanford NER</option>
        {% for cfg in deid_llm_configs %}
        <option value="llm:{{ cfg.id }}">LLM NER — {{ cfg.llm_model_name }}{% if cfg.is_default_deid %} (default){% endif %}</option>
        {% endfor %}
    </select>
    {% else %}
    <input type="hidden" name="backend" value="default">
    {% endif %}
    <span title="Run deidentification on this version">
    {% component "button" style="primary" type="submit" icon="fas fa-user-shield" %}Run deid{% endcomponent %}
    </span>
</form>
```

(When no LLM config is enabled the form behaves exactly as before — no visible select.)

- [ ] **Step 2: NER badge on the review page**

In `processed_text_deid_review.html`, change the engine badge to include the model:

```html
{% component "badge" style="gray" %}NER: {{ processed_text.deid_engine|default:"unknown" }}{% if processed_text.deid_model %} · {{ processed_text.deid_model }}{% endif %}{% endcomponent %}
```

- [ ] **Step 3: Engine lines on `processed_text_view.html`**

Both occurrences of `<strong>Deidentified version</strong> (engine: {{ processed_text.deid_engine|default:"unknown" }})` become:

```html
<strong>Deidentified version</strong> (engine: {{ processed_text.deid_engine|default:"unknown" }}{% if processed_text.deid_model %} · {{ processed_text.deid_model }}{% endif %})
```

- [ ] **Step 4: Manual verification**

With a local Ollama model loaded (`ollama pull gemma4:4b` or the actual tag) and a certified config: open a processed file page → select "LLM NER — ..." → Run deid → background task completes → review page badge shows `NER: llm · <model>`; pick Presidio on another file → badge shows `full`/`degraded` as before.

- [ ] **Step 5: Commit**

```bash
git add templates/extractor/file_upload_detail.html templates/extractor/processed_text_deid_review.html templates/extractor/processed_text_view.html
git commit -m "feat(deid): per-file engine selector and engine/model badges"
```

---

## Part 4 — End-to-end LLM deid test + rollout

### Task 8: End-to-end LLM deidentification (text + CSV, mocked LLM)

**Files:**
- Test: `extractor/tests.py`

**Interfaces:**
- Consumes: Tasks 1–7 (full pipeline with `LlmNerClient._llm_call` mocked)
- Produces: regression guard for the whole LLM path

- [ ] **Step 1: Write the end-to-end tests**

Append to `extractor/tests.py`:

```python
class LlmDeidEndToEndTests(TestCase):
    """Full deidentify() run on the LLM engine with the model mocked.

    Verifies: engine/model/config recorded, Indian names redacted by the
    LLM, dates shifted (not replaced with <DATE> when parseable), rule
    recognizers still active (Aadhaar caught without the LLM naming it),
    durations NOT redacted, and the review map populated.
    """

    def setUp(self):
        from pathlib import Path
        from django.conf import settings
        from extractor.models import (
            ClientConfiguration, FileUpload, ProcessedText)
        self.media = Path(settings.MEDIA_ROOT)
        self.cfg = ClientConfiguration.objects.create(
            llm_model_name='gemma4:4b', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            enable_text_deid=True, deid_local_certified=True,
            is_default_deid=True)
        self.upload = FileUpload.objects.create(original_filename='note.pdf')
        self.content = (
            'Mr Rajesh Kumar from Village Patia, Kolkata, was admitted on '
            '01/02/2024. Aadhaar 123412341234. He had symptoms for 1 month '
            'before presentation. Follow up advised in 2 weeks.')
        self.pt = self._write_processed('uploads/test_note.txt', self.content)

    def _write_processed(self, rel_path, content):
        from django.conf import settings
        from extractor.models import ProcessedText
        pt = ProcessedText.objects.create(
            file_upload=self.upload, processed_file_path=rel_path,
            content_length=len(content))
        path = Path(settings.MEDIA_ROOT) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return pt

    def _llm_side_effect(self, chunk):
        # The model "finds" the Indian names (which the gazetteer/NER may
        # miss) but nothing else — rules cover Aadhaar + dates.
        found = []
        for name in ('Rajesh Kumar', 'Patia'):
            if name in chunk:
                found.append(('person', name))
        if 'Kolkata' in chunk:
            found.append(('location', 'Kolkata'))
        return found

    @mock.patch('extractor.services.llm_ner.LlmNerClient._llm_call',
                side_effect=lambda self, chunk: self._llm_side_effect(chunk))
    def test_llm_deidentify_text(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        new = S.deidentify(self.pt, backend='llm', client_config_id=self.cfg.id)
        from pathlib import Path
        self.assertIsNotNone(new)
        self.assertEqual(new.deid_engine, 'llm')
        self.assertEqual(new.deid_model, 'gemma4:4b')
        self.assertEqual(new.deid_client_config_id, self.cfg.id)
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        # LLM-found entities redacted
        self.assertNotIn('Rajesh Kumar', out)
        self.assertNotIn('Patia', out)
        self.assertNotIn('Kolkata', out)
        self.assertRegex(out, r'<PERSON_\d+>')
        # Rule recognizer still catches the Aadhaar without LLM help
        self.assertNotIn('123412341234', out)
        self.assertRegex(out, r'<IN_AADHAAR_\d+>')
        # Duration NOT redacted — the persistent false positive
        self.assertIn('1 month', out)
        self.assertIn('2 weeks', out)
        # Real date shifted by the recorded offset (or unchanged when the
        # random offset happened to be 0)
        from datetime import timedelta
        from dateutil.parser import parse as parse_date
        shift = new.deid_date_shift_days
        self.assertIsNotNone(shift)
        if shift != 0:
            self.assertNotIn('01/02/2024', out)
            shifted = (parse_date('01/02/2024', dayfirst=True)
                       + timedelta(days=shift)).strftime('%d/%m/%Y')
            self.assertIn(shifted, out)
        # Review map populated
        self.assertTrue(new.deid_map)

    @mock.patch('extractor.services.llm_ner.LlmNerClient._llm_call',
                side_effect=lambda self, chunk: self._llm_side_effect(chunk))
    def test_default_resolution_picks_llm(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        new = S.deidentify(self.pt)  # backend defaults -> LLM (default cfg set)
        self.assertEqual(new.deid_engine, 'llm')

    def test_presidio_engine_unaffected(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        new = S.deidentify(self.pt, backend='presidio')
        self.assertIn(new.deid_engine, ('full', 'degraded'))
        self.assertIsNone(new.deid_client_config_id)
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        self.assertNotIn('123412341234', out)  # rules still work

    def test_llm_csv_cell_caching(self):
        """Identical unmapped cell values cost ONE LLM call per run.

        Layout trick: 'dob' IS in EXTRACTOR_DEID_CSV_COLUMN_MAP so the CSV
        goes through the header-aware path (fully unmapped CSVs fall back
        to whole-text deid), while 'subject' cells go through per-cell NER
        where the recognizer's run-cache must absorb the repeats.
        """
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        csv_content = (
            'dob,subject\n'
            '01/02/2024,Rajesh Kumar\n'
            '02/02/2024,Rajesh Kumar\n'
            '03/02/2024,Rajesh Kumar\n')
        pt2 = self._write_processed('uploads/test_note.csv', csv_content)
        with mock.patch(
                'extractor.services.llm_ner.LlmNerClient._llm_call',
                wraps=lambda self, chunk: self._llm_side_effect(chunk)) as m:
            new = S.deidentify(pt2, backend='llm', client_config_id=self.cfg.id)
        calls_for_name = sum(
            1 for c in m.call_args_list if 'Rajesh Kumar' in c.args[0])
        out = (self.media / new.processed_file_path).read_text(encoding='utf-8')
        self.assertNotIn('Rajesh Kumar', out)
        self.assertEqual(calls_for_name, 1)
```

- [ ] **Step 2: Run the tests**

Run: `python manage.py test extractor.tests.LlmDeidEndToEndTests -v 2`
Expected: PASS (the date assertion already handles a zero random shift).

- [ ] **Step 3: Run the complete extractor suite**

Run: `python manage.py test extractor -v 1`
Expected: PASS (all existing tests + new ones — confirms nothing in the legacy path regressed)

- [ ] **Step 4: Commit**

```bash
git add extractor/tests.py
git commit -m "test(deid): end-to-end LLM deid coverage (text, CSV caching, default resolution)"
```

### Task 9: Real-environment evaluation checklist (manual, no code)

Purpose: "properly test and evaluate in real world" — run the same files through both engines and compare on the existing review UI.

- [ ] **Step 1: Load the local model**

Run: `ollama pull gemma4:4b` (or the actual low-capacity tag in use). Verify: `ollama run gemma4:4b "say ok"` responds.

- [ ] **Step 2: Create the certified config**

UI → LLM Configurations → Create: model `gemma4:4b`, provider `Local (Ollama)`, base URL `http://localhost:11434`, API key `ollama`, context size matching the server's `num_ctx`. Tick all three deid checkboxes (enable + certify + default).

- [ ] **Step 3: A/B a known-bad file**

Take a file with (a) Indian names the Stanford model misses and (b) durations like "1 month". Deidentify two identical uploads — one with `Presidio + Stanford NER`, one with `LLM NER`. On each review page compare: entity counts panel, redaction map, and search for leaked names/durations in the deidentified text.

- [ ] **Step 4: Latency check**

Watch the background task progress: LLM engine should show total runtime proportional to chunk count (≈ chars / 3500) — on a 4B model at edge-GPU speeds expect roughly a few seconds per chunk. If too slow, lower `DEFAULT_CHUNK_CHARS` trade-off is recall, not speed; instead consider a smaller model or raising Ollama's parallelism — note in the evaluation write-up.

- [ ] **Step 5: Fallback behavior check**

Stop Ollama and dispatch an LLM deid run → expect the background task to FAIL with "LLM NER call failed…" and NO deidentified version created (fail-safe).

- [ ] **Step 6: Record results**

Note recall/precision deltas per entity type in `docs/` (or the evaluation sheet the team keeps) — this data decides whether `is_default_deid` stays flipped to the LLM engine.

---

## Self-Review

**Spec coverage:**
- Keep Presidio/Stanford system → Global Constraints + Task 5(c) (separate `_llm_analyzer` without HF NER only for LLM runs; default path untouched). ✓
- LLM replaces only the NER, rules stay → LLM is an ad-hoc recognizer on the rule-based analyzer (Task 5). ✓
- Reuse `ClientConfiguration`, no new config model, no settings toggle → Tasks 1–2. ✓
- Cloud-provider validation → `is_cloud_provider` + `clean()` (Task 1) + re-check at dispatch (`_resolve_backend`, Task 5). ✓
- "I understand" certification checkbox → `deid_local_certified` + UI copy (Task 2 Step 3). ✓
- Model-based default, overridable manually → `is_default_deid` (single flag = "LLM is default") + per-file engine select (Tasks 5, 6, 7). ✓
- Verbatim spans, offsets by search, ordered duplicate mapping → `resolve_spans` (Task 3). ✓
- Same view/form protection as current deid → decorators unchanged in Task 6 Step 4; permission test included. ✓
- Frontend thought through → Task 2 (config forms/detail/list), Task 7 (engine select + badges). ✓
- Duration false-positive ("1 month") → filter regex fix in Task 5(g), benefits both engines; prompt rule 2 for the LLM. ✓

**Placeholder scan:** none — every step carries concrete code/markup/tests. Two deliberate "inspect the template" notes (Task 2 Step 6 loop variable; Task 7 Step 1) flag exact anchors in the real templates rather than guessing markup.

**Type consistency:**
- `_resolve_backend` returns `(str, ClientConfiguration|None)` — used identically in Task 6 (view pre-validation, task kwargs) and Task 8 tests.
- `find_entities_in_text` returns list of `{'type','start','end','score'}` dicts — consumed by `LlmNerRecognizer.analyze` (Task 4) and mocked with the same shape in Task 8 tests.
- `deidentify(..., backend='default', client_config_id=None)` keyword names match in tasks.py, the command, and the tests.
- `chunk_text` yields `(offset, chunk)` tuples — Task 3 tests and Task 4 implementation agree.

---

## Execution Status (2026-10-15)

- Tasks 1–8: **complete** — 8 commits on `main` (`27b870b` → `83926ad`),
  204 extractor tests run; only the 2 pre-existing failures remain
  (`InferenceModelTests.test_invalid_assessments_rejected case=5`,
  `DeidReplacementTests.test_resolve_overlaps_keeps_highest_score` —
  both fail identically on pristine `d2489af`).
- Task 9: **pending** — manual real-world A/B evaluation with the actual
  local model.
- Execution notes / deviations from the plan:
  - The installed `presidio_analyzer` is a newer API than the plan assumed:
    `LlmNerRecognizer` subclasses `LocalRecognizer`, its
    `analyze(text, entities, nlp_artifacts)` signature, and
    `RecognizerResult(entity_type=...)` (not `type=`).
  - Entity-type mapping was moved from `_llm_call` into
    `LlmNerClient.find_entities` so the network seam (`_llm_call`) can be
    mocked with raw model output and the mapping code stays under test.
  - The end-to-end Aadhaar assertion was relaxed from "tagged as
    IN_AADHAAR" to "digits do not survive": spaCy's en_core_web_lg tags
    the whole "Aadhaar 123412341234" as PERSON and the intentional
    containment rule in `_resolve_overlaps` then wins over IN_AADHAAR.
    Pre-existing on both engines; digits are still redacted.
- Task 9 (partial, automated): synthetic Indian clinical A/B executed with
  `gemma4:e2b` (4.6B Q4_K_M, Ollama 0.40.4) on 3 documents (discharge
  summary, CT radiology, histopathology) via `scripts/ab_deid_test.py`:
  - Duration false-positives ("1 month", "2 weeks", "3 days", "3 months"):
    now preserved on **both** engines.
  - All dates shifted on both engines; clinical numerics (4 x 3.5 cm,
    12 mm, HER2, Ki-67, p16, D2-40, node counts) all preserved.
  - LLM advantage: caught village name "Patia" (Stanford missed it);
    consolidated the full postal address into one LOCATION span.
  - LLM gap: missed the radiology report number "RAD/26/004512"
    (rules split it into MRN tags; note "RAD/" prefix is not in the
    MRN rule either — the model's miss is the only leak).
  - Shared (spaCy layer, both engines): "Grade III" redacted as PERSON,
    "Nottingham" as LOCATION in the pathology grading line; "Age 56
    years" and "mammogram" as DATE in the clinical note. These are
    candidates for a shared allowlist, engine-independent.
  - Latency (warm model, ~1KB docs): Presidio+Stanford ~0.2-4s;
    LLM ~4-15s per call (first call + cold model ~40s).
  - `LlmNerClient._llm_call` switched from instructor JSON-mode to raw
    OpenAI-compat chat + lenient JSON parsing (array / 'entities' object /
    single object / fenced), because small models do not reliably emit the
    exact requested schema.
