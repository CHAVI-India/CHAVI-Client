# De-Identification Pipeline Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the text de-identification pipeline fully user-configurable via a new
`TextDeidentificationPipelineConfig` model, decoupling all text-deid settings from
hard-coded `settings.py` values, and add a `model_type` (System-1 / System-2) to
`ClientConfiguration` so pipelines can reference the right model kind.

**Architecture:** Presidio + rule recognizers and the date-shift algorithm are
always-on. Per pipeline the user picks the NER engine (bundled spaCy — default — or
any HuggingFace NER model, downloaded on demand), an optional local System-2 LLM recall
pass (FK to a certified System-2 `ClientConfiguration`), an optional System-1
second-check model (FK to a System-1 `ClientConfiguration`), the date-shift range,
and an editable
rules/regex bundle. The service (`text_deidentification.py`) is refactored to build the
analyzer and run the filters from a pipeline object instead of settings. The
`ClientConfiguration` gains a `model_type` field and drops the now-obsolete
`is_default_deid` + `enable_text_deid`; the "default deid engine" concept moves to the
pipeline's `is_default`.

**Tech Stack:** Django 4.x, Presidio AnalyzerEngine, spaCy, transformers
(`HuggingFaceNerRecognizer`), Ollama (System-1 `/v1/systemone` decision endpoint),
Django JSONField, migrations.

**Spec:** The user's requirements in this session (see "Locked design" below, which is
the self-contained contract). Prior context: `docs/superpowers/plans/2026-10-17-deid-pipeline-test.md`
(the staged test that motivated spacy-default + LLM-recall + System-1-judge).

## Status: COMPLETE (2026-10-17)

All 8 tasks implemented and verified. Summary of what shipped:

- **Task 1** — `ClientConfiguration.model_type` (`system2`/`system1`) added; `enable_text_deid`
  and `is_default_deid` removed; `clean()` reworked so a System-2 config that is
  `deid_local_certified` must use a local (non-cloud) endpoint. A System-1 config may use
  any endpoint (no certification required).
- **Task 2** — `TextDeidentificationPipelineConfig` added (identity, `ner_engine` spacy/hf,
  `hf_*` incl. `hf_token`, `system2_model`, `system_1_model_integration` + `system_1_model`,
  `system_1_threshold`/`_window`, `extractor_date_shift_range`, `rules`, `min_confidence`,
  `is_default`); `ProcessedText.deid_pipeline` FK added; auto-name + collision-safe slug;
  cross-field validation (System-1 on↔model, System-2 must be certified+local, one default).
  Migration `0033` + seed migration `0034` (default `spaCy · no-LLM · rules`).
- **Task 3** — `extractor/services/system1_judge.py` (per-span decision-model judge with a
  `/v1/systemone` endpoint; `judge_span` returns the `noul` probability).
- **Task 4** — `extractor/services/deid_rules.py` (shared defaults); the filter stages
  (`_filter_mechanical`/`_filter_dates`/`_filter_clinical`/`_filter_results`) are
  parameterized by `rules` (None = defaults), behaviour-identical.
- **Task 5** — `_build_analyzer_for(pipeline)`, `_apply_precision`, `_filter_system1` (DATE /
  DATE_TIME bypass the judge; everything else is probability-gated), `_deidentify_text_for`,
  `_deidentify_csv_for`, `_resolve_pipeline(pipeline, backend, client_config_id)`; `deidentify()`
  now runs from a pipeline (date-shift range read per pipeline, falling back to the setting).
- **Task 6** — `pipeline_id` threaded through the Celery task, the backfill command
  (`--pipeline`), and the dispatch view (which also accepts `pipeline:<id>` in the engine
  select, alongside the legacy `llm:<id>` / `presidio` / `openmed`).
- **Task 7** — `ClientConfiguration` UI: `model_type` select in, obsolete checkboxes out
  (create/edit/detail/list templates).
- **Task 8** — Pipeline CRUD (crispy form, list/create/detail/edit/delete) + per-file
  pipeline selector on the file detail page.

**Verification:**
- `manage.py check` clean.
- `manage.py test extractor` green: **234 tests, 2 failures — both pre-existing and
  unrelated** (`InferenceModelTests.test_invalid_assessments_rejected`,
  `DeidReplacementTests.test_resolve_overlaps_keeps_highest_score`).
- Test-DB builds hit a **pre-existing flaky migration** (`lookup` `0002`…`0058` fetch CSVs
  from a rate-limited GitLab raw endpoint). To keep the suite runnable offline, a dev test
  settings module `chavi_client/test_settings_netstub.py` redirects those CSV URLs to a local
  mirror when present (env: `CHAVI_LOOKUP_LOCAL_ROOT`); it is a no-op when the mirror is
  absent and modifies no production file.
  Run: `DJANGO_SETTINGS_MODULE=chavi_client.test_settings_netstub manage.py test extractor`.

## Global Constraints

- **Do not remove existing functionality.** The legacy per-file engine overrides
(`presidio` / `openmed` / `llm:<id>` / `default`) must keep working; the new pipeline
selection is additive and becomes the primary path.
- **CPU-only / local:** System-2 LLM must be a local/LAN endpoint and user-certified
(`deid_local_certified`). System-1 models may be external (they only see short
snippets).
- **Age is never de-identified; durations/intervals are never de-identified; real dates
are still shifted.** These behaviours live in the default `rules` bundle and must be
preserved (existing `DurationFilterTests` / `FilterDecompositionTests` are the guard).
- **Text-deid settings move to the model.** `EXTRACTOR_DEID_SCORE_THRESHOLD`,
`EXTRACTOR_DEID_DROP_ENTITY_TYPES`, `EXTRACTOR_DEID_CLINICAL_ALLOWLIST`,
`EXTRACTOR_DEID_NER_BACKEND`, and the text use of `DEID_HF_NER_MODEL`/
`DEID_HF_LABEL_MAP`/`DEID_HF_NER_THRESHOLD` are superseded by pipeline fields. The
`DEID_HF_*` settings are KEPT (still used by the separate Dicom pixel-scrub
analyzer); only the *text* code stops reading them. `EXTRACTOR_DEID_DATE_SHIFT_RANGE`  
is also shifted to the model. 

- **Only one default pipeline** at a time (`is_default`).
- **Test command:** `venv/bin/python manage.py test extractor -v 1 --noinput`.
- **Pre-existing failures (NOT caused by this work — ignore):**
`test_invalid_assessments_rejected`, `test_resolve_overlaps_keeps_highest_score`.
- Python interpreter: `venv/bin/python` (3.13). Run from repo root
`/mnt/share/CHAVI-Client`.

---

## File Structure

- **Modify `extractor/models.py`** — add `ModelTypeChoices`, `DeidNerEngineChoices`,
`DEFAULT_DEID_RULES` / `DEFAULT_HF_LABEL_MAP` + default callables, the
`TextDeidentificationPipelineConfig` model; change `ClientConfiguration` (add
`model_type`, drop `is_default_deid` + `enable_text_deid`, rework `clean()`); add a
`deid_pipeline` FK to `ProcessedText`.
- **Create `extractor/services/system1_judge.py`** — the System-1 decision-model client,
relocated from `scripts/pipeline_test.py`, reading endpoint/model/threshold/window
from a `ClientConfiguration`.
- **Modify `extractor/services/text_deidentification.py`** — `_build_analyzer` +
`deidentify()` consume a pipeline; the three filter stages read from `pipeline.rules`;
System-1 judge integrated; HF token applied at download.
- **Modify `extractor/forms.py`** — `ClientConfigurationForm` (model_type; drop the two
obsolete booleans), `TextDeidentificationPipelineConfigForm` (filtered pickers, rules
editor, auto-name).
- **Modify `extractor/views.py`** — pipeline CRUD views, pipeline resolution in the
dispatch path, per-file pipeline selector, remove obsolete-flag handling.
- **Modify `extractor/urls.py`** — pipeline routes.
- **Modify `extractor/tasks.py`** — deid task takes `pipeline_id` (legacy `backend`
kept for compat).
- **Modify `extractor/management/commands/deidentify_processed.py`** — `--pipeline` arg.
- **Modify templates:** `client_configuration_create.html` / `_edit.html` / `_detail.html`
(model_type + deid cert; drop obsolete checkboxes), new `pipeline_*.html` templates,
`file_upload_detail.html` + `processed_text_deid_review.html` (pipeline selector).
- **Modify `extractor/tests.py`** — new tests per task.

---

## Locked Design (the contract)

Everything below is final; later tasks reference these exact names/types.

### `ClientConfiguration` delta

```python
class ModelTypeChoices(models.TextChoices):
    SYSTEM2 = 'system2', 'Traditional autoregressive LLM (System 2)'
    SYSTEM1 = 'system1', 'Decision model (System 1)'

# ADD to ClientConfiguration (default system2 so existing LLMs are correct):
model_type = models.CharField(
    max_length=12, choices=ModelTypeChoices.choices,
    default=ModelTypeChoices.SYSTEM2,
    help_text="Kind of model. System 2 = a traditional autoregressive large "
              "language model (used for extraction and as the main de-identification "
              "LLM). System 1 = a fast decision model that judges short text snippets.")

# REMOVE: is_default_deid
# REMOVE: enable_text_deid
# KEEP:   deid_local_certified   (now the deid gate)
```

`ClientConfiguration.clean()` deid block is replaced by (the certification now implies
local, so it is the only thing that triggers the local-only checks):

```python
        if self.deid_local_certified:
            from extractor.services.url_policy import (
                is_cloud_provider, is_local_endpoint)
            errors = {}
            if is_cloud_provider(self.model_provider):
                errors['model_provider'] = (
                    'A model certified for local de-identification cannot use a '
                    'cloud provider.')
            if not is_local_endpoint(self.model_base_url):
                errors['model_base_url'] = (
                    'A model certified for local de-identification must use a '
                    'local endpoint.')
            if errors:
                raise ValidationError(errors)
```

### `TextDeidentificationPipelineConfig` (new)

```python
class DeidNerEngineChoices(models.TextChoices):
    SPACY = 'spacy', 'spaCy (bundled)'
    HF    = 'hf', 'HuggingFace model'


DEFAULT_DEID_RULES = {
    'drop_entity_types': ['ID', 'AGE', 'NRP'],
    'clinical_allowlist': [
        'nottingham', 'grade i', 'grade ii', 'grade iii', 'grade iv',
        'mammogram', 'mammography', 'ce', 'cea', 'fnac', 'fna',
        'hourly', 'spo2', 'jvp',
    ],
    # regexes that mark a DATE_TIME hit as a duration/age/dose -> KEEP, not redact
    'date_keep_patterns': [
        r'^\d{1,3}%?$',
        r'^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$',
        r'^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$',
        r'^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$',
        r'^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$',
        r'^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$',
        r'^\d{1,3}\s*/\s*min\b\.?$',
        r'^\d{1,2}:\d{2}$',
        r'^(?!(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b)[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$',
    ],
    # NOTE: no trailing `$` — matches the *prefix* of the surface
    # (e.g. 'HB 13.2', 'Spo2 95'); must stay exactly as the shipped filter.
    'clinical_prefix_pattern':
        r'^(hb|h\.b\.?|tabs?\b|inj\b|caps?\b|iv\b|po\b|oral\b|spo2?|s\.p\.o|jvp|ef\b|bp\b|pr\b|hr\b|wt\b|lmp\b)',
    'location': {'min_length': 4, 'reject_lowercase': True,
                 'pattern': r'^[A-Za-z]?-?\d[\w-]*$'},
}


def _default_deid_rules():
    import copy
    return copy.deepcopy(DEFAULT_DEID_RULES)


DEFAULT_HF_LABEL_MAP = {
    'PATIENT': 'PERSON', 'HCW': 'PERSON',
    'HOSPITAL': 'ORGANIZATION', 'VENDOR': 'ORGANIZATION',
    'ID': 'MEDICAL_RECORD_NUMBER',
    'DATE': 'DATE_TIME',
    'PHONE': 'PHONE_NUMBER',
}


def _default_hf_label_map():
    import copy
    return copy.deepcopy(DEFAULT_HF_LABEL_MAP)


class TextDeidentificationPipelineConfig(models.Model):
    """One configurable text-deid pipeline.

    Always-on (not fields): Presidio + rule recognizers, and the date-shift
    *algorithm*. Per pipeline: NER engine, optional System-2 LLM pass, optional
    System-1 second-check, the date-shift range, and the editable rules/regex
    bundle.
    """
    name = models.CharField(max_length=200, unique=True, blank=True,
        help_text="Auto-generated from the chosen stages when blank; editable. "
                  "Must be unique.")
    slug = models.SlugField(unique=True, blank=True,
        help_text="Stable unique technical id, auto-derived from the name.")

    ner_engine = models.CharField(max_length=12,
        choices=DeidNerEngineChoices.choices,
        default=DeidNerEngineChoices.SPACY)
    hf_model_id = models.CharField(max_length=255, blank=True,
        help_text="HuggingFace model id when the engine is a HuggingFace model, "
                  "e.g. 'StanfordAIMI/stanford-deidentifier-base'. Downloaded on "
                  "first use.")
    hf_token = EncryptedCharField(max_length=255, blank=True,
        help_text="HuggingFace access token (huggingface.co/settings/tokens). "
                  "Used to download the model and for private/gated models. "
                  "Leave blank for public models.")
    hf_label_map = models.JSONField(default=_default_hf_label_map, blank=True,
        help_text="Maps the model's labels to the types this pipeline redacts. "
                  "Pre-filled with clinical defaults.")
    hf_threshold = models.FloatField(default=0.20,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Confidence floor for the HuggingFace model (lower = catches "
                  "more, redacts more by mistake).")

    system2_model = models.ForeignKey(
        'ClientConfiguration', null=True, blank=True, on_delete=models.PROTECT,
        related_name='deid_pipelines_s2',
        limit_choices_to=models.Q(model_type='system2',
                                  deid_local_certified=True),
        help_text="Optional large language model that runs on this machine or "
                  "your local network, to help catch personal details the main "
                  "detector misses. Cloud services are not allowed. Leave empty "
                  "to use only the main detector.")

    system_1_model_integration = models.BooleanField(default=False,
        help_text="Ask a fast second-check model to review each flagged item "
                  "before it is redacted, deciding redact or keep. Off (default) "
                  "uses the built-in rules instead, which is faster.")
    system_1_model = models.ForeignKey(
        'ClientConfiguration', null=True, blank=True, on_delete=models.PROTECT,
        related_name='deid_pipelines_s1',
        limit_choices_to=models.Q(model_type='system1'),
        help_text="Which second-check model to use. Needed only when the "
                  "second-check option is on. An external API endpoint is "
                  "allowed for these.")
    system_1_threshold = models.FloatField(default=0.5,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="How confident the second-check model must be to keep an item "
                  "redacted (0-1).")
    system_1_window = models.PositiveIntegerField(default=90,
        validators=[MinValueValidator(8)],
        help_text="Surrounding text (chars each side) shown to the second-check "
                  "model.")
    extractor_date_shift_range = models.PositiveIntegerField(default=90,null=True,blank=True, help_text= "Date shift range for the date shifting. A random value is chosen from this range"). 
    rules = models.JSONField(default=_default_deid_rules, blank=True,
        help_text="Rules and regex patterns that decide what is redacted versus "
                  "kept. Ships with clinical defaults; view and extend here. "
                  "Edits apply to this pipeline only.")
    min_confidence = models.FloatField(default=0.35,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Minimum confidence (0-1) an item must have before it is "
                  "redacted. Higher = stricter (fewer false redactions, more "
                  "misses). Lower = more thorough (more catches, more false "
                  "redactions).")
    
    is_default = models.BooleanField(default=False,
        help_text="Pipeline new files use by default. Only one may be default.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['ner_engine', 'hf_model_id', 'system2_model',
                        'system_1_model', 'system_1_model_integration'],
                name='deid_pipeline_unique_identity'),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.ner_engine == DeidNerEngineChoices.HF:
            if not (self.hf_model_id or '').strip():
                errors['hf_model_id'] = (
                    'Enter a HuggingFace model id - required for a '
                    'HuggingFace NER engine.')
        else:
            if (self.hf_model_id or '').strip():
                errors['hf_model_id'] = (
                    'Clear the HuggingFace model id; it is only used for a '
                    'HuggingFace NER engine.')
        if self.system_1_model_integration:
            if self.system_1_model_id is None:
                errors['system_1_model'] = (
                    'Choose a second-check (System-1) model, or switch the '
                    'second-check option off.')
        else:
            if self.system_1_model_id is not None:
                errors['system_1_model'] = (
                    'The second-check option is off, so a System-1 model '
                    'cannot be selected.')
        if self.system2_model_id is not None:
            from extractor.services.url_policy import (
                is_cloud_provider, is_local_endpoint)
            s2 = self.system2_model
            problems = []
            if s2.model_type != ModelTypeChoices.SYSTEM2:
                problems.append('it is not a System-2 model')
            if is_cloud_provider(s2.model_provider):
                problems.append('a cloud provider is not allowed')
            if not is_local_endpoint(s2.model_base_url):
                problems.append('its endpoint is not local')
            if not s2.deid_local_certified:
                problems.append('local execution is not certified')
            if problems:
                errors['system2_model'] = (
                    f"'{s2.llm_model_name}' cannot be used for the local-LLM "
                    f"pass: " + ', '.join(problems) + '.')
        if self.is_default and TextDeidentificationPipelineConfig.objects.exclude(
                pk=self.pk).filter(is_default=True).exists():
            errors['is_default'] = (
                'Another pipeline is already the default. Unset its '
                '"default" flag first.')
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not (self.name or '').strip():
            self.name = self._generate_name()
        if not (self.slug or '').strip():
            from django.utils.text import slugify
            base = slugify(self.name) or 'pipeline'
            slug, i = base, 2
            while TextDeidentificationPipelineConfig.objects.filter(
                    slug=slug).exclude(pk=self.pk).exists():
                slug, i = f'{base}-{i}', i + 1
            self.slug = slug
        super().save(*args, **kwargs)

    def _generate_name(self):
        ner = ('spaCy' if self.ner_engine == DeidNerEngineChoices.SPACY
               else (self.hf_model_id or 'HF model').split('/')[-1])
        s2 = (self.system2_model.llm_model_name
              if self.system2_model_id else 'no-LLM')
        s1 = ('second-check' if self.system_1_model_integration else 'rules')
        base = ' · '.join([ner, s2, s1])
        i = 2
        while TextDeidentificationPipelineConfig.objects.filter(name=base).exclude(
                pk=self.pk).exists():
            base, i = f'{base} ({i})', i + 1
        return base
```

### `ProcessedText` delta

```python
    deid_pipeline = models.ForeignKey(
        'TextDeidentificationPipelineConfig', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='deid_runs',
        help_text="The pipeline that produced this deidentified version.")
```

(`deid_engine` / `deid_model` / `deid_client_config` stay for display; they are now
filled from the pipeline — `deid_engine` gets the `ner_engine`, `deid_model` gets
`hf_model_id` or the System-2 model name, `deid_client_config` the System-2 config.)

---

### Task 1: `ClientConfiguration` — add `model_type`, drop obsolete flags, rework `clean()`

**Files:**

- Modify: `extractor/models.py` (add `ModelTypeChoices`; change `ClientConfiguration`)
- Create migration: `extractor/migrations/0XXX_clientconfig_model_type.py`
- Test: `extractor/tests.py` (new `ClientConfigModelTypeTests`)

**Interfaces:**

- Produces: `ModelTypeChoices` (`SYSTEM2='system2'`, `SYSTEM1='system1'`);
`ClientConfiguration.model_type` (choices, default `system2`); `is_default_deid`
and `enable_text_deid` removed; `deid_local_certified` kept; `clean()` enforces
local-only when `deid_local_certified` is set.

- [ ] **Step 1: Write the failing tests**

Add to `extractor/tests.py`:

```python
class ClientConfigModelTypeTests(TestCase):
    def _cfg(self, **kw):
        base = dict(llm_model_name='m', model_provider='Local (Ollama)',
                    model_api_key='k', model_base_url='http://localhost:11434')
        base.update(kw)
        return ClientConfiguration.objects.create(**base)

    def test_default_model_type_is_system2(self):
        c = self._cfg()
        self.assertEqual(c.model_type, 'system2')

    def test_obsolete_fields_removed(self):
        c = self._cfg()
        self.assertFalse(hasattr(c, 'is_default_deid'))
        self.assertFalse(hasattr(c, 'enable_text_deid'))

    def test_certified_cloud_rejected(self):
        with self.assertRaises(ValidationError):
            c = ClientConfiguration(llm_model_name='g',
                                    model_provider='OpenAI', model_api_key='k',
                                    model_base_url='https://api.openai.com/v1',
                                    deid_local_certified=True)
            c.full_clean()

    def test_certified_local_ok(self):
        c = self._cfg(deid_local_certified=True)
        c.full_clean()  # no error
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.ClientConfigModelTypeTests -v 2 --noinput`
Expected: FAIL (`model_type` does not exist; `is_default_deid` still present).

- [ ] **Step 3: Implement the model change**

In `extractor/models.py`: add `ModelTypeChoices` (above `ClientConfiguration`); in
`ClientConfiguration` add `model_type`; delete the `is_default_deid` and
`enable_text_deid` field definitions; replace the whole deid block in `clean()`
(from `if self.enable_text_deid or self.is_default_deid:` to the end of that block)
with the `if self.deid_local_certified:` block from the Locked design.

- [ ] **Step 4: Make the migration**

Run: `venv/bin/python manage.py makemigrations extractor --name clientconfig_model_type`
Open the generated file; confirm it (a) adds `model_type` with `default='system2'`,
(b) removes `is_default_deid` and `enable_text_deid`. Remove the `RemoveField`
operations' risk: because the data migration for the pipeline (Task 2) still reads
`is_default_deid`, **order matters** — keep the `RemoveField` ops but ensure the
Task-2 data migration that references the old flags runs BEFORE the removal. Simplest
safe order: do the removal in this file, and have Task 2's seed data migration run
`RunPython` using the NEW pipeline fields only (not the old flags). (No backfill from
the old flags is required — the shipped default pipeline is a fixed spaCy row.)

- [ ] **Step 5: Run the tests + a full suite pass**

Run: `venv/bin/python manage.py test extractor.tests.ClientConfigModelTypeTests -v 2 --noinput`
Then: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: the 4 new tests pass. Existing tests that referenced
`enable_text_deid` / `is_default_deid` (search: `grep -rn "is_default_deid\|enable_text_deid" extractor/tests.py`)
must be updated to set `model_type` / `deid_local_certified` instead — fix each hit in
this task so the suite is green (only the 2 known pre-existing failures remain).

- [ ] **Step 6: Commit**

```bash
git add extractor/models.py extractor/migrations/ extractor/tests.py
git commit -m "feat(deid): add model_type to ClientConfiguration; drop is_default_deid + enable_text_deid"
```

---

### Task 2: `TextDeidentificationPipelineConfig` model + `ProcessedText.deid_pipeline` + migration + seed default

**Files:**

- Modify: `extractor/models.py` (add `DeidNerEngineChoices`, `DEFAULT_DEID_RULES`,
`DEFAULT_HF_LABEL_MAP`, the two default callables, `TextDeidentificationPipelineConfig`,
and `ProcessedText.deid_pipeline`)
- Create migration: `extractor/migrations/0YYY_deid_pipeline_config.py`
- Create data migration: `extractor/migrations/0ZZZ_seed_default_pipeline.py`
- Test: `extractor/tests.py` (new `DeidPipelineModelTests`)

**Interfaces:**

- Produces: `TextDeidentificationPipelineConfig` with fields exactly as in the Locked
design; `ProcessedText.deid_pipeline` (nullable FK). A seed row: a spaCy pipeline
named `spaCy · no-LLM · rules`, `is_default=True`, slug `spacy-no-llm-rules`.

- [ ] **Step 1: Write the failing tests**

```python
class DeidPipelineModelTests(TestCase):
    def test_auto_name_and_slug(self):
        p = TextDeidentificationPipelineConfig.objects.create(
            ner_engine='spacy', is_default=True)
        self.assertEqual(p.name, 'spaCy · no-LLM · rules')
        self.assertTrue(p.slug)

    def test_hf_requires_model_id(self):
        p = TextDeidentificationPipelineConfig(ner_engine='hf', name='x')
        with self.assertRaises(ValidationError):
            p.full_clean()
        p.hf_model_id = 'org/model'
        p.full_clean()  # ok

    def test_system1_requires_model_when_on(self):
        from extractor.models import ModelTypeChoices
        s1 = ClientConfiguration.objects.create(
            llm_model_name='nimble', model_provider='Local (Ollama)',
            model_api_key='k', model_base_url='http://localhost:11434',
            model_type='system1')
        p = TextDeidentificationPipelineConfig(name='a',
            system_1_model_integration=True)
        with self.assertRaises(ValidationError):
            p.full_clean()
        p.system_1_model = s1
        p.full_clean()  # ok
        p2 = TextDeidentificationPipelineConfig(name='b', system_1_model=s1)
        with self.assertRaises(ValidationError):  # model set but switch off
            p2.full_clean()

    def test_only_one_default(self):
        a = TextDeidentificationPipelineConfig.objects.create(
            name='a', is_default=True)
        b = TextDeidentificationPipelineConfig(name='b', is_default=True)
        with self.assertRaises(ValidationError):
            b.full_clean()

    def test_seed_default_exists(self):
        d = TextDeidentificationPipelineConfig.objects.filter(is_default=True).first()
        self.assertIsNotNone(d)
        self.assertEqual(d.ner_engine, 'spacy')

    def test_defaults_shape(self):
        p = TextDeidentificationPipelineConfig(name='c')
        self.assertIn('drop_entity_types', p.rules)
        self.assertEqual(p.min_confidence, 0.35)
        self.assertIn('PATIENT', p.hf_label_map)
        self.assertEqual(p.extractor_date_shift_range, 90)
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.DeidPipelineModelTests -v 2 --noinput`
Expected: FAIL (`TextDeidentificationPipelineConfig` does not exist).

- [ ] **Step 3: Implement the model**

Add to `extractor/models.py` exactly the Locked-design code: `DeidNerEngineChoices`,
`DEFAULT_DEID_RULES`, `DEFAULT_HF_LABEL_MAP`, `_default_deid_rules`,
`_default_hf_label_map`, `TextDeidentificationPipelineConfig`, and the
`ProcessedText.deid_pipeline` field. Ensure `MinValueValidator`, `MaxValueValidator`
are imported at the top (`from django.core.validators import ...`) and
`ValidationError` is already imported (it is).

- [ ] **Step 4: Make the migrations**

Run: `venv/bin/python manage.py makemigrations extractor --name deid_pipeline_config`
Confirm it creates `TextDeidentificationPipelineConfig`, adds
`ProcessedText.deid_pipeline`, and the `deid_pipeline_unique_identity` constraint.

- [ ] **Step 5: Write the seed data migration**

Create `extractor/migrations/0ZZZ_seed_default_pipeline.py`:

```python
from django.db import migrations

def seed(apps, schema_editor):
    P = apps.get_model('extractor', 'TextDeidentificationPipelineConfig')
    if P.objects.filter(slug='spacy-no-llm-rules').exists():
        return
    P.objects.create(
        name='spaCy · no-LLM · rules', slug='spacy-no-llm-rules',
        ner_engine='spacy', is_default=True)

def unseed(apps, schema_editor):
    P = apps.get_model('extractor', 'TextDeidentificationPipelineConfig')
    P.objects.filter(slug='spacy-no-llm-rules').delete()

class Migration(migrations.Migration):
    dependencies = [migrations_swappable('extractor', 'deid_pipeline_config')]
    operations = [migrations.RunPython(seed, unseed)]
```

Replace `migrations_swappable(...)` with the real dependency tuple:
`('extractor', '0YYY_deid_pipeline_config')` — the migration from Step 4.

- [ ] **Step 6: Run the tests + a migrate**

Run: `venv/bin/python manage.py test extractor.tests.DeidPipelineModelTests -v 2 --noinput`
Expected: PASS (seed test finds the default row). Then:
`venv/bin/python manage.py migrate extractor`
Expected: applies cleanly; `venv/bin/python manage.py shell -c "from extractor.models import TextDeidentificationPipelineConfig as P; print(P.objects.filter(is_default=True).first())"`
prints the spaCy default.

- [ ] **Step 7: Commit**

```bash
git add extractor/models.py extractor/migrations/ extractor/tests.py
git commit -m "feat(deid): add TextDeidentificationPipelineConfig model + ProcessedText.deid_pipeline + seed default"
```

### Task 3: System-1 judge service (`extractor/services/system1_judge.py`)

Relocate the System-1 decision-model call out of the test script into a
production service that reads the endpoint + model name from a
`ClientConfiguration` (model_type='system1'). The threshold and window come from
the pipeline (they are pipeline fields), not the config.

**Files:**
- Create: `extractor/services/system1_judge.py`
- Test: `extractor/tests.py` (new `System1JudgeTests`)

**Interfaces:**
- Produces: `build_context(text, start, end, window) -> str`; `judge_span(config,
  text, start, end, threshold, window) -> float` (the PHI probability); `_so_post(
  url, model, state, questions, api_key=None, timeout=300) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
class System1JudgeTests(TestCase):
    def test_build_context_wraps_span(self):
        from extractor.services.system1_judge import build_context
        self.assertIn('«bar»', build_context('x bar y', 2, 5, window=8))

    def test_judge_span_returns_noul_probability(self):
        from unittest import mock
        from extractor.services import system1_judge as s1j
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration.objects.create(
            llm_model_name='nimble', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system1')
        with mock.patch.object(s1j, '_so_post',
                return_value={'is_phi': {'type': 'noul', 'noul': 0.9}}) as m:
            p = s1j.judge_span(cfg, 'a b c d e', 2, 3, threshold=0.5, window=90)
        self.assertAlmostEqual(p, 0.9)
        m.assert_called_once()

    def test_endpoint_appends_systemone(self):
        from extractor.services.system1_judge import endpoint
        from extractor.models import ClientConfiguration
        cfg = ClientConfiguration(llm_model_name='m', model_provider='x',
            model_api_key='k', model_base_url='http://localhost:11434')
        self.assertEqual(endpoint(cfg), 'http://localhost:11434/v1/systemone')
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.System1JudgeTests -v 2 --noinput`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Write the module**

Create `extractor/services/system1_judge.py`:

```python
"""System-1 decision-model judge for deid precision.

A fast decision model (e.g. Ollama 'nimble' via /v1/systemone) judges one small
span with its surrounding context: 'is this PHI?' Endpoint + model name come
from a ClientConfiguration (model_type='system1'); threshold + window come from
the pipeline. External endpoints are allowed (only short snippets are sent).
"""
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

IS_PHI_QUESTION = (
    'Is the span marked «...» personally identifiable or private medical '
    'information that should be de-identified from this clinical note? Count '
    'it as PHI only if it is a person\'s name, a location/address, an '
    'organisation, a phone or ID number, or a calendar date. Do NOT count it '
    'if it is a diagnosis or disease ("DM", "CCF", "Hypertension"), a '
    'medication or drug ("Tab Amlodipine 5", "Tramadol", "Ceftriaxone"), a '
    'dose, a lab value, a vital sign ("SpO2", "BP", "HR"), a clinical role '
    '("Attendant", "Doctor", "Nurse"), a duration/interval, or an age. If it '
    'is a medical term, answer NO.')


def endpoint(config):
    base = config.model_base_url.rstrip('/')
    if base.endswith('/systemone'):
        return base
    if base.endswith('/v1'):
        return base + '/systemone'
    return base + '/v1/systemone'


def build_context(text, start, end, window=90):
    surf = text[start:end]
    ws, we = max(0, start - window), min(len(text), end + window)
    excerpt = text[ws:we]
    rel = start - ws
    return excerpt[:rel] + '«' + surf + '»' + excerpt[rel + len(surf):]


def _so_post(url, model, state, questions, api_key=None, timeout=300):
    payload = json.dumps({'model': model, 'state': state,
                          'questions': questions}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key and api_key != 'ollama':
        headers['Authorization'] = f'Bearer {api_key}'
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8')).get('answers', {})


def judge_span(config, text, start, end, threshold, window=90):
    """PHI probability (0..1) for one span. Caller compares to threshold."""
    state = {'excerpt': build_context(text, start, end, window)}
    answers = _so_post(endpoint(config), config.llm_model_name, state,
                       {'is_phi': {'type': 'noul', 'instructions': IS_PHI_QUESTION}},
                       api_key=config.model_api_key)
    return float(answers.get('is_phi', {}).get('noul', 0.0))
```

- [ ] **Step 4: Run to verify they pass**

Run: `venv/bin/python manage.py test extractor.tests.System1JudgeTests -v 2 --noinput`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extractor/services/system1_judge.py extractor/tests.py
git commit -m "feat(deid): add system1_judge service (relocated from test harness)"
```

---

### Task 4: Rule defaults in a leaf module + parameterize the filter stages by `rules`

The three filter stages currently read some values from `settings` and others
from inline constants. Refactor them to read from a `rules` dict (the pipeline's
`rules` field), with a `rules=None` fallback that reproduces today's behaviour
exactly — so the existing 22 filter tests keep passing unchanged. Move the
defaults into a leaf module shared by `models.py` and the service (no circular
import).

**Files:**
- Create: `extractor/services/deid_rules.py`
- Modify: `extractor/services/text_deidentification.py` (`_filter_mechanical`,
  `_filter_dates`, `_filter_clinical`, `_filter_results`, add `_rules()`)
- Modify: `extractor/models.py` (source `DEFAULT_DEID_RULES` / `DEFAULT_HF_LABEL_MAP`
  from `deid_rules` instead of inline)
- Test: `extractor/tests.py` (new `DeidRulesParameterTests`)

**Interfaces:**
- Produces: `deid_rules.default_rules() -> dict`, `deid_rules.default_hf_label_map()
  -> dict`; the four filter stages accept a trailing `rules=None` arg.

- [ ] **Step 1: Write the failing tests**

```python
class DeidRulesParameterTests(TestCase):
    def test_default_rules_equal_settings_values(self):
        from extractor.services import deid_rules
        from django.conf import settings
        r = deid_rules.default_rules()
        self.assertEqual(set(r['drop_entity_types']),
                         set(settings.EXTRACTOR_DEID_DROP_ENTITY_TYPES))

    def test_custom_allowlist_respected(self):
        from extractor.models import ProcessedText  # noqa: F401 (import sanity)
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        from extractor.services import deid_rules
        r = deid_rules.default_rules()
        r['clinical_allowlist'].append('mammogram')
        text = 'Mammogram scheduled.'
        res = [type('R', (), {'entity_type': 'DATE_TIME', 'start': 0, 'end': 9,
                              'score': 0.9})()]
        self.assertEqual(len(S._filter_clinical(text, res, rules=r)), 0)

    def test_none_rules_matches_current(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        from extractor.services import deid_rules
        text = 'Age 56 years.'
        res = [type('R', (), {'entity_type': 'DATE_TIME', 'start': 4, 'end': 14,
                              'score': 0.9})()]
        self.assertEqual(len(S._filter_dates(text, res)), 0)
        self.assertEqual(len(S._filter_dates(text, res,
                             rules=deid_rules.default_rules())), 0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.DeidRulesParameterTests -v 2 --noinput`
Expected: FAIL (`deid_rules` module missing; filter signatures don't accept `rules`).

- [ ] **Step 3: Create `extractor/services/deid_rules.py`**

```python
"""Central defaults for the text deid rule bundle (leaf module, no model deps)."""
import copy

DROP_ENTITY_TYPES = ['ID', 'AGE', 'NRP']

CLINICAL_ALLOWLIST = [
    'nottingham', 'grade i', 'grade ii', 'grade iii', 'grade iv',
    'mammogram', 'mammography', 'ce', 'cea', 'fnac', 'fna',
    'hourly', 'spo2', 'jvp',
]

# regexes that mark a DATE_TIME hit as a duration/age/dose -> KEEP, not redact
DATE_KEEP_PATTERNS = [
    r'^\d{1,3}%?$',
    r'^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$',
    r'^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$',
    r'^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$',
    r'^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$',
    r'^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$',
    r'^\d{1,3}\s*/\s*min\b\.?$',
    r'^\d{1,2}:\d{2}$',
    r'^(?!(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b)[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$',
]

# NOTE: no trailing `$` — matches the *prefix* of the surface (shipped behaviour)
CLINICAL_PREFIX_PATTERN = (
    r'^(hb|h\.b\.?|tabs?\b|inj\b|caps?\b|iv\b|po\b|oral\b|spo2?|s\.p\.o|jvp'
    r'|ef\b|bp\b|pr\b|hr\b|wt\b|lmp\b)')

LOCATION_RULES = {'min_length': 4, 'reject_lowercase': True,
                  'pattern': r'^[A-Za-z]?-?\d[\w-]*$'}

HF_LABEL_MAP_DEFAULT = {
    'PATIENT': 'PERSON', 'HCW': 'PERSON',
    'HOSPITAL': 'ORGANIZATION', 'VENDOR': 'ORGANIZATION',
    'ID': 'MEDICAL_RECORD_NUMBER',
    'DATE': 'DATE_TIME',
    'PHONE': 'PHONE_NUMBER',
}


def default_rules():
    return copy.deepcopy({
        'drop_entity_types': DROP_ENTITY_TYPES,
        'clinical_allowlist': CLINICAL_ALLOWLIST,
        'date_keep_patterns': DATE_KEEP_PATTERNS,
        'clinical_prefix_pattern': CLINICAL_PREFIX_PATTERN,
        'location': LOCATION_RULES,
    })


def default_hf_label_map():
    return copy.deepcopy(HF_LABEL_MAP_DEFAULT)
```

- [ ] **Step 4: Point `models.py` at `deid_rules`**

In `extractor/models.py`, replace the inline `DEFAULT_DEID_RULES = {...}`, `def
_default_deid_rules()`, `DEFAULT_HF_LABEL_MAP = {...}`, `def _default_hf_label_map()`
(Tasks 1-2 put these in models.py) with:

```python
from extractor.services import deid_rules
DEFAULT_DEID_RULES = deid_rules.default_rules()
DEFAULT_HF_LABEL_MAP = deid_rules.default_hf_label_map()
_default_deid_rules = deid_rules.default_rules
_default_hf_label_map = deid_rules.default_hf_label_map
```

- [ ] **Step 5: Parameterize the four filter stages**

In `extractor/services/text_deidentification.py`, add a helper and add a trailing
`rules=None` to each stage (keep the fraction-context check inline in
`_filter_dates`; it is a context rule, not a surface pattern):

```python
    @staticmethod
    def _rules(rules):
        from extractor.services import deid_rules
        return rules if rules else deid_rules.default_rules()

    @staticmethod
    def _filter_mechanical(text, results, rules=None):
        rules = TextDeidentificationService._rules(rules)
        drop_types = set(rules['drop_entity_types'])
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if r.entity_type in drop_types:
                continue
            if not surface:
                continue
            raw = text[r.start:r.end]
            b_start = r.start + (len(raw) - len(raw.lstrip()))
            b_end = r.end - (len(raw) - len(raw.rstrip()))
            if (b_start > 0 and text[b_start - 1].isalnum()) or \
                    (b_end < len(text) and text[b_end].isalnum()):
                continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_dates(text, results, rules=None):
        rules = TextDeidentificationService._rules(rules)
        patterns = [re.compile(p, re.I) for p in rules['date_keep_patterns']]
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if (r.entity_type == 'DATE_TIME'
                    and any(p.match(surface) for p in patterns)):
                continue
            if (r.entity_type == 'DATE_TIME'
                    and re.match(r'^\d{1,2}/\d{1,2}$', surface)
                    and re.search(r'fraction\s*$',
                                  text[max(0, r.start - 12):r.start], re.I)):
                continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_clinical(text, results, rules=None):
        rules = TextDeidentificationService._rules(rules)
        allowlist = {t.lower() for t in rules['clinical_allowlist']}
        prefix = re.compile(rules['clinical_prefix_pattern'], re.I)
        loc = rules['location']
        loc_pattern = re.compile(loc['pattern'])
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if surface.lower() in allowlist:
                continue
            if r.entity_type in ('PERSON', 'ORGANIZATION') and prefix.match(surface):
                continue
            if r.entity_type == 'LOCATION':
                if (len(surface) < loc['min_length']
                        or (loc.get('reject_lowercase') and surface.islower())
                        or loc_pattern.match(surface)):
                    continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_results(text, results, rules=None):
        results = TextDeidentificationService._filter_mechanical(text, results, rules)
        results = TextDeidentificationService._filter_dates(text, results, rules)
        results = TextDeidentificationService._filter_clinical(text, results, rules)
        return results
```

- [ ] **Step 6: Run the new tests + the full existing filter suite**

Run: `venv/bin/python manage.py test extractor.tests.DeidRulesParameterTests -v 2 --noinput`
Then: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: new tests pass AND the pre-existing `DurationFilterTests` /
`FilterDecompositionTests` (22) still pass (the `rules=None` path is behaviour-
identical). Only the 2 known pre-existing failures remain.

- [ ] **Step 7: Commit**

```bash
git add extractor/services/deid_rules.py extractor/services/text_deidentification.py extractor/models.py extractor/tests.py
git commit -m "refactor(deid): source rule defaults from deid_rules; filters accept rules dict"
```

---

### Task 5: Build the analyzer + run deid from a pipeline

Refactor the analyzer builder and `deidentify()` to consume a
`TextDeidentificationPipelineConfig`. This is the core of the feature.

**Files:**
- Modify: `extractor/services/text_deidentification.py`
- Test: `extractor/tests.py` (new `PipelineDeidTests`)

**Interfaces:**
- Produces:
  - `_build_analyzer_for(pipeline) -> AnalyzerEngine` (cached by
    `(ner_engine, hf_model_id, hf_threshold)`; `hf` engine uses SlimSpacy +
    `HuggingFaceNerRecognizer` with `hf_token` applied; `spacy` engine uses the
    default spaCy NER).
  - `_apply_precision(text, results, pipeline) -> list` (mechanical + dates +
    [system1 judge OR clinical]).
  - `_filter_system1(text, results, pipeline) -> list`.
  - `_deidentify_text_for(content, shift, patient, pipeline) -> (str, dict, list)`.
  - `_resolve_pipeline(pipeline, backend, client_config_id) -> (pipeline, openmed)`
    where `openmed` is `'openmed'` or `None` (legacy OpenMed path).
  - `deidentify(processed_text, user=None, pipeline=None, backend='default',
    client_config_id=None)` (new `pipeline` param; legacy `backend` still works).

- [ ] **Step 1: Write the failing tests**

```python
class PipelineDeidTests(TestCase):
    def _spacy_pipeline(self):
        from extractor.models import TextDeidentificationPipelineConfig as P
        return P(ner_engine='spacy', rules=deid_rules.default_rules(),
                 min_confidence=0.35)

    def test_resolve_default_pipeline(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        p, openmed = S._resolve_pipeline(None, 'default', None)
        self.assertEqual(openmed, None)
        self.assertTrue(p.is_default)

    def test_resolve_presidio_legacy_is_hf(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        p, _ = S._resolve_pipeline(None, 'presidio', None)
        self.assertEqual(p.ner_engine, 'hf')

    def test_resolve_llm_legacy_is_spacy_plus_s2(self):
        from extractor.models import ClientConfiguration
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        cfg = ClientConfiguration.objects.create(
            llm_model_name='g', model_provider='Local (Ollama)',
            model_api_key='k', model_base_url='http://localhost:11434',
            model_type='system2', deid_local_certified=True)
        p, _ = S._resolve_pipeline(None, 'llm', str(cfg.id))
        self.assertEqual(p.ner_engine, 'spacy')
        self.assertEqual(p.system2_model_id, cfg.id)

    def test_precision_system1_judges_non_dates_only(self):
        from unittest import mock
        from extractor.models import TextDeidentificationPipelineConfig as P, \
            ClientConfiguration
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        s1 = ClientConfiguration.objects.create(
            llm_model_name='nimble', model_provider='Local (Ollama)',
            model_api_key='ollama', model_base_url='http://localhost:11434',
            model_type='system1')
        pipe = P(system_1_model_integration=True, system_1_model=s1,
                 system_1_threshold=0.5, system_1_window=90,
                 rules=deid_rules.default_rules(), min_confidence=0.35)
        R = lambda t, a, b: type('R', (), {'entity_type': t, 'start': a, 'end': b, 'score': 0.9})()
        res = [R('PERSON', 0, 4), R('DATE_TIME', 10, 15)]
        text = 'John x y Admit date 01/02/2024 here'
        with mock.patch('extractor.services.system1_judge.judge_span',
                        return_value=0.1) as m:   # 0.1 < 0.5 -> keep PERSON dropped
            kept = S._apply_precision(text, res, pipe)
        m.assert_called_once()                 # only the PERSON was judged
        self.assertTrue(any(r.entity_type == 'DATE_TIME' for r in kept))

    def test_deidentify_text_for_spacy(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        new_content, entities, repl = S._deidentify_text_for(
            'Patient John Smith from Kolkata, admitted 01/02/2024.',
            15, None, self._spacy_pipeline())
        self.assertTrue(repl)                 # something was redacted
        self.assertIn('DATE_TIME', entities)
        self.assertNotIn('01/02/2024', new_content)  # date shifted
```

(Add `from extractor.services import deid_rules` at the top of the test module.
`deid_rules.default_rules()` is used to build pipelines in the tests.)

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.PipelineDeidTests -v 2 --noinput`
Expected: FAIL (`_build_analyzer_for`, `_apply_precision`, `_resolve_pipeline` undefined).

- [ ] **Step 3: Add the builder + precision + per-pipeline deid methods**

Add to `TextDeidentificationService`:

```python
    _analyzer_cache = {}

    @classmethod
    def _build_analyzer_for(cls, pipeline):
        import os
        key = (pipeline.ner_engine,
               pipeline.hf_model_id if pipeline.ner_engine == 'hf' else None,
               pipeline.hf_threshold)
        if key in cls._analyzer_cache:
            return cls._analyzer_cache[key]
        nlp_engine = None
        if pipeline.ner_engine == 'hf':
            from presidio_analyzer.nlp_engine import SlimSpacyNlpEngine
            nlp_engine = SlimSpacyNlpEngine(supported_languages=['en'])
        analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine, supported_languages=['en'],
            context_aware_enhancer=LemmaContextAwareEnhancer(
                context_similarity_factor=0.35,
                min_score_with_context_similarity=0.4))
        if pipeline.ner_engine == 'hf':
            if pipeline.hf_token:
                os.environ['HF_TOKEN'] = pipeline.hf_token
            from presidio_analyzer.predefined_recognizers.ner import (
                HuggingFaceNerRecognizer)
            try:
                recognizer = HuggingFaceNerRecognizer(
                    model_name=pipeline.hf_model_id,
                    label_mapping=pipeline.hf_label_map,
                    threshold=pipeline.hf_threshold,
                    aggregation_strategy='simple', device='cpu',
                    supported_language='en')
                analyzer.registry.add_recognizer(recognizer)
            except Exception as e:
                logger.warning(f"HF NER {pipeline.hf_model_id} failed to load: {e}")
        if getattr(settings, 'DEID_LENIENT_INDIAN_IDS', True):
            from deidentification.utils.indian_id_recognizers import (
                build_indian_id_recognizers)
            for recognizer in build_indian_id_recognizers():
                analyzer.registry.add_recognizer(recognizer)
        for recognizer in build_text_recognizers():
            analyzer.registry.add_recognizer(recognizer)
        cls._analyzer_cache[key] = analyzer
        return analyzer

    @classmethod
    def _apply_precision(cls, text, results, pipeline):
        rules = pipeline.rules
        results = cls._filter_mechanical(text, results, rules)
        results = cls._filter_dates(text, results, rules)
        if pipeline.system_1_model_integration:
            results = cls._filter_system1(text, results, pipeline)
        else:
            results = cls._filter_clinical(text, results, rules)
        return results

    @classmethod
    def _filter_system1(cls, text, results, pipeline):
        from extractor.services import system1_judge
        kept = []
        for r in results:
            if r.entity_type in ('DATE_TIME', 'DATE'):
                kept.append(r)          # real dates are shifted, never judged
                continue
            p = system1_judge.judge_span(
                pipeline.system_1_model, text, r.start, r.end,
                threshold=pipeline.system_1_threshold,
                window=pipeline.system_1_window)
            if p >= pipeline.system_1_threshold:
                kept.append(r)
        return kept

    @classmethod
    def _deidentify_text_for(cls, content, shift, patient, pipeline):
        analyzer = cls._build_analyzer_for(pipeline)
        ad_hoc = build_patient_recognizers(patient)
        if pipeline.system2_model_id:
            ad_hoc = [LlmNerRecognizer(pipeline.system2_model)] + ad_hoc
        results = analyzer.analyze(
            text=content, language='en',
            score_threshold=pipeline.min_confidence,
            ad_hoc_recognizers=ad_hoc)
        results = cls._apply_precision(content, results, pipeline)
        results = cls._resolve_overlaps(results)
        repl = []
        new_content = cls._apply_replacements(content, results, shift, {}, repl)
        return new_content, cls._entity_counts(results), repl
```

- [ ] **Step 4: Rewrite `deidentify()` to resolve a pipeline and branch**

Replace the body of `deidentify()` (from `backend_name, llm_config = ...` to the
`return ProcessedText.objects.create(...)`) so that:

```python
        pipeline, openmed = cls._resolve_pipeline(pipeline, backend, client_config_id)
        content = FileProcessorService.get_processed_content(processed_text)
        if not content:
            raise ValueError("Cannot read source processed text content")
        date_range = (pipeline.extractor_date_shift_range
                      if (pipeline is not None
                          and pipeline.extractor_date_shift_range is not None)
                      else getattr(settings, 'EXTRACTOR_DEID_DATE_SHIFT_RANGE', 90))
        shift = random.randint(-date_range, date_range)
        patient = processed_text.file_upload.patient_id
        path = str(processed_text.processed_file_path or '')

        if openmed:
            # legacy OpenMed path (unchanged behaviour)
            from extractor.services.openmed_ner import OpenMedNerRecognizer
            ner_recognizer = OpenMedNerRecognizer()
            engine_mode, deid_model = 'openmed', getattr(
                settings, 'EXTRACTOR_DEID_OPENMED_MODEL', 'pii_superclinical_large')
            s2_cfg = None
            if path.endswith('.csv'):
                new_content, entities, columns, repl = cls._deidentify_csv(
                    content, shift, patient, ner_recognizer)
            else:
                new_content, entities, repl = cls._deidentify_text(
                    content, shift, patient, ner_recognizer)
                columns = []
            deid_pipeline_row = None
        else:
            if path.endswith('.csv'):
                new_content, entities, columns, repl = cls._deidentify_csv_for(
                    content, shift, patient, pipeline)
            else:
                new_content, entities, repl = cls._deidentify_text_for(
                    content, shift, patient, pipeline)
                columns = []
            engine_mode = pipeline.ner_engine
            deid_model = (pipeline.hf_model_id if pipeline.ner_engine == 'hf'
                          else (pipeline.system2_model.llm_model_name
                                if pipeline.system2_model_id else ''))
            s2_cfg = pipeline.system2_model if pipeline.system2_model_id else None
            deid_pipeline_row = pipeline if pipeline.pk else None

        # (aggregate deid_map exactly as before - unchanged block)
        deid_map = {}
        for e in repl:
            key = (e['tag'], e['original'])
            if key in deid_map:
                deid_map[key]['count'] += 1
            else:
                deid_map[key] = {
                    'tag': e['tag'], 'type': e['type'],
                    'original': e['original'], 'count': 1}

        file_upload = processed_text.file_upload
        version = FileProcessorService._next_version(file_upload)
        new_path = cls._output_path(file_upload, version, path or '.txt')
        cls._write_output(new_path, new_content)
        return ProcessedText.objects.create(
            file_upload=file_upload, processed_file_path=new_path,
            source_sheet=processed_text.source_sheet, content_length=len(new_content),
            version=version, processed_by_user=user, deidentified=True,
            deidentified_source=processed_text, deid_engine=engine_mode,
            deid_model=deid_model, deid_entities=entities,
            deid_csv_columns_flagged=columns, deid_map=list(deid_map.values()),
            deid_date_shift_days=shift, deid_client_config=s2_cfg,
            deid_pipeline=deid_pipeline_row)
```

(The `deid_map` aggregation block above is the existing code, unchanged. Add
`_deidentify_csv_for(content, shift, patient, pipeline)`
that mirrors `_deidentify_csv` but calls `_build_analyzer_for(pipeline)`,
`_apply_precision(cell, results, pipeline)`, and the pipeline `min_confidence`.
Keep the old `_deidentify_csv` / `_deidentify_text` / `OpenMedNerRecognizer` path
intact for the `openmed` branch.)

Add the resolvers:

```python
    @classmethod
    def _resolve_pipeline(cls, pipeline, backend, client_config_id):
        from extractor.models import ClientConfiguration, \
            TextDeidentificationPipelineConfig as P
        if pipeline is not None:
            return pipeline, None
        backend = (backend or 'default')
        if backend == 'openmed':
            return None, 'openmed'
        if backend in ('', 'default'):
            default = P.objects.filter(is_default=True).first()
            if default is None:
                raise LlmDeidConfigurationError(
                    'No default deidentification pipeline is configured.')
            return default, None
        if backend == 'presidio':
            from django.conf import settings as s
            return P(ner_engine='hf', hf_model_id=s.DEID_HF_NER_MODEL,
                     hf_label_map=s.DEID_HF_LABEL_MAP,
                     hf_threshold=s.DEID_HF_NER_THRESHOLD,
                     min_confidence=s.EXTRACTOR_DEID_SCORE_THRESHOLD), None
        if backend == 'llm':
            cfg = ClientConfiguration.objects.filter(id=client_config_id).first()
            if cfg is None:
                raise LlmDeidConfigurationError(
                    'No configuration for the llm backend.')
            return P(ner_engine='spacy', system2_model=cfg,
                     min_confidence=s.EXTRACTOR_DEID_SCORE_THRESHOLD), None
        raise LlmDeidConfigurationError(f"Unknown deid backend {backend!r}.")
```

(Import `settings` at the top of the method scope where used, or reuse the
module-level `settings` already imported in `text_deidentification.py`.)

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python manage.py test extractor.tests.PipelineDeidTests -v 2 --noinput`
Then: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: PipelineDeidTests pass; existing deid e2e tests pass (they use the
legacy `backend` path, now routed through `_resolve_pipeline`). Only the 2 known
pre-existing failures remain.

- [ ] **Step 6: Commit**

```bash
git add extractor/services/text_deidentification.py extractor/tests.py
git commit -m "feat(deid): build analyzer + run deid from a pipeline config (NER/LLM/system1/rules)"
```

### Task 6: Dispatch wiring — task / command / views carry `pipeline_id`

Thread a `pipeline_id` through the Celery task, the backfill command, and the
dispatch view. The view resolves `pipeline_id` -> config and passes the object to
the service (the service takes objects; the task takes an id). Legacy `backend`
still works unchanged.

**Files:**
- Modify: `extractor/tasks.py` (`deidentify_processed_text_task`)
- Modify: `extractor/management/commands/deidentify_processed.py`
- Modify: `extractor/views.py` (`processed_text_deidentify`, `_dispatch_deid_tasks`)
- Test: `extractor/tests.py` (new `DeidDispatchTests`)

**Interfaces:**
- Consumes: `TextDeidentificationPipelineConfig`, `TextDeidentificationService.deidentify(pipeline=...)`.
- Produces: `deidentify_processed_text_task(..., pipeline_id=None)`; view accepts
  `pipeline_id` from POST.

- [ ] **Step 1: Write the failing tests**

```python
class DeidDispatchTests(TestCase):
    def test_task_resolves_pipeline_id(self):
        from unittest import mock
        from extractor.models import TextDeidentificationPipelineConfig as P, \
            ProcessedText
        from extractor.tasks import deidentify_processed_text_task
        pipe = P.objects.create(name='x', is_default=True)
        pt = ProcessedText.objects.create(file_upload=make_upload(), version=1)
        with mock.patch.object(
                TextDeidentificationService, 'deidentify') as m:
            deidentify_processed_text_task(
                task_id='t', processed_text_id=pt.id, pipeline_id=pipe.id)
        _, kwargs = m.call_args
        self.assertEqual(kwargs['pipeline'].id, pipe.id)

    def test_task_defaults_to_no_pipeline(self):
        from unittest import mock
        from extractor.models import ProcessedText
        from extractor.tasks import deidentify_processed_text_task
        pt = ProcessedText.objects.create(file_upload=make_upload(), version=1)
        with mock.patch.object(TextDeidentificationService, 'deidentify') as m:
            deidentify_processed_text_task(task_id='t', processed_text_id=pt.id)
        self.assertIsNone(m.call_args.kwargs.get('pipeline'))
```

(Add a small `make_upload()` helper to the test module if one does not already
exist: it creates a minimal `FileUpload` + patient. Mirror the existing deid test
fixtures in `extractor/tests.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.DeidDispatchTests -v 2 --noinput`
Expected: FAIL (task has no `pipeline_id` param).

- [ ] **Step 3: Add `pipeline_id` to the task**

In `extractor/tasks.py`, `deidentify_processed_text_task(self, task_id,
processed_text_id, user_id=None, backend='default', client_config_id=None,
pipeline_id=None)`: before calling the service, resolve the id and pass the object:

```python
        from extractor.models import TextDeidentificationPipelineConfig
        pipeline = (TextDeidentificationPipelineConfig.objects.filter(
            id=pipeline_id).first() if pipeline_id else None)
        new_version = TextDeidentificationService.deidentify(
            pt, user=user, pipeline=pipeline, backend=backend,
            client_config_id=client_config_id)
```

- [ ] **Step 4: Add `--pipeline` to the backfill command**

In `extractor/management/commands/deidentify_processed.py`, add
`parser.add_argument('--pipeline', type=int, default=None, help='pipeline id')`
and pass `pipeline_id=options['pipeline']` to `deidentify(...)` (keep `--backend`
for legacy runs).

- [ ] **Step 5: Accept `pipeline_id` in the dispatch view**

In `extractor/views.py` `processed_text_deidentify`, after the existing `backend`
handling, read the pipeline id:

```python
    pipeline_id = request.POST.get('pipeline_id') or None
    if pipeline_id and not str(pipeline_id).isdigit():
        messages.error(request, "Invalid pipeline choice.")
        return redirect(next_url)
```
and pass it to the task:

```python
    deidentify_processed_text_task.delay(
        task.task_id, processed_text_id, user_id=request.user.id,
        backend=backend, client_config_id=client_config_id,
        pipeline_id=int(pipeline_id) if pipeline_id else None)
```

`_dispatch_deid_tasks` (auto) needs no change — it passes no backend/pipeline, so
it resolves to the default pipeline via `_resolve_pipeline`.

- [ ] **Step 6: Run the tests + suite**

Run: `venv/bin/python manage.py test extractor.tests.DeidDispatchTests -v 2 --noinput`
Then: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: pass; suite green (2 known pre-existing failures aside).

- [ ] **Step 7: Commit**

```bash
git add extractor/tasks.py extractor/management/commands/deidentify_processed.py extractor/views.py extractor/tests.py
git commit -m "feat(deid): thread pipeline_id through task, backfill command, and dispatch view"
```

---

### Task 7: `ClientConfiguration` UI — `model_type` in, obsolete flags out

**Files:**
- Modify: `extractor/views.py` (`client_configuration_create`, `client_configuration_edit`,
  `client_configuration_detail`)
- Modify: `templates/extractor/client_configuration_create.html`, `_edit.html`,
  `_detail.html`
- Test: `extractor/tests.py` (extend an existing client-config view test, or add
  `ClientConfigModelTypeUITests`)

**Interfaces:**
- Consumes: `ClientConfiguration.model_type`; the two removed booleans.

- [ ] **Step 1: Write the failing test**

```python
class ClientConfigModelTypeUITests(TestCase):
    def test_create_stores_model_type_and_drops_obsolete(self):
        from django.test import Client
        from extractor.models import ClientConfiguration
        c = Client()
        c.login(username=self.user.username, password='pw')  # reuse your test user fixture
        c.get('/extractor/client-configurations/create/')
        resp = c.post('/extractor/client-configurations/create/', {
            'llm_model_name': 'nimble', 'model_provider': 'Local (Ollama)',
            'model_api_key': 'k', 'model_base_url': 'http://localhost:11434',
            'request_timeout': '60', 'context_size': '8192',
            'model_type': 'system1',
        })
        cfg = ClientConfiguration.objects.get(llm_model_name='nimble')
        self.assertEqual(cfg.model_type, 'system1')
        self.assertFalse(hasattr(cfg, 'is_default_deid'))
```

(Adjust the URL + user fixture to match the existing client-config view tests in
`extractor/tests.py`.)

- [ ] **Step 2: Run to verify it fails** (create view doesn't accept `model_type`).

- [ ] **Step 3: Update the create/edit views**

In `client_configuration_create` and `client_configuration_edit`, add
`model_type=request.POST.get('model_type', 'system2')` to the
`ClientConfiguration(...)` / assignment, and delete the lines that set
`enable_text_deid` and `is_default_deid`.

- [ ] **Step 4: Update the three templates**

In each of `client_configuration_create.html` / `_edit.html` / `_detail.html`:
- Replace the deid block's two removed checkboxes with a `model_type` select:

```html
{% component "form_field" label="Model type" field_id="model_type" required=True %}
    <select name="model_type" id="model_type" class="...">
        <option value="system2" {% if form_model_type == "system2" %}selected{% endif %}>System 2 - traditional autoregressive LLM</option>
        <option value="system1" {% if form_model_type == "system1" %}selected{% endif %}>System 1 - decision model</option>
    </select>
{% endcomponent %}
```

- Remove the `enable_text_deid` and `is_default_deid` checkbox blocks.
- Keep the `deid_local_certified` checkbox; change its label to: "I certify this
  model runs locally (same machine or local network) so patient text does not
  leave the local network" (it now doubles as the de-identification clearance).
- Update the section intro text to drop the "default engine" wording (the default
  is now chosen on the pipeline, not the config).

(`form_model_type` is the instance value for create/edit/detail — pass it in the
view context, or use `configuration.model_type` on detail.)

- [ ] **Step 5: Run the test + suite**

Run: `venv/bin/python manage.py test extractor.tests.ClientConfigModelTypeUITests -v 2 --noinput`
Then full suite. Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add extractor/views.py templates/extractor/client_configuration_*.html extractor/tests.py
git commit -m "feat(deid): model_type on client config UI; drop enable_text_deid + is_default_deid"
```

---

### Task 8: Pipeline CRUD UI + per-file pipeline selector

**Files:**
- Modify: `extractor/forms.py` (new `TextDeidentificationPipelineConfigForm`)
- Modify: `extractor/views.py` (`pipeline_list`, `pipeline_create`, `pipeline_detail`,
  `pipeline_edit`, `pipeline_delete`; `file_upload_detail` / `processed_text_deid_review`
  gain the pipeline list)
- Modify: `extractor/urls.py` (pipeline routes)
- Create: `templates/extractor/pipeline_list.html`, `pipeline_create.html`,
  `pipeline_detail.html`, `pipeline_edit.html` (mirror `client_configuration_*.html`
  scaffolding)
- Modify: `templates/extractor/file_upload_detail.html` +
  `processed_text_deid_review.html` (pipeline selector)
- Test: `extractor/tests.py` (new `PipelineCrudTests`)

**Interfaces:**
- Produces: `TextDeidentificationPipelineConfigForm` (filtered pickers, JSON rules
  editor, auto-name); views `pipeline_*`; the per-file selector posts
  `pipeline_id`.

- [ ] **Step 1: Write the failing tests**

```python
class PipelineCrudTests(TestCase):
    def test_form_filters_pickers_by_model_type(self):
        from extractor.models import ClientConfiguration
        from extractor.forms import TextDeidentificationPipelineConfigForm as F
        s2 = ClientConfiguration.objects.create(llm_model_name='g',
            model_provider='Local (Ollama)', model_api_key='k',
            model_base_url='http://localhost:11434', model_type='system2',
            deid_local_certified=True)
        s1 = ClientConfiguration.objects.create(llm_model_name='n',
            model_provider='Local (Ollama)', model_api_key='k',
            model_base_url='http://localhost:11434', model_type='system1')
        f = F()
        self.assertEqual(f.fields['system2_model'].queryset.count(), 1)
        self.assertNotIn(s1, f.fields['system2_model'].queryset)
        self.assertEqual(f.fields['system_1_model'].queryset.count(), 1)
        self.assertNotIn(s2, f.fields['system_1_model'].queryset)

    def test_create_view_autonames_and_persists_rules(self):
        import json
        from django.test import Client
        from extractor.models import TextDeidentificationPipelineConfig as P
        c = Client(); c.login(username=self.user.username, password='pw')
        c.post('/extractor/deid-pipelines/create/', {
            'ner_engine': 'spacy', 'min_confidence': '0.35',
            'rules': json.dumps({'drop_entity_types': ['ID']}),
            'hf_label_map': json.dumps({'PATIENT': 'PERSON'}),
        })
        p = P.objects.latest('id')
        self.assertTrue(p.name)                      # auto-named
        self.assertEqual(p.rules['drop_entity_types'], ['ID'])
```

- [ ] **Step 2: Run to verify they fail** (form/views do not exist).

- [ ] **Step 3: Write the form**

In `extractor/forms.py`:

```python
import json as _json


class TextDeidentificationPipelineConfigForm(forms.Form):
    name = forms.CharField(required=False, label='Name')
    ner_engine = forms.ChoiceField(choices=DeidNerEngineChoices.choices)
    hf_model_id = forms.CharField(required=False, label='HuggingFace model id')
    hf_token = forms.CharField(required=False, widget=forms.PasswordInput(
        attrs={'autocomplete': 'new-password'}), label='HuggingFace token')
    hf_label_map = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 8}))
    hf_threshold = forms.FloatField(initial=0.20, required=False)
    system2_model = forms.ModelChoiceField(queryset=ClientConfiguration.objects.none(),
        required=False, empty_label='(none - main detector only)')
    system_1_model_integration = forms.BooleanField(required=False)
    system_1_model = forms.ModelChoiceField(queryset=ClientConfiguration.objects.none(),
        required=False, empty_label='(select a System-1 model)')
    system_1_threshold = forms.FloatField(initial=0.5, required=False)
    system_1_window = forms.IntegerField(initial=90, required=False)
    rules = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 12}))
    min_confidence = forms.FloatField(initial=0.35, required=False)
    extractor_date_shift_range = forms.IntegerField(initial=90, required=False,
        help_text='Leave blank to use the default range.')
    is_default = forms.BooleanField(required=False)

    def __init__(self, *args, pipeline=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['system2_model'].queryset = ClientConfiguration.objects.filter(
            model_type='system2', deid_local_certified=True)
        self.fields['system_1_model'].queryset = ClientConfiguration.objects.filter(
            model_type='system1')
        src = pipeline or {}
        if pipeline:
            self.fields['rules'].initial = _json.dumps(pipeline.rules, indent=2)
            self.fields['hf_label_map'].initial = _json.dumps(pipeline.hf_label_map, indent=2)

    def clean(self):
        cleaned = super().clean()
        for fname in ('rules', 'hf_label_map'):
            val = cleaned.get(fname)
            if val and isinstance(val, str):
                try:
                    _json.loads(val)
                except _json.JSONDecodeError:
                    self.add_error(fname, 'Must be valid JSON.')
        return cleaned

    def build_object(self):
        """Return a (possibly unsaved) TextDeidentificationPipelineConfig."""
        c = self.cleaned_data
        from extractor.models import TextDeidentificationPipelineConfig as P
        obj = P(
            name=c.get('name') or '',
            ner_engine=c['ner_engine'],
            hf_model_id=c.get('hf_model_id') or '',
            hf_token=c.get('hf_token') or '',
            hf_threshold=c.get('hf_threshold') or 0.20,
            system2_model=c.get('system2_model'),
            system_1_model_integration=c.get('system_1_model_integration', False),
            system_1_model=c.get('system_1_model'),
            system_1_threshold=c.get('system_1_threshold') or 0.5,
            system_1_window=c.get('system_1_window') or 90,
            min_confidence=c.get('min_confidence') or 0.35,
            extractor_date_shift_range=c.get('extractor_date_shift_range'),
            is_default=c.get('is_default', False))
        if c.get('rules'):
            obj.rules = _json.loads(c['rules'])
        if c.get('hf_label_map'):
            obj.hf_label_map = _json.loads(c['hf_label_map'])
        return obj
```

- [ ] **Step 4: Add the CRUD views**

Mirror `client_configuration_list/create/detail/edit/delete` in `extractor/views.py`.
Create/edit pattern:

```python
@login_required
@permission_required('extractor.add_textdeidentificationpipelineconfig',
                     raise_exception=True)
def pipeline_create(request):
    from extractor.forms import TextDeidentificationPipelineConfigForm as F
    if request.method == 'POST':
        form = F(request.POST)
        if form.is_valid():
            obj = form.build_object()
            try:
                obj.full_clean()   # runs model.clean() cross-field validation
            except ValidationError as e:
                for k, v in e.message_dict.items():
                    form.add_error(k, ', '.join(v) if isinstance(v, list) else v)
            else:
                obj.save()         # auto-names + slugs
                return redirect('extractor:pipeline_detail', pipeline_id=obj.id)
    else:
        form = F()
    return render(request, 'extractor/pipeline_create.html', {'form': form})
```

(`pipeline_edit` loads the row, passes `pipeline=obj` to the form for initial
values, and saves back to it; `pipeline_list`/`pipeline_detail`/`pipeline_delete`
mirror the client-config equivalents. `permission_required` uses the model's
auto perms; if the model is not in `auth` perms yet, Django auto-creates them on
migration — Task 2's migration already registered the model.)

- [ ] **Step 5: Add the URL routes**

In `extractor/urls.py`:

```python
    path('deid-pipelines/', views.pipeline_list, name='pipeline_list'),
    path('deid-pipelines/create/', views.pipeline_create, name='pipeline_create'),
    path('deid-pipelines/<int:pipeline_id>/', views.pipeline_detail, name='pipeline_detail'),
    path('deid-pipelines/<int:pipeline_id>/edit/', views.pipeline_edit, name='pipeline_edit'),
    path('deid-pipelines/<int:pipeline_id>/delete/', views.pipeline_delete, name='pipeline_delete'),
```

- [ ] **Step 6: Create the four templates**

Mirror `client_configuration_*.html` for the card/form scaffolding. The create/edit
form body renders the standard fields; give `rules` and `hf_label_map` a
`<textarea>` bound to `form.rules` / `form.hf_label_map` (JSON). Example core block:

```html
{% component "form_field" label="Rules & regex (JSON)" field_id="rules"
        help_text="Edit the rules and regex patterns. Keep it valid JSON." %}
    <textarea name="rules" id="rules" rows="12">{{ form.rules.value|default:default_rules_json }}</textarea>
{% endcomponent %}
```

(`default_rules_json` is passed in the create-view context:
`json.dumps(deid_rules.default_rules(), indent=2)`. The remaining scalar fields
— ner_engine, hf_model_id, hf_token, hf_threshold, the two model pickers,
system_1_* and `extractor_date_shift_range` (a number input, label "Date shift
range (days)"), min_confidence, is_default — render as standard form inputs.
`pipeline_detail.html` shows the resolved stages: NER engine, System-2 model,
System-1 (on/off + model), date-shift range, min-confidence, and the rules JSON
in a `<pre>`.)

- [ ] **Step 7: Add the per-file pipeline selector**

In `file_upload_detail` (and `processed_text_deid_review`), expose the pipelines:

```python
    from extractor.models import TextDeidentificationPipelineConfig
    context['deid_pipelines'] = list(
        TextDeidentificationPipelineConfig.objects.all())
```

In `file_upload_detail.html`, in the deidentify action form, add a select that posts
`pipeline_id` (primary choice), before the existing engine/backend select (keep the
backend select as an "advanced" option so legacy engines still work):

```html
<select name="pipeline_id">
    <option value="">Default pipeline</option>
    {% for p in deid_pipelines %}
      <option value="{{ p.id }}">{{ p.name }}{% if p.is_default %} (default){% endif %}</option>
    {% endfor %}
</select>
```

- [ ] **Step 8: Run the tests + suite**

Run: `venv/bin/python manage.py test extractor.tests.PipelineCrudTests -v 2 --noinput`
Then: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: pass; full suite green (2 known pre-existing failures aside).

- [ ] **Step 9: Commit**

```bash
git add extractor/forms.py extractor/views.py extractor/urls.py templates/extractor/pipeline_*.html templates/extractor/file_upload_detail.html templates/extractor/processed_text_deid_review.html extractor/tests.py
git commit -m "feat(deid): pipeline CRUD UI + per-file pipeline selector"
```

---

## Verification / Done

- [ ] Full suite: `venv/bin/python manage.py test extractor -v 1 --noinput` — green
  (only the 2 known pre-existing failures).
- [ ] Migrations apply on a fresh DB: `venv/bin/python manage.py migrate`.
- [ ] Manual end-to-end:
  1. `/extractor/deid-pipelines/create/` -> create `spaCy + gemma4:e2b (system-2) +
     rules`; confirm auto-name + slug, and that only System-2 configs appear in the
     system-2 picker and only System-1 configs in the system-1 picker.
  2. On a file detail page, pick that pipeline and run deidentification; confirm a
     deidentified version is produced, `ProcessedText.deid_pipeline` is set, dates
     are shifted, and ages/durations are kept.
  3. Create a System-1 pipeline (`second-check` on) pointing at a local `nimble`
     config; run a note; confirm the judge is invoked for non-date spans only.
  4. Confirm the shipped default (`spaCy · no-LLM · rules`) is used when no pipeline
     is chosen.
- [ ] Legacy engines still work: backfill with `--backend openmed` and a file
  override `llm:<id>` produce output as before.
- [ ] Nothing removed: the Dicom pixel-scrub path (`DEID_HF_*` settings) is
  untouched.

## Open items / assumptions

- **OpenMed** is preserved as a legacy `backend='openmed'` path, not a
  `ner_engine` choice (it uses its own library, not `HuggingFaceNerRecognizer`).
  If you want it as a first-class pipeline engine, that is a follow-up.
- **HF `hf_token`** is applied via the `HF_TOKEN` env var at load time (process-
  global). Fine for a single local tool; revisit if multiple pipelines with
  different tokens run in one process.
- The `rules` editor is a JSON textarea (view + edit). A structured rule editor
  (add-a-pattern form) is a possible follow-up.
- `EXTRACTOR_DEID_SCORE_THRESHOLD`, `EXTRACTOR_DEID_DROP_ENTITY_TYPES`,
  `EXTRACTOR_DEID_CLINICAL_ALLOWLIST`, `EXTRACTOR_DEID_NER_BACKEND` are no longer
  read by the text pipeline (now per-pipeline). They can be deleted from
  `settings.py` in a cleanup pass (left in place here to avoid touching unrelated
  code).