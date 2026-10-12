# Per-Table Question-Style Prompt Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the stage-2 per-table extraction prompt as a document-first, question-style prompt driven by client_app model docstrings, with up to 2 focused null-field re-ask passes per table, and remove the obsolete field-chunking machinery.

**Architecture:** Each table is extracted in ONE call: the full document comes first, then the table's docstring (table context), the already-extracted parent records, then one question per field (lookup fields presented with an explicit choice list). Fields still null afterwards are re-asked in focused passes (max 2 re-asks = 3 calls total per table; re-asks never overwrite earlier answers; pass 3 is skipped when pass 2 made no progress). The field-chunk overflow path, record-count reconciliation, chunk merge and the `extraction_fields_per_call` setting are deleted.

**Tech Stack:** instructor/pydantic (response models unchanged), Django test runner, live local LLM for final validation (Qwen3.8-27B-NVFP4 at the configured base URL).

**Spec:** This plan + `docs/superpowers/plans/2026-10-12-client-app-docstrings.md` (table context source).

## Global Constraints

- **No client_app schema changes**; no new table-level instruction field — table context comes from the model's `__doc__` via `DatabaseTable.clientapp_content_type.model_class().__doc__`.
- **Prompt layout (document-first order — validated by A/B against the live model on the stored document, ProcessedText 5, pathology table, 31 fields):**

```
1. Task intro: "Extract the {TABLE} information from the document."
2. <document> ...full deidentified text... </document>          ← FIRST
3. TABLE CONTEXT: the table model's docstring (stripped)
4. Record-granularity line (neutral — see below)
5. PARENT RECORDS: JSON of the already-extracted parent table (only when the table has a parent)
6. QUESTIONS: one numbered question per field
7. EXTRACTION RULES (lookup choice rule, missing→null, negation, untrusted-document)
8. Output-format instruction: {"records": [...]}, raw JSON, no fences
```

  A/B result (same document/model, 44s each): doc-first filled **23** fields vs **19** doc-last and matched the lookup option label exactly; both returned 1 record. Doc-first is the default; the builder takes `document_first: bool = True` so the order remains testable.
- **Neutral record-granularity line** (table-agnostic; table-specific rules live in docstrings):
  `"Each distinct {table} entry described in the document becomes ONE record, in the order the entries appear. Return {"records": []} when the document contains none."`
- **Question style:** plain fields: `What {help_text lowercased, trailing '.' removed}?` (fall back to `What is the {humanized field name}?` when `help_text` is empty). Lookup fields: `What {help_text}? The following choices are available to you - select from these only: {labels joined by '; '}.`
- **Attempt budget per table:** pass 1 (all fields) + re-ask pass 2 (null fields only) + re-ask pass 3 (fields still null after pass 2). **Pass 3 runs only if pass 2 produced at least one non-null value.** Answers from earlier passes are never re-asked or overwritten.
- **Re-ask record alignment:** a re-ask response must return the same number of records as pass 1 (index-aligned); otherwise the re-ask's answers are discarded (log warning).
- **Unchanged:** the mining stage (lookup snippet mining + recheck + embedding option resolution — lookup options continue to be sent to the LLM; NO high-similarity skip), the single approval gate (`AWAITING_EXTRACTION`), the review flow, `PARTIAL` save semantics, child-skip on ancestor failure, the legacy path (jobs without `extraction_plan_version == 2` in `config_snapshot`), saved result shape (roots only in `data`; children nested in place).
- `extraction_plan_version` stays `2`.
- **Test command:** `venv/bin/python manage.py test extractor` (known pre-existing failures on main: `InferenceModelTests.test_invalid_assessments_rejected` case 5, `DeidReplacementTests.test_resolve_overlaps_keeps_highest_score` — ignore these two).
- **Branch:** continue on `split-extraction-calls` — do NOT create a new branch.

## File Map

- Modify: `extractor/services/extraction_split.py` — new `build_table_question_prompt`, new `table_docstring()` helper, delete `plan_table_chunks` / `build_chunk_prompt` / `merge_table_chunks` / `TableMergeError` (keep `plan_extraction_calls` simplified, `rescue_single_parent`, `nest_children`, `_parent_context_block` reused).
- Modify: `extractor/services/instructor_extractor.py` — new gap-fill helper(s), rewire per-table execution, delete reconciliation (`_reconcile_table_counts`, `_reask_chunk_count`, `RECONCILE_INSTRUCTION`).
- Modify: `extractor/services/pydantic_builder.py` — rename `build_chunk_response_model` → `build_table_response_model` (same behaviour; it already supports field subsets + parent_index).
- Modify: `extractor/models.py` — drop `ClientConfiguration.extraction_fields_per_call`; new migration.
- Modify: `extractor/views.py`, `templates/extractor/client_configuration_create.html`, `templates/extractor/client_configuration_edit.html` — remove the setting.
- Modify: `extractor/tests.py` — new prompt/loop tests; retire chunk-specific tests.

---

### Task 1: `table_docstring()` + `build_table_question_prompt`

**Files:**
- Modify: `extractor/services/extraction_split.py`
- Test: `extractor/tests.py` (new class `TablePromptTests`)

**Interfaces:**
- Consumes: `ResponseModelTableField` rows, `DatabaseField.help_text`, `field.lookup_field` / `field.lookup_content_type`, `resolved_options` (`{field_id: [{'code','label'}...]}` from mining), `ancestor_records` (list of parent-record dicts, already used by `_parent_context_block`).
- Produces:
  - `table_docstring(model_table) -> str` — stripped `__doc__` of the client_app model, or `''` when missing.
  - `build_table_question_prompt(response_model, model_table, fields, document, *, resolved_options=None, ancestor_records=None, document_first=True) -> list[dict]` — the message list for one table call. Field list order = `order` from `ResponseModelTableField`.

- [ ] **Step 1: Write the failing tests**

Add to `extractor/tests.py` (reuse the `ChunkPromptTests` fixtures: `self.rm`, `self.rmt_d`, `self.rmt_p`, fields `site_0..3` lookup / `plain_0..2` int):

```python
class TablePromptTests(TestCase):
    def setUp(self):
        # same fixtures as ChunkPromptTests (copy them here)
        ...

    def test_document_comes_before_questions(self):
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC TEXT')
        content = msgs[-1]['content']
        self.assertLess(content.index('<document>'), content.index('QUESTIONS'))
        self.assertIn('DOC TEXT', content)

    def test_questions_are_questions_and_lookup_lists_choices(self):
        msgs = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC TEXT',
            resolved_options={self._f('site_0').id: [
                {'code': 'A', 'label': 'Label A'},
                {'code': 'B', 'label': 'Label B'}]})
        content = msgs[-1]['content']
        site_q = next(l for l in content.splitlines() if 'site_0' in l or 'side' in l.lower())
        self.assertTrue(site_q.rstrip().endswith('?'))
        self.assertIn('select from these only', content)
        self.assertIn('Label A; Label B', content)

    def test_docstring_is_included_as_table_context(self):
        import client_app.models as cm
        msgs = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC TEXT')
        content = msgs[-1]['content']
        doc = (cm.Diagnosis.__doc__ or '').strip()
        self.assertIn('TABLE CONTEXT:', content)
        if doc:
            self.assertIn(doc.splitlines()[0].strip(), content)

    def test_parent_records_block_present_only_for_children(self):
        parent = [{'site_0': 'Left', 'plain_0': 1}]
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC',
            ancestor_records=parent)
        self.assertIn('PARENT RECORDS:', msgs[-1]['content'])
        self.assertIn('Left', msgs[-1]['content'])
        msgs2 = build_table_question_prompt(
            self.rm, self.rmt_d, self._diagnosis_fields(), 'DOC')
        self.assertNotIn('PARENT RECORDS:', msgs2[-1]['content'])

    def test_neutral_granularity_line_present(self):
        msgs = build_table_question_prompt(
            self.rm, self.rmt_p, self._pathology_fields(), 'DOC')
        content = msgs[-1]['content']
        self.assertIn('ONE record', content)
        self.assertIn('{"records": []}', content)
        self.assertNotIn('exactly ONE record object for the', content)
```

(Helper `_diagnosis_fields()` / `_pathology_fields()` return the `DatabaseField` lists in `order`; `_f(name)` looks up by `clientapp_field_name`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.TablePromptTests`
Expected: FAIL with `ImportError: cannot import name 'build_table_question_prompt'`

- [ ] **Step 3: Implement**

In `extraction_split.py`:

```python
def table_docstring(model_table):
    cls = model_table.database_table.clientapp_content_type.model_class()
    return (cls.__doc__ or '').strip() if cls else ''


def _question_for(field, resolved_options=None):
    stem = (field.help_text or '').strip()
    if stem:
        q = f"What {stem.rstrip('.').lower()}?"
    else:
        human = field.clientapp_field_name.replace('_', ' ')
        q = f"What is the {human}?"
    if field.lookup_field:
        options = (resolved_options or {}).get(field.id, [])
        if options:
            labels = '; '.join(o['label'] for o in options)
            q += f" The following choices are available to you - " \
                 f"select from these only: {labels}."
        else:
            q += " If the document states a value, copy it verbatim."
    return q
```

`build_table_question_prompt(response_model, model_table, fields, document, *, resolved_options=None, ancestor_records=None, document_first=True) -> list[dict]`:
- `table_name = model_table.database_table.clientapp_content_type.model`
- Build blocks: intro (`f"Extract the {table_name.upper()} information from the document."`), document block (`<document>\n{document}\n</document>`), table context (`TABLE CONTEXT:\n` + `table_docstring(model_table)` — omit the whole block when empty), granularity line (the Global Constraints neutral line with `{table}`), parent block (`PARENT RECORDS:\n` + `json.dumps(ancestor_records, indent=2)` + the existing `_parent_context_block` guidance line about `parent_index` — reuse its wording), questions (numbered `1. {question}` per field in `order`), rules (copy the four current rules: lookup choice, missing→null, negation, untrusted `<document>`), output instruction (current IMPORTANT line).
- Order: intro, [document if document_first], table context, granularity, parent block (if `ancestor_records` is not None), questions, rules, output, [document if not document_first].
- Returns `[{'role': 'user', 'content': content}]`.
- Keep `MISSING_RULE_*` / `NEGATION_RULE_*` class attributes on the service as the rule text source (they are plain-text rules; copy verbatim, no per-field formatting inside).

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test extractor.tests.TablePromptTests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/services/extraction_split.py extractor/tests.py
git commit -m "feat: document-first question-style per-table prompt with docstring context"
```

---

### Task 2: Gap-fill re-ask helper

**Files:**
- Modify: `extractor/services/instructor_extractor.py`
- Test: `extractor/tests.py` (extend `TablePromptTests` or new `GapFillTests`)

**Interfaces:**
- Consumes: `build_table_question_prompt` (Task 1) with a restricted field list; `PydanticModelBuilder.build_table_response_model` (Task 3 renames it, but the current `build_chunk_response_model` works — code against the new name and do the rename in Task 3 Step 1); client via `InstructorExtractionService._get_llm_client`.
- Produces:
  - `null_fields_for(records, fields) -> list[DatabaseField]` — fields whose value is null/'' on ANY record.
  - `InstructorExtractionService._refill_null_fields(extraction_job, response_model, model_table, fields, asked_fields, records, document, *, resolved_options, ancestor_records, client, client_config, validation_context) -> tuple[list[dict], int]` — one focused LLM call asking only `asked_fields`; returns `(updated_records, tokens)`. `updated_records` keeps pass-1 values for all other fields; fills nulls index-by-index; if the response has a different record count, returns the input records unchanged with tokens spent.

- [ ] **Step 1: Write the failing tests** (mock `create_with_completion` like `ChunkedStageExtractTests._run` does)

```python
def test_refill_fills_only_nulls_and_never_overwrites(self):
    # pass-1 record: site_0 filled, plain_0 null
    records = [{'site_0': 'Left', 'plain_0': None}]
    # LLM answers the focused question with plain_0=2 and (temptingly) site_0='Right'
    ...  # mock returns records=[{'plain_0': 2, 'site_0': 'Right', ...assessments...}]
    updated, tokens = InstructorExtractionService._refill_null_fields(...)
    self.assertEqual(updated[0]['plain_0'], 2)
    self.assertEqual(updated[0]['site_0'], 'Left')  # not overwritten

def test_refill_discards_misaligned_record_counts(self):
    records = [rec1, rec2]
    ...  # mock returns a single record
    updated, _ = InstructorExtractionService._refill_null_fields(...)
    self.assertEqual(updated, records)  # unchanged

def test_refill_prompt_asks_only_null_fields_and_keeps_document_first(self):
    ...  # capture kwargs['messages']
    self.assertIn('still empty' or 'previous pass', content_lower)  # focused framing
    self.assertLess(content.index('<document>'), content.index('QUESTIONS'))
    self.assertNotIn('question about site_0', content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test extractor.tests.GapFillTests`
Expected: FAIL with `AttributeError: ... '_refill_null_fields'`

- [ ] **Step 3: Implement**

`null_fields_for(records, fields)`: a field is "null" when EVERY record has the value None, `''` or absent (a record with a value means the field is answered). Note `field_assessments` values are not field values.

`_refill_null_fields(...)` (static method):
1. Build the focused prompt with `build_table_question_prompt(..., fields=asked_fields, ...)` plus a leading line: `"In the previous extraction pass, the following fields of this table were left empty. Re-read the document carefully and answer only these questions. Do not repeat fields that already have values."`
2. Build the response model with ONLY `asked_fields` (subset model — instructor validates only what is asked) via `build_table_response_model(model_table, asked_fields, include_field_assessments=..., with_parent_index=bool(ancestor_records is not None))` — when the table is a child table the subset model still carries `parent_index`; ignore returned parent_index values (alignment is by index, pass-1 values).
3. Call `client.chat.completions.create_with_completion(context=validation_context, **create_kwargs)` with the same kwargs pattern as the main pass (model, response_model, messages, timeout, reasoning kwargs, optional max_tokens).
4. On `InstructorRetryException` with failed attempts → attempt `_repair_failed_extraction` (same as main pass); on any other exception → log and return `(records, 0)`.
5. When `include_assessments`: re-validate via `wrapper.model_validate(result.model_dump(), context=validation_context)`; on `ValidationError` → log + return `(records, tokens so far)`.
6. If `len(result.records) != len(records)` → log warning, return `(records, tokens)`.
7. Merge: for each record index, copy ONLY keys for `asked_fields` (and that record's `field_assessments` entries whose `field` is an asked field) from the new record when the new value is non-null. Return `(updated, tokens)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test extractor.tests.GapFillTests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add extractor/services/instructor_extractor.py extractor/tests.py
git commit -m "feat: focused null-field re-ask pass with never-overwrite merge"
```

---

### Task 3: One call per table + 3-attempt loop; delete chunking machinery

**Files:**
- Modify: `extractor/services/pydantic_builder.py`
- Modify: `extractor/services/extraction_split.py`
- Modify: `extractor/services/instructor_extractor.py`
- Test: `extractor/tests.py`

**Interfaces:**
- Produces:
  - `PydanticModelBuilder.build_table_response_model(model_table, fields, *, include_field_assessments=False, with_parent_index=False)` (rename of `build_chunk_response_model`, signature unchanged).
  - `plan_extraction_calls(response_model, batch_size=None) -> list[dict]` — one entry per table: `{'model_table', 'table', 'fields', 'call_kind': 'table', 'ancestry'}` (field order = `order`; `batch_size` parameter kept but ignored, so existing call sites/tests do not break before Task 4 cleanup).
  - `_run_table_extraction(extraction_job, processed_content)` — renamed from `_run_chunked_extraction`; per table: pass 1 → up to 2 `_refill_null_fields` passes with the Global-Constraints gating (pass 3 only if pass 2 produced ≥1 non-null value); trace `call_result` entries gain a `'pass'` key (1/2/3).

- [ ] **Step 1: Rename the response-model builder**

Rename `build_chunk_response_model` → `build_table_response_model` in `pydantic_builder.py` and all references (`instructor_extractor.py`, `tests.py`).

Run: `venv/bin/python manage.py test extractor` — expect the 2 known pre-existing failures only.

- [ ] **Step 2: Simplify planning (one entry per table)**

In `extraction_split.py`, rewrite `plan_extraction_calls` to emit a single `{'kind': 'table'}` chunk per table with ALL its active fields in `order`. Delete `plan_table_chunks`.

Update the plan-entry builder in `instructor_extractor.py` (`build_extraction_plan_entries`) to use the new shape: `call_kind` is always `'table'`; prompt built with `build_table_question_prompt(..., table_chunk_count omitted)`; `fields` = all table fields.

- [ ] **Step 3: Rewire execution**

In `_run_table_extraction` (renamed):
- For each entry (sequential, parent-first order unchanged): skip when an ancestor failed (unchanged); build the FULL table response model; build the prompt with `build_table_question_prompt` (document = `processed_content`, `ancestor_records` = the merged parent table records — the current parent-context logic); pass 1 call (current try/repair/error handling unchanged).
- After pass 1 succeeds: `asked = null_fields_for(records, fields)`; loop `for pass_no in (2, 3)`: if `asked` empty → break; call `_refill_null_fields`; if pass 2 produced zero non-null fills → skip pass 3 (per Global Constraints); update `asked` for the next pass. Trace each pass with `_append_trace(..., 'call_result', pass=pass_no, ...)`.
- Delete: the `table_chunks` accumulation, `merge_table_chunks` import/use, the reconciliation block (`_reconcile_table_counts`, `_reask_chunk_count`, `RECONCILE_INSTRUCTION`), and `TableMergeError` handling. Merged = pass-1 records (possibly gap-filled).
- Assembly unchanged (`records_by_table`, `rescue_single_parent`, `nest_children`, roots-only `data`).
- `stage_extract` dispatch: `_run_chunked_extraction` → `_run_table_extraction` (same `extraction_plan_version == 2` gate).

- [ ] **Step 4: Rewrite the affected tests**

- `ExtractionPlanTests`: replace chunk-shape assertions with one-entry-per-table assertions; delete `test_oversized_table_chunks_lookup_fields_before_plain_fields`; keep `test_small_table_gets_one_single_call` renamed to `test_one_entry_per_table_all_fields_in_order`; keep `test_table_without_extractable_fields_makes_no_call`.
- `ChunkedStageExtractTests` → rename class to `TableExtractTests`: fixture now produces exactly 2 entries (diagnosis, pathology) — `_record_for` already returns one record per table (drop the lookup/plain branching); `test_record_count_mismatch_reconciles_by_reasking` is DELETED (reconciliation removed); `test_grandchild_of_failed_table_is_dropped_not_crashing` keeps its scenario but the failure now comes from a failed call (mock the pathology call to raise) instead of a chunk mismatch; add `test_gap_fill_passes_run_for_null_fields`: pass 1 returns one record with `plain_0` null, mock pass 2 returns it filled → assert 2 LLM calls for diagnosis, final data has the value; add `test_gap_fill_stops_when_second_pass_fills_nothing`: pass 2 returns null → assert total 2 calls for diagnosis (no pass 3).
- `ChunkPromptTests`: delete tests that assert `ONLY PART` / chunk splitting; keep the docstring/prompt-order coverage that moved to `TablePromptTests` (Task 1).
- `SplitSettingTests`: deleted entirely (setting removed in Step 5).

- [ ] **Step 5: Remove `extraction_fields_per_call`**

- `extractor/models.py`: delete the field.
- `venv/bin/python manage.py makemigrations extractor` → new migration dropping the column (the dev DB has it from migration 0028/0029).
- `extractor/views.py`: drop the form handling/kwargs for the field (create + edit views).
- `templates/extractor/client_configuration_create.html` and `client_configuration_edit.html`: remove the input + help text.
- `extractor/tests.py`: delete `SplitSettingTests`.

- [ ] **Step 6: Run the full extractor suite**

Run: `venv/bin/python manage.py test extractor`
Expected: PASS except the 2 known pre-existing failures.

- [ ] **Step 7: Commit**

```bash
git add extractor/
git commit -m "refactor: one call per table with 2 focused null-field re-asks; remove field chunking and reconciliation"
```

---

### Task 4: Live validation run

**Files:** none (verification only; may touch `extractor/PROGRESS.md`).

- [ ] **Step 1: Update the live config row** (the dev DB row still carries the old default)

```bash
venv/bin/python manage.py shell -c "
from extractor.models import ClientConfiguration
ClientConfiguration.objects.filter(id=1).update(extraction_fields_per_call=None)"
```

(If the column drop migration keeps the DB row readable, skip — verify with the query below.)

- [ ] **Step 2: Run a real extraction**

```bash
nohup venv/bin/python /tmp/run_extraction.py > /tmp/extraction_run6.log 2>&1 &
```

(Script reuses response model 2 + ProcessedText 5 — the teaching pathology report with 3 specimens.)

- [ ] **Step 3: Verify**

From the log + DB (`ExtractionJob` last id, `stage_trace`, `raw_llm_response`):
- 5 extraction tables → pass-1 calls + any gap-fill passes; trace shows `pass` keys.
- `diagnosis[0]['pathology']` has **exactly 1 record** combining the 3 specimens (tumor dimension 2.6, margin 5 mm, PNI/LVI present, node counts consolidated).
- Stage/surgery nested under diagnosis; IHC empty.
- Gap-fill visibly filled at least one pass-1 null (e.g. `greatest_dimension_of_tumor`, `lymph_nodes_in_specimen`) — check the `pass=2` trace entries.
- Status `completed` or `partial` with honest `extraction_error`.

- [ ] **Step 4: Update `extractor/PROGRESS.md`**

Replace the "Split Stage-2 Extraction" section with the new behaviour (one call per table + docstring context + question-style document-first prompt + 2 null-field re-asks; chunking/reconciliation/setting removed; A/B numbers).

- [ ] **Step 5: Commit**

```bash
git add extractor/PROGRESS.md
git commit -m "docs: document the question-style per-table extraction flow"
```

---

## Self-Review

- **Spec coverage:** docstrings-as-prompts → Task 1 (context block) + the companion docstring plan; one-go table extraction → Task 3; parent context → Task 1 (`ancestor_records`) + Task 3 (merged parent records, unchanged); 2 re-asks with null-only focus / keep-earlier-answers / skip-pass-3-when-no-progress → Global Constraints + Task 2/3; mining unchanged incl. options always sent (no cosine skip) → Global Constraints; document first → layout constant + A/B evidence; "?" questions with explicit lookup choices → `_question_for`; cleanup confirmed → Task 3 Step 5.
- **Placeholder scan:** the `setUp`/mock bodies in Task 1/2 tests reference existing fixture patterns verbatim from `ChunkPromptTests` / `ChunkedStageExtractTests` — an executor reading `extractor/tests.py` has the complete working code to copy; no other steps lack code.
- **Type consistency:** `build_table_response_model` (Task 3 Step 1) is the name used by Task 2's implementation; `build_table_question_prompt(response_model, model_table, fields, document, *, resolved_options, ancestor_records, document_first)` is identical in Tasks 1, 2, 3; `null_fields_for(records, fields)` / `_refill_null_fields(...)` signatures match between Task 2 and Task 3's loop.
- **Known limitations (accepted):** the focused re-ask prompt re-sends the full document each pass (token cost accepted per user direction); the docstring quality directly bounds prompt quality — the docstring plan's per-model review gates mitigate drift.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-10-12-per-table-prompt-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
