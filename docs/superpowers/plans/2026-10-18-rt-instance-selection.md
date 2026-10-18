# RT Instance Selection Implementation Plan (Bulk DICOM Retrieval)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show RT objects (structure sets, plans, doses) in the bulk DICOM retrieval selection UI as individually selectable rows nested by their DICOM reference relationships, so a user can import exactly the RT objects they need (e.g. only the approved plan) while retrieval itself stays series-level.

**Architecture:** The query phase already collects per-instance RT data (SOP UIDs, labels, ApprovalStatus, reference sequences) into the study-tree JSON on `RetrievalBatchPatient.studies`. Selection becomes instance-level for RT objects (keyed by SOPInstanceUID) and series-level for image/other series. The server validates the selection, closes it under ancestors, stores (a) the series to retrieve as `RetrievalJobSeries` rows and (b) the closed SOP set as `RetrievalJobStudy.selected_sop_instance_uids`. Retrieval (C-MOVE/C-GET in `tasks.py`/`qr_client.py`) is unchanged — series-level only. At ingest time, instances not in the selection are dropped (audit row, no file, wire status still SUCCESS).

**Tech Stack:** Django (tests via `django.test.TestCase`), Django models + one migration, inline jQuery 3.6 JS in one template, pydicom/pynetdicom (Q/R paths untouched).

**Spec:** The agreed design is recorded in "Spec (agreed design)" below — there is no separate spec document; executors read both that section and the tasks.

## Spec (agreed design, working session 2026-10-18)

Background: the bulk DICOM retrieval selection UI (`templates/dicom_server/batch_select.html`) renders one row per series plus extra sub-rows per RT instance, nested at **series** level via `parent_series_uids`. That (a) showed plan instances as extra rows that duplicated their series row (e.g. the series named "final" plus a sub-row "final"), and (b) made it impossible to select "only the approved plan" when several plans share one series — selection was series-granular.

The DICOM facts the design relies on (verified against PS3.3 C.8.8/A.86 and the Varian DCS):

- A series of a given RT type may contain several instances; the series grouping carries **no normative semantics** (PS3.3 A.86: "internal references shall be used to relate and locate SOP Instances rather than making assumptions about how related SOP Instances are grouped into Studies or Series").
- An RTDose references exactly **one** plan (ReferencedRTPlanSequence: single item). An RTPlan references its structure set(s) via ReferencedStructureSetSequence. An RTStruct references its image series via ReferencedFrameOfReferenceSequence → RTReferencedStudySequence → RTReferencedSeriesSequence.
- Multiple plans can legally share one SeriesInstanceUID (each has its own SOPInstanceUID). ARIA/Eclipse exports often write one plan per series, but that is a convention, not a guarantee.

Agreed rules:

1. **Display = instance level.** The expanded study table shows:
   - image (and other non-RT-detail) series as **series rows**;
   - RTSTRUCT/RTPLAN/RTDOSE objects as **instance rows**, nested by per-instance references: struct set under the image series it references, plan under its struct set, dose under its (single) plan;
   - approval as **plain text** on the plan row (`approved` / `unapproved`) — no pill badge;
   - RT instances whose references do not resolve within the study render under their **own series row** (a container row with the existing aggregate details plus a `references missing` badge when `unresolved_refs` is set).
   - RTREG/RTIMAGE series keep series-level rows (no instance drill-down).
2. **Selection = instance level for RT** (checkbox per instance row, key = SOPInstanceUID), **series level for image/other series** (key = SeriesInstanceUID). Checking a node auto-pulls its ancestors (plan → struct set → image series; dose → plan → struct set → image series). Unchecking cascades to descendants (unchecking a struct set removes its plans and their doses).
3. **Retrieval = series level only.** No SOP-level C-MOVE/C-GET. Series to retrieve = user-selected series ∪ containing series of every selected RT instance ∪ containing series of pulled-in ancestor instances ∪ referenced image series — computed **server-side** from the study tree (the browser's claim is never trusted for closure).
4. **Ingest filter.** When a RUNNING job's study row has series rows (partial selection), arriving instances are dropped unless selected: RT-detail modalities per SOPInstanceUID, but only when the job stored a **non-empty** SOP set (an empty SOP set is the legacy/scheduled series-level selection → accept, exactly as before); other modalities per selected series. Jobs with no series rows (whole-study selection) accept everything.
5. **Unchanged:** the C-FIND query phase, the C-MOVE/C-GET implementation, `tasks.py` retrieval worker, the scheduled bulk flow (`bulk_selection.py`, `task_bulk_schedule_finalize_query`), and the single-patient flow (`RetrieveStudiesView`/`task_retrieve_studies`).
6. **Known limitation (documented, not fixed):** job `instances_received` counts wire-level sub-operations, so deliberately dropped instances still count toward it. Drops are visible in the `InboundDICOMInstance` audit log with reject_reason `Instance not selected in retrieval job` / `Series not selected in retrieval job`.

## Global Constraints

- Test command: `venv/bin/python manage.py test dicom_server` (Django test runner; **no pytest** in this repo). Run the full dicom_server suite after every task.
- New/changed Python tests live in `dicom_server/tests/`, `django.test.TestCase` style, helpers from `dicom_server/tests/utils.py` (`make_test_dataset`, `make_rt_dataset`).
- No new Python dependencies.
- Frontend is inline `<script>` jQuery (3.6) in the template — no JS build step, no JS framework, no new CDN assets.
- Study-tree JSON shape (from `RetrievalBatchPatient.studies` help_text): a study has `series[]`; each series has `series_instance_uid, series_description, modality, series_number, series_date, instances, rt_error?, instances_error?, parent_series_uids?, unresolved_refs?` and `rt_instances[]`; each RT instance has `sop_instance_uid, instance_number, modality?, series_date?, accession_number?, structure_set_label, structure_set_name, rt_plan_label, rt_plan_name, approval_status, referenced_plan_uids[], referenced_structure_set_uids[], referenced_series_uids[], referenced_image_uids[], referenced_image_series_uids[]` (absent keys possible — always use `|| []` / `.get()`).
- Commit after each task.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `dicom_server/constants.py` | Create | Import-safe shared constants: `RT_DETAIL_MODALITIES` (frozenset). No Django model imports — `ingest` and `qr_client` may both import it because `scp/handlers` ↔ `ingest` ↔ `qr_client` form an import cycle otherwise. |
| `dicom_server/services/instance_selection.py` | Create | Pure functions over the study-tree dict (no DB): SOP→series lookup, ancestor closure, selection validation/normalization. |
| `dicom_server/services/qr_client.py` | Modify | Replace its module-private `_RT_DETAIL_MODALITIES` set with `constants.RT_DETAIL_MODALITIES`. |
| `dicom_server/models.py` | Modify | Add `RetrievalJobStudy.selected_sop_instance_uids` JSONField. |
| `dicom_server/migrations/0011_*.py` | Create | Migration for the new field (generated by makemigrations). |
| `dicom_server/views.py` | Modify | `BatchRetrieveView.post` accepts the new payload, closes the selection under ancestors, persists the SOP set. |
| `dicom_server/services/ingest.py` | Modify | Drop unselected instances for jobs with a partial selection. |
| `templates/dicom_server/batch_select.html` | Modify | Instance-level tree rendering, selection, submit payload. |
| `dicom_server/tests/test_instance_selection.py` | Create | Unit tests for the pure helpers. |
| `dicom_server/tests/test_job_models.py` | Modify | Test for the new model field. |
| `dicom_server/tests/test_bulk_retrieval.py` | Modify | View tests for the new payload; update `test_batch_select_page` JS markers. |
| `dicom_server/tests/test_ingest.py` | Modify | Ingest selection-filter tests. |
| `dicom_server/tests/test_rt_instance_selection_e2e.py` | Create | End-to-end: POST selection → job rows → ingest accept/drop. |

---

### Task 1: Shared constant + pure instance-selection helpers

**Files:**
- Create: `dicom_server/constants.py`
- Create: `dicom_server/services/instance_selection.py`
- Create: `dicom_server/tests/test_instance_selection.py`
- Modify: `dicom_server/services/qr_client.py` (line 461 `_RT_DETAIL_MODALITIES = {...}` and its only use at line 480)

**Interfaces:**
- Consumes: nothing (pure functions over dicts shaped like `RetrievalBatchPatient.studies`).
- Produces (Tasks 3–5 rely on these exact names/signatures):
  - `constants.RT_DETAIL_MODALITIES: frozenset` — `{'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'RTREG', 'RTIMAGE'}`
  - `instance_selection.SelectionError` (subclass of `ValueError`; message is user-safe)
  - `instance_selection.sop_series_uid(study: dict, sop_uid: str) -> str | None`
  - `instance_selection.instance_ancestors(study: dict, sop_uid: str) -> tuple[list[str], list[str]]` — `(ancestor_sop_uids, ancestor_series_uids)`
  - `instance_selection.normalize_selection(study: dict, series_uids: list[str] | None, sop_uids: list[str] | None) -> dict` — `{'series_uids': sorted list, 'sop_uids': sorted list}`; raises `SelectionError` on unknown UIDs.

- [ ] **Step 1: Write the failing tests**

Create `dicom_server/tests/test_instance_selection.py`:

```python
"""Unit tests for instance-level selection math — pure functions over the
study-tree dict (the JSON shape stored on RetrievalBatchPatient.studies)."""
from django.test import TestCase

from dicom_server.services.instance_selection import (
    SelectionError, instance_ancestors, normalize_selection, sop_series_uid,
)

# ARIA-like study: one CT, one RTSTRUCT series with 2 struct sets, one
# RTPLAN series with 2 plans (shared series UID, different SOP UIDs), one
# RTDOSE series with 2 doses (each references one plan).
STUDY = {
    'study_instance_uid': '1.2.3',
    'series': [
        {'series_instance_uid': 'ct', 'series_description': 'CECT',
         'modality': 'CT', 'series_number': 1, 'instances': 196},
        {'series_instance_uid': 'ss', 'series_description':
         'ARIA RadOnc Structure Sets', 'modality': 'RTSTRUCT',
         'series_number': 13, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'ss1', 'instance_number': '1',
              'structure_set_label': 'CT_FINAL',
              'referenced_series_uids': ['ct']},
             {'sop_instance_uid': 'ss2', 'instance_number': '2',
              'structure_set_label': 'Setup',
              'referenced_series_uids': ['ct']},
         ]},
        {'series_instance_uid': 'pl', 'series_description': 'ARIA RadOnc Plans',
         'modality': 'RTPLAN', 'series_number': 14, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'p1', 'instance_number': '1',
              'rt_plan_label': 'final', 'approval_status': 'APPROVED',
              'referenced_structure_set_uids': ['ss1']},
             {'sop_instance_uid': 'p2', 'instance_number': '2',
              'rt_plan_label': 'final_v2', 'approval_status': 'UNAPPROVED',
              'referenced_structure_set_uids': ['ss1']},
         ]},
        {'series_instance_uid': 'ds', 'series_description': 'Eclipse Doses',
         'modality': 'RTDOSE', 'series_number': 15, 'instances': 2,
         'rt_instances': [
             {'sop_instance_uid': 'd1', 'instance_number': '1',
              'referenced_plan_uids': ['p1']},
             {'sop_instance_uid': 'd2', 'instance_number': '2',
              'referenced_plan_uids': ['p2']},
         ]},
    ],
}

# Struct set whose referenced image series is NOT in the study (orphan).
ORPHAN_STUDY = {
    'study_instance_uid': '9',
    'series': [
        {'series_instance_uid': 'ssX', 'modality': 'RTSTRUCT',
         'instances': 1,
         'rt_instances': [
             {'sop_instance_uid': 'sX', 'referenced_series_uids': ['nope']},
         ]},
    ],
}


class SopSeriesUidTests(TestCase):
    def test_plan_maps_to_its_containing_series(self):
        self.assertEqual(sop_series_uid(STUDY, 'p1'), 'pl')
        self.assertEqual(sop_series_uid(STUDY, 'd2'), 'ds')

    def test_unknown_sop_is_none(self):
        self.assertIsNone(sop_series_uid(STUDY, 'zzz'))
        self.assertIsNone(sop_series_uid(STUDY, ''))


class InstanceAncestorsTests(TestCase):
    def test_plan_pulls_struct_set_and_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'p1')
        self.assertEqual(sops, ['ss1'])
        self.assertEqual(seuids, ['ct'])

    def test_dose_pulls_plan_and_struct_set_and_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'd1')
        self.assertEqual(sops, ['p1', 'ss1'])
        self.assertEqual(seuids, ['ct'])

    def test_struct_set_pulls_only_its_image_series(self):
        sops, seuids = instance_ancestors(STUDY, 'ss1')
        self.assertEqual(sops, [])
        self.assertEqual(seuids, ['ct'])

    def test_orphan_struct_set_has_no_series_ancestors(self):
        sops, seuids = instance_ancestors(ORPHAN_STUDY, 'sX')
        self.assertEqual(sops, [])
        self.assertEqual(seuids, [])

    def test_unknown_sop_is_empty(self):
        self.assertEqual(instance_ancestors(STUDY, 'zzz'), ([], []))


class NormalizeSelectionTests(TestCase):
    def test_plan_selection_closes_under_ancestors_and_excludes_dose_series(self):
        self.assertEqual(
            normalize_selection(STUDY, None, ['p1']),
            {'series_uids': ['ct', 'pl', 'ss'], 'sop_uids': ['p1', 'ss1']},
        )

    def test_dose_selection_closes_through_plan(self):
        self.assertEqual(
            normalize_selection(STUDY, None, ['d1']),
            {'series_uids': ['ct', 'ds', 'pl', 'ss'],
             'sop_uids': ['d1', 'p1', 'ss1']},
        )

    def test_series_only_selection(self):
        self.assertEqual(
            normalize_selection(STUDY, ['ct'], None),
            {'series_uids': ['ct'], 'sop_uids': []},
        )

    def test_mixed_selection(self):
        self.assertEqual(
            normalize_selection(STUDY, ['ct'], ['p2']),
            {'series_uids': ['ct', 'pl', 'ss'], 'sop_uids': ['p2', 'ss1']},
        )

    def test_orphan_struct_set_still_pulls_its_own_series(self):
        self.assertEqual(
            normalize_selection(ORPHAN_STUDY, None, ['sX']),
            {'series_uids': ['ssX'], 'sop_uids': ['sX']},
        )

    def test_unknown_sop_raises(self):
        with self.assertRaises(SelectionError):
            normalize_selection(STUDY, None, ['zzz'])

    def test_unknown_series_raises(self):
        with self.assertRaises(SelectionError):
            normalize_selection(STUDY, ['nope'], None)

    def test_empty_selections_yield_empty_result(self):
        self.assertEqual(
            normalize_selection(STUDY, None, None),
            {'series_uids': [], 'sop_uids': []},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test dicom_server.tests.test_instance_selection -v 2`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'dicom_server.services.instance_selection'`

- [ ] **Step 3: Implement `dicom_server/constants.py`**

```python
"""Shared constants for dicom_server services.

Kept free of Django model imports so any service module can import it:
scp/handlers -> ingest -> qr_client -> scp/handlers would be a cycle if a
shared constant lived in qr_client instead.
"""

# Modalities whose instances carry RT attributes worth enumerating via
# IMAGE-level C-FIND (labels, approval status, reference sequences).
RT_DETAIL_MODALITIES = frozenset(
    {'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'RTREG', 'RTIMAGE'})
```

- [ ] **Step 4: Implement `dicom_server/services/instance_selection.py`**

```python
"""Instance-level selection math over a study-tree dict.

Pure functions (no DB access) shared by BatchRetrieveView so the server — not
the browser — validates selections and decides which series to retrieve. The
study-tree shape is the JSON stored on RetrievalBatchPatient.studies (see the
help_text on that field in dicom_server/models.py).

Reference hierarchy used (populated by qr_client._find_instances_on_assoc):
  RTDOSE   -> referenced_plan_uids              (exactly one plan per dose)
  RTPLAN   -> referenced_structure_set_uids
  RTSTRUCT -> referenced_series_uids            (the image series)
"""


class SelectionError(ValueError):
    """Unknown UID or malformed selection — message is safe to show to the user."""


def _series_by_uid(study):
    return {se.get('series_instance_uid'): se
            for se in (study.get('series') or [])}


def _sop_index(study):
    """{sop_instance_uid: (series_dict, instance_dict)} for all RT instances."""
    out = {}
    for se in study.get('series') or []:
        for inst in se.get('rt_instances') or []:
            sop = inst.get('sop_instance_uid')
            if sop:
                out[sop] = (se, inst)
    return out


def sop_series_uid(study, sop_uid):
    """SeriesInstanceUID containing this SOP instance, or None."""
    hit = _sop_index(study).get(sop_uid)
    if not hit:
        return None
    return hit[0].get('series_instance_uid') or None


def instance_ancestors(study, sop_uid):
    """Ancestors of one RT instance, closed transitively.

    Returns (ancestor_sop_uids, ancestor_series_uids): a dose pulls its plan
    and that plan's struct set; a plan pulls its struct set; a struct set
    pulls the image series it references (only when that series is in the
    study)."""
    idx = _sop_index(study)
    series = _series_by_uid(study)
    sops, seuids = [], []
    seen = {sop_uid}
    stack = [sop_uid]
    while stack:
        cur = stack.pop()
        hit = idx.get(cur)
        if not hit:
            continue
        se, inst = hit
        mod = (se.get('modality') or '').upper()
        if mod == 'RTDOSE':
            refs = inst.get('referenced_plan_uids') or []
        elif mod == 'RTPLAN':
            refs = inst.get('referenced_structure_set_uids') or []
        else:
            refs = []
        for ref in refs:
            if ref in idx and ref not in seen:
                seen.add(ref)
                sops.append(ref)
                stack.append(ref)
        if mod == 'RTSTRUCT':
            for ref in inst.get('referenced_series_uids') or []:
                if ref in series and ref not in seuids:
                    seuids.append(ref)
    return sops, seuids


def normalize_selection(study, series_uids, sop_uids):
    """Validate a selection and close it under ancestors.

    series_uids: series-level picks (any modality, e.g. image series).
    sop_uids: RT instance picks (must belong to the study's rt_instances).
    Either may be None.

    Returns {'series_uids': [...], 'sop_uids': [...]} (both sorted) where
    series_uids is everything to C-MOVE — user picks plus the containing
    series of every selected and ancestor RT instance plus referenced image
    series — and sop_uids is the closed instance set stored for ingest
    filtering. Raises SelectionError for unknown UIDs.
    """
    series = _series_by_uid(study)
    idx = _sop_index(study)
    out_series, out_sops = set(), set()
    for u in series_uids or []:
        if u not in series:
            raise SelectionError(f'unknown series UID {u!r}')
        out_series.add(u)
    for u in sop_uids or []:
        if u not in idx:
            raise SelectionError(f'unknown SOP instance UID {u!r}')
        out_sops.add(u)
        a_sops, a_series = instance_ancestors(study, u)
        out_sops.update(a_sops)
        out_series.update(a_series)
        for s in [u] + a_sops:
            containing = sop_series_uid(study, s)
            if containing:
                out_series.add(containing)
    return {'series_uids': sorted(out_series), 'sop_uids': sorted(out_sops)}
```

- [ ] **Step 5: Point `qr_client.py` at the shared constant**

In `dicom_server/services/qr_client.py`:

1. Add the import next to the other `dicom_server` imports (after line 24's `from dicom_server.models import (...)` block):

```python
from dicom_server import constants
```

2. Delete line 461:

```python
_RT_DETAIL_MODALITIES = {'RTSTRUCT', 'RTPLAN', 'RTDOSE', 'RTREG', 'RTIMAGE'}
```

3. At line 480, change:

```python
            needs_rt = (se.get('modality') or '').upper() in _RT_DETAIL_MODALITIES
```

to:

```python
            needs_rt = (se.get('modality') or '').upper() in constants.RT_DETAIL_MODALITIES
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/python manage.py test dicom_server.tests.test_instance_selection dicom_server.tests.test_qr -v 1`
Expected: PASS (test_qr guards the qr_client rename).

- [ ] **Step 7: Run the full app test suite**

Run: `venv/bin/python manage.py test dicom_server`
Expected: PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add dicom_server/constants.py dicom_server/services/instance_selection.py \
        dicom_server/services/qr_client.py dicom_server/tests/test_instance_selection.py
git commit -m "feat(dicom_server): add instance-level selection math over study trees"
```

### Task 2: `RetrievalJobStudy.selected_sop_instance_uids` field + migration

**Files:**
- Modify: `dicom_server/models.py` (class `RetrievalJobStudy`, ~line 224)
- Create: `dicom_server/migrations/0011_*.py` (generated)
- Test: `dicom_server/tests/test_job_models.py` (class `RetrievalJobStudyTests`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `RetrievalJobStudy.selected_sop_instance_uids` — `JSONField`, `default=list`, `blank=True`; holds the closed list of selected RT SOPInstanceUIDs for this study (empty list = whole-study or legacy series-level selection). Tasks 3 and 4 read/write it.

- [ ] **Step 1: Write the failing test**

Append to class `RetrievalJobStudyTests` in `dicom_server/tests/test_job_models.py`:

```python
    def test_selected_sop_instance_uids_defaults_to_empty_list(self):
        job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        study = RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='1.2.3')
        self.assertEqual(study.selected_sop_instance_uids, [])
        study.selected_sop_instance_uids = ['p1', 'ss1']
        study.save(update_fields=['selected_sop_instance_uids'])
        study.refresh_from_db()
        self.assertEqual(study.selected_sop_instance_uids, ['p1', 'ss1'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test dicom_server.tests.test_job_models.RetrievalJobStudyTests -v 2`
Expected: FAIL with `AttributeError: 'RetrievalJobStudy' has no attribute 'selected_sop_instance_uids'`

- [ ] **Step 3: Add the field**

In `dicom_server/models.py`, in `class RetrievalJobStudy`, after the `accession_number` field (line ~239):

```python
    # Instance-level RT selection for this study: closed list of selected
    # SOPInstanceUIDs (plans/struct sets/doses + pulled-in ancestors).
    # Empty list = whole-study selection or a legacy/scheduled
    # series-level selection (ingest then accepts every RT instance of
    # the selected series).
    selected_sop_instance_uids = models.JSONField(default=list, blank=True)
```

- [ ] **Step 4: Generate and apply the migration**

Run: `venv/bin/python manage.py makemigrations dicom_server`
Expected: creates `dicom_server/migrations/0011_...py` containing `AddField(model_name='retrievaljobstudy', name='selected_sop_instance_uids', ...)`.
Run: `venv/bin/python manage.py migrate dicom_server`
Expected: `0011_...` applied.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python manage.py test dicom_server.tests.test_job_models -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dicom_server/models.py dicom_server/migrations/0011_*.py \
        dicom_server/tests/test_job_models.py
git commit -m "feat(dicom_server): store per-study RT SOP selection on RetrievalJobStudy"
```

---

### Task 3: `BatchRetrieveView` — instance-level payload, server-side closure

**Files:**
- Modify: `dicom_server/views.py` — `BatchRetrieveView.post` (~lines 610–690), plus imports at top of file
- Test: `dicom_server/tests/test_bulk_retrieval.py` (class `BulkRetrievalTestCase`)

**Interfaces:**
- Consumes: `instance_selection.normalize_selection`, `instance_selection.SelectionError` (Task 1); `RetrievalJobStudy.selected_sop_instance_uids` (Task 2).
- Produces: new POST contract for `dicom_server:batch_retrieve` —
  `{'selections': {patient_id: [{study_instance_uid, series_uids?: list|null, sop_instance_uids?: list|null}]}}`
  where `series_uids` = series-level picks, `sop_instance_uids` = RT instance picks. Both keys absent/null ⇒ whole study. Legacy key `series_instance_uids` is accepted as an alias of `series_uids` (old UI/tests keep working; its selections store an empty SOP set → legacy ingest behaviour). Persisted per study: `RetrievalJobSeries` rows for `normalize_selection(...)['series_uids']` and `selected_sop_instance_uids = ['...']` (or `[]` for whole-study).

- [ ] **Step 1: Write the failing tests**

Append to class `BulkRetrievalTestCase` in `dicom_server/tests/test_bulk_retrieval.py` (it already provides `self.node`, `self.user`, `self.plain`, `self._patient(pid)`, `self._post_json(url, body)`, and imports `RetrievalBatch`, `RetrievalBatchPatient`, `RetrievalJob`, `RetrievalJobStudy`; add `mock` to the existing `from unittest import mock` import if not present — it is already imported at module level):

```python
    @classmethod
    def _rt_study_tree(cls):
        """ARIA-like tree: CT + struct-set series + plan series (2 plans) +
        dose series (1 dose). Mirrors the fixture in test_instance_selection."""
        return [{
            'study_instance_uid': '1.2', 'remote_patient_id': 'X',
            'study_date': '20250407', 'study_description': 'RT Planning CT',
            'accession_number': 'EY581041', 'modalities': 'CT, RTSTRUCT, RTPLAN, RTDOSE',
            'series': [
                {'series_instance_uid': 'ct', 'series_description': 'CECT',
                 'modality': 'CT', 'series_number': 1, 'instances': 196},
                {'series_instance_uid': 'ss', 'series_description':
                 'ARIA RadOnc Structure Sets', 'modality': 'RTSTRUCT',
                 'series_number': 13, 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'ss1', 'instance_number': '1',
                      'structure_set_label': 'CT_FINAL',
                      'referenced_series_uids': ['ct']}]},
                {'series_instance_uid': 'pl', 'series_description': 'final',
                 'modality': 'RTPLAN', 'series_number': 14, 'instances': 2,
                 'rt_instances': [
                     {'sop_instance_uid': 'p1', 'instance_number': '1',
                      'rt_plan_label': 'final', 'approval_status': 'APPROVED',
                      'referenced_structure_set_uids': ['ss1']},
                     {'sop_instance_uid': 'p2', 'instance_number': '2',
                      'rt_plan_label': 'final_v2',
                      'approval_status': 'UNAPPROVED',
                      'referenced_structure_set_uids': ['ss1']}]},
                {'series_instance_uid': 'ds', 'series_description':
                 'Eclipse Doses', 'modality': 'RTDOSE', 'series_number': 15,
                 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'd1', 'instance_number': '1',
                      'referenced_plan_uids': ['p1']}]},
            ],
        }]

    @mock.patch('dicom_server.views.chord')
    def test_batch_retrieve_instance_selection_closes_ancestors(self, mock_chord):
        mock_chord.return_value.return_value.id = 'chord-i1'
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient, studies=self._rt_study_tree())
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {patient.patient_id: [{
                'study_instance_uid': '1.2',
                'sop_instance_uids': ['p1'],
            }]}},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        job = RetrievalJob.objects.get()
        study = job.studies.get()
        # Selected plan + its struct-set ancestor; dose series NOT retrieved.
        self.assertEqual(study.selected_sop_instance_uids, ['p1', 'ss1'])
        self.assertEqual(
            sorted(study.series.values_list('series_instance_uid', flat=True)),
            ['ct', 'pl', 'ss'],
        )
        mock_chord.assert_called_once()

    @mock.patch('dicom_server.views.chord')
    def test_batch_retrieve_series_and_instance_mixed(self, mock_chord):
        mock_chord.return_value.return_value.id = 'chord-i2'
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient, studies=self._rt_study_tree())
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {patient.patient_id: [{
                'study_instance_uid': '1.2',
                'series_uids': ['ct'],
                'sop_instance_uids': ['d1'],
            }]}},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        study = RetrievalJob.objects.get().studies.get()
        self.assertEqual(study.selected_sop_instance_uids, ['d1', 'p1', 'ss1'])
        self.assertEqual(
            sorted(study.series.values_list('series_instance_uid', flat=True)),
            ['ct', 'ds', 'pl', 'ss'],
        )

    def test_batch_retrieve_unknown_sop_rejected(self):
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient, studies=self._rt_study_tree())
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {patient.patient_id: [{
                'study_instance_uid': '1.2',
                'sop_instance_uids': ['zzz'],
            }]}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(RetrievalJob.objects.exists())

    @mock.patch('dicom_server.views.chord')
    def test_batch_retrieve_whole_study_unchanged(self, mock_chord):
        mock_chord.return_value.return_value.id = 'chord-i3'
        patient = self._patient('MR/25/004771')
        batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=batch, patient=patient, studies=self._rt_study_tree())
        self.client.force_login(self.user)
        resp = self._post_json(
            reverse('dicom_server:batch_retrieve', args=[batch.pk]),
            {'selections': {patient.patient_id: [{
                'study_instance_uid': '1.2',
                'series_uids': None, 'sop_instance_uids': None,
            }]}},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        study = RetrievalJob.objects.get().studies.get()
        self.assertEqual(study.selected_sop_instance_uids, [])
        self.assertEqual(study.series.count(), 0)  # whole study
```

The existing `test_batch_retrieve_creates_jobs_and_chord` (legacy `series_instance_uids` key) and `test_batch_retrieve_rejects_unknown_uids` must keep passing unmodified — they are the legacy-compat proof.

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test dicom_server.tests.test_bulk_retrieval.BulkRetrievalTestCase -v 2`
Expected: the four new tests FAIL (view still validates `series_instance_uids` only / stores no SOP set), existing tests PASS.

- [ ] **Step 3: Implement the view change**

In `dicom_server/views.py`:

1. Add the import with the other service imports (near the top where `from dicom_server.services import ...` lines live):

```python
from dicom_server.services import instance_selection
```

2. Replace the per-entry normalization block in `BatchRetrieveView.post` — from

```python
                series_req = entry.get('series_instance_uids')
                if series_req is not None:
                    if not isinstance(series_req, list) or not series_req:
                        return JsonResponse({'error': (
                            f'{pid}: series_instance_uids must be a non-empty '
                            'list or null'
                        )}, status=400)
                    known_series = {
                        s.get('series_instance_uid')
                        for s in (study.get('series') or [])
                    }
                    unknown = set(series_req) - known_series
                    if unknown:
                        return JsonResponse({'error': (
                            f'{pid}: unknown series UID(s) {sorted(unknown)} '
                            f'for study {suid}'
                        )}, status=400)
                normalized.append({
                    'study_instance_uid': suid,
                    'series_instance_uids': series_req,
                    'remote_patient_id': study.get('remote_patient_id'),
                })
```

to:

```python
                series_req = entry.get(
                    'series_uids', entry.get('series_instance_uids'))
                sops_req = entry.get('sop_instance_uids')
                for label, value in (('series_uids', series_req),
                                     ('sop_instance_uids', sops_req)):
                    if value is not None and (
                            not isinstance(value, list) or not value):
                        return JsonResponse({'error': (
                            f'{pid}: {label} must be a non-empty list or null'
                        )}, status=400)
                if series_req is None and sops_req is None:
                    normalized.append({
                        'study_instance_uid': suid,
                        'series_uids': None,  # whole study
                        'sop_uids': [],
                        'remote_patient_id': study.get('remote_patient_id'),
                    })
                    continue
                try:
                    norm = instance_selection.normalize_selection(
                        study, series_req, sops_req)
                except instance_selection.SelectionError as e:
                    return JsonResponse(
                        {'error': f'{pid}: {e} for study {suid}'}, status=400)
                normalized.append({
                    'study_instance_uid': suid,
                    'series_uids': norm['series_uids'],
                    'sop_uids': norm['sop_uids'],
                    'remote_patient_id': study.get('remote_patient_id'),
                })
```

3. Replace the series-creation block:

```python
            # Series
            for entry in normalized:
                series_uids = entry.get('series_instance_uids')
                if series_uids:
                    job_study = job.studies.get(
                        study_instance_uid=entry['study_instance_uid'],
                    )
                    RetrievalJobSeries.objects.bulk_create([
                        RetrievalJobSeries(study=job_study, series_instance_uid=su)
                        for su in series_uids
                    ])
```

with:

```python
            # Series + instance-level SOP set
            for entry in normalized:
                series_uids = entry['series_uids']
                if series_uids:
                    job_study = job.studies.get(
                        study_instance_uid=entry['study_instance_uid'],
                    )
                    RetrievalJobSeries.objects.bulk_create([
                        RetrievalJobSeries(study=job_study, series_instance_uid=su)
                        for su in series_uids
                    ])
                    if entry['sop_uids']:
                        job_study.selected_sop_instance_uids = entry['sop_uids']
                        job_study.save(update_fields=['selected_sop_instance_uids'])
```

Note: `normalize_selection` validates every series UID against the study tree (replacing the old `known_series`/`unknown` check) and raises `SelectionError` for unknown series or SOP UIDs, so no separate validation code remains.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test dicom_server.tests.test_bulk_retrieval -v 1`
Expected: PASS, including the untouched legacy tests.

- [ ] **Step 5: Run the full app test suite**

Run: `venv/bin/python manage.py test dicom_server`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dicom_server/views.py dicom_server/tests/test_bulk_retrieval.py
git commit -m "feat(dicom_server): accept instance-level RT selection in batch retrieve"
```

### Task 4: Ingest filter — drop unselected instances for partial-selection jobs

**Files:**
- Modify: `dicom_server/services/ingest.py` — imports, new helper, hook in `ingest_dataset` (~lines 120–145)
- Test: `dicom_server/tests/test_ingest.py`

**Interfaces:**
- Consumes: `constants.RT_DETAIL_MODALITIES` (Task 1); `RetrievalJobStudy.selected_sop_instance_uids` (Task 2); the existing `job_study` lookup in `ingest_dataset` (RUNNING job matching the study).
- Produces: `ingest._selection_reject_reason(job_study, series_uid, sop_uid, modality) -> str | None` — used only internally; behaviour contract: returns a reject reason or None per spec rule 4 (see "Spec (agreed design)" rule 4). Dropped instances get an `InboundDICOMInstance` audit row (status `REJECTED`) but the C-STORE wire status stays `0x0000` SUCCESS (a failure status would count as a failed sub-op and mark the retrieval job PARTIAL/FAILED).

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_ingest.py` (module already imports `tempfile`, `Path`, `override_settings`, `TestCase`, `ingest_dataset`, `make_test_dataset`, `SiteConfiguration`, `Patient`, `InboundDICOMInstance`; add these to the existing `from dicom_server.models import (...)` line: `RemoteDICOMNode, RetrievalJob, RetrievalJobStudy, RetrievalJobSeries`; add `from dicom_server.tests.utils import make_rt_dataset`):

```python
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class IngestSelectionFilterTests(TestCase):
    """Spec rule 4: partial-selection jobs drop unselected instances."""

    STUDY_UID = '1.2.3'

    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='T', center_name='T')
        self.patient = Patient.objects.create(patient_id='P1', gender='Male')
        Patient.objects.filter(pk=self.patient.pk).update(chavi_consent=True)
        self.patient.chavi_consent = True
        node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1')
        self.job = RetrievalJob.objects.create(
            node=node, patient=self.patient,
            status=RetrievalJob.Status.RUNNING,
        )

    def _job_study(self, series_uids=(), sop_uids=()):
        study = RetrievalJobStudy.objects.create(
            job=self.job, study_instance_uid=self.STUDY_UID)
        RetrievalJobSeries.objects.bulk_create([
            RetrievalJobSeries(study=study, series_instance_uid=s)
            for s in series_uids
        ])
        if sop_uids:
            study.selected_sop_instance_uids = list(sop_uids)
            study.save(update_fields=['selected_sop_instance_uids'])
        return study

    def _audit(self, sop_uid):
        return InboundDICOMInstance.objects.get(sop_instance_uid=sop_uid)

    def test_whole_study_job_accepts_everything(self):
        self._job_study()  # no series rows
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN',
            rt_plan_label='final_v2', approval_status='UNAPPROVED')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        self.assertEqual(self._audit('p2').status, 'STORED')

    def test_rt_instance_in_sop_set_stored(self):
        self._job_study(series_uids=['pl'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p1', modality='RTPLAN',
            rt_plan_label='final', approval_status='APPROVED')
        ingest_dataset(ds)
        self.assertEqual(self._audit('p1').status, 'STORED')

    def test_rt_instance_not_in_sop_set_dropped(self):
        self._job_study(series_uids=['pl'], sop_uids=['p1', 'ss1'])
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN',
            rt_plan_label='final_v2', approval_status='UNAPPROVED')
        result = ingest_dataset(ds)
        # Wire status stays SUCCESS (spec: must not count as failed sub-op).
        self.assertEqual(result.status, 0x0000)
        entry = self._audit('p2')
        self.assertEqual(entry.status, 'REJECTED')
        self.assertEqual(entry.reject_reason,
                         'Instance not selected in retrieval job')
        self.assertFalse(entry.file_path)

    def test_legacy_series_level_selection_accepts_rt_instances(self):
        # Empty SOP set = legacy/scheduled flow: series-level selection
        # behaves exactly as before the filter existed.
        self._job_study(series_uids=['pl'])  # no SOP set
        ds = make_rt_dataset(
            patient_id='P1', study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN')
        ingest_dataset(ds)
        self.assertEqual(self._audit('p2').status, 'STORED')

    def test_unselected_image_series_dropped(self):
        self._job_study(series_uids=['ct'], sop_uids=[])
        ds = make_test_dataset(
            patient_id='P1', study_uid=self.STUDY_UID, series_uid='ct2')
        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        entry = self._audit(ds.SOPInstanceUID)
        self.assertEqual(entry.status, 'REJECTED')
        self.assertEqual(entry.reject_reason,
                         'Series not selected in retrieval job')

    def test_selected_image_series_stored(self):
        self._job_study(series_uids=['ct'], sop_uids=[])
        ds = make_test_dataset(
            patient_id='P1', study_uid=self.STUDY_UID, series_uid='ct')
        ingest_dataset(ds)
        self.assertEqual(self._audit(ds.SOPInstanceUID).status, 'STORED')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python manage.py test dicom_server.tests.test_ingest.IngestSelectionFilterTests -v 2`
Expected: the drop tests FAIL (instances currently always stored), the accept tests may already pass.

- [ ] **Step 3: Implement the filter**

In `dicom_server/services/ingest.py`:

1. Imports — add after `from dicom_server.models import ...`:

```python
from dicom_server import constants
```

2. New module-level function, placed just above `def ingest_dataset(`:

```python
def _selection_reject_reason(job_study, series_uid, sop_uid, modality):
    """Reason to drop an instance arriving under a RUNNING job whose study
    has a partial (series-scoped) selection, or None to accept.

    - No series rows on the job study -> whole-study selection -> accept.
    - RT detail modality -> strict per-SOP filter, but only when the job
      stored a non-empty SOP set (interactive instance-level selection).
      An empty SOP set is a legacy/scheduled series-level selection ->
      accept (behaviour identical to before this filter existed).
    - Other modalities -> accept only if the series was selected.
    """
    selected_series = list(
        job_study.series.values_list('series_instance_uid', flat=True))
    if not selected_series:
        return None
    if (modality or '').upper() in constants.RT_DETAIL_MODALITIES:
        wanted = set(job_study.selected_sop_instance_uids or [])
        if wanted and sop_uid not in wanted:
            return 'Instance not selected in retrieval job'
        return None
    if series_uid not in selected_series:
        return 'Series not selected in retrieval job'
    return None
```

3. Hook in `ingest_dataset`. After the existing block

```python
    raw_patient_id = str(getattr(ds, 'PatientID', '') or '').strip()
    if not raw_patient_id:
        return reject(STATUS_MISSING_ATTRIBUTE, 'Missing PatientID')
    study_uid = str(getattr(ds, 'StudyInstanceUID', '') or '').strip()
    sop_uid = str(getattr(ds, 'SOPInstanceUID', '') or '').strip()
```

add:

```python
    series_uid = str(getattr(ds, 'SeriesInstanceUID', '') or '').strip()
```

Then, immediately after the consent check (`if not patient.chavi_consent: return reject(STATUS_NO_CONSENT, ...)`), insert:

```python
    # Selection filter (spec rule 4): a RUNNING job that selected only part
    # of the study drops instances the user did not ask for. The wire status
    # stays SUCCESS — the transfer succeeded; we simply chose not to persist.
    # (A failure status would count as a failed C-MOVE sub-op and mark the
    # retrieval job PARTIAL/FAILED.) Dropped instances still count in
    # job.instances_received; they are visible in the audit log below.
    if job_study is not None:
        reason = _selection_reject_reason(
            job_study, series_uid, sop_uid,
            modality=str(getattr(ds, 'Modality', '') or ''),
        )
        if reason:
            logger.info('Dropping unselected instance %s: %s', sop_uid, reason)
            InboundDICOMInstance.objects.create(
                status=InboundDICOMInstance.Status.REJECTED,
                reject_reason=reason[:255],
                matched_patient=patient, **log_fields,
            )
            return IngestResult(
                status=STATUS_SUCCESS, reason='dropped: ' + reason,
                patient=patient)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python manage.py test dicom_server.tests.test_ingest -v 1`
Expected: PASS (new + pre-existing ingest tests).

- [ ] **Step 5: Run the full app test suite**

Run: `venv/bin/python manage.py test dicom_server`
Expected: PASS — in particular the SCP loopback tests (they ingest without a RUNNING job → `job_study is None` → filter is a no-op).

- [ ] **Step 6: Commit**

```bash
git add dicom_server/services/ingest.py dicom_server/tests/test_ingest.py
git commit -m "feat(dicom_server): drop unselected instances at ingest for partial jobs"
```

---

### Task 5: End-to-end test — selection POST → job rows → ingest accept/drop

**Files:**
- Create: `dicom_server/tests/test_rt_instance_selection_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 2–4 (view contract, model field, ingest filter) — this task adds no production code; it locks the chain together and guards against the tasks drifting apart.

- [ ] **Step 1: Write the test file**

```python
"""End-to-end: instance-level selection -> job rows -> ingest filtering.

Chains BatchRetrieveView -> RetrievalJob/Study/Series -> ingest_dataset
accept/drop using the ARIA data shape: one RTPLAN series holding two plans
(one approved, one unapproved) plus struct-set and dose series.
"""
import json
import tempfile
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    InboundDICOMInstance, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient,
)
from dicom_server.services.ingest import ingest_dataset
from dicom_server.tests.utils import make_rt_dataset, make_test_dataset


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RtInstanceSelectionE2ETests(TestCase):
    STUDY_UID = '1.2.840.10008.5.1.4.199471.1.1'

    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital')
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1')
        cls.user = User.objects.create_user('qruser', password='pw')
        cls.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_server',
            codename__in=['add_retrievaljob', 'view_retrievaljob'],
        ))
        cls.patient = Patient.objects.create(
            patient_id='MR/25/004771', gender='Female')
        Patient.objects.filter(pk=cls.patient.pk).update(chavi_consent=True)
        cls.patient.chavi_consent = True

    def setUp(self):
        self.tree = [{
            'study_instance_uid': self.STUDY_UID, 'remote_patient_id': 'X',
            'study_date': '20250407', 'study_description': 'RT Planning CT',
            'series': [
                {'series_instance_uid': 'ct', 'series_description': 'CECT',
                 'modality': 'CT', 'series_number': 1, 'instances': 2},
                {'series_instance_uid': 'ss', 'modality': 'RTSTRUCT',
                 'series_number': 13, 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'ss1', 'structure_set_label':
                      'CT_FINAL', 'referenced_series_uids': ['ct']}]},
                {'series_instance_uid': 'pl', 'modality': 'RTPLAN',
                 'series_number': 14, 'instances': 2,
                 'rt_instances': [
                     {'sop_instance_uid': 'p1', 'rt_plan_label': 'final',
                      'approval_status': 'APPROVED',
                      'referenced_structure_set_uids': ['ss1']},
                     {'sop_instance_uid': 'p2', 'rt_plan_label': 'final_v2',
                      'approval_status': 'UNAPPROVED',
                      'referenced_structure_set_uids': ['ss1']}]},
                {'series_instance_uid': 'ds', 'modality': 'RTDOSE',
                 'series_number': 15, 'instances': 1,
                 'rt_instances': [
                     {'sop_instance_uid': 'd1',
                      'referenced_plan_uids': ['p1']}]},
            ],
        }]
        self.batch = RetrievalBatch.objects.create(
            node=self.node, status='AWAITING_SELECTION')
        RetrievalBatchPatient.objects.create(
            batch=self.batch, patient=self.patient, studies=self.tree)

    def _post_selection(self, **entry_overrides):
        entry = {'study_instance_uid': self.STUDY_UID}
        entry.update(entry_overrides)
        self.client.force_login(self.user)
        with mock.patch('dicom_server.views.chord') as mock_chord:
            mock_chord.return_value.return_value.id = 'chord-e2e'
            resp = self.client.post(
                reverse('dicom_server:batch_retrieve',
                        args=[self.batch.pk]),
                data=json.dumps({'selections': {
                    self.patient.patient_id: [entry],
                }}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        job = RetrievalJob.objects.get()
        job.status = RetrievalJob.Status.RUNNING
        job.save(update_fields=['status'])
        return job

    def _audit_status(self, sop_uid):
        entry = InboundDICOMInstance.objects.filter(
            sop_instance_uid=sop_uid).first()
        return entry.status if entry else None

    def test_select_only_approved_plan(self):
        job = self._post_selection(sop_instance_uids=['p1'])
        study = job.studies.get()
        self.assertEqual(study.selected_sop_instance_uids, ['p1', 'ss1'])
        self.assertEqual(
            sorted(study.series.values_list('series_instance_uid', flat=True)),
            ['ct', 'pl', 'ss'],
        )
        pid = self.patient.patient_id

        # Approved plan + its struct set + a CT slice: stored.
        self.assertEqual(ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
            sop_uid='p1', modality='RTPLAN', rt_plan_label='final',
            approval_status='APPROVED')).status, 0x0000)
        self.assertEqual(self._audit_status('p1'), 'STORED')
        self.assertEqual(ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ss',
            sop_uid='ss1', modality='RTSTRUCT',
            structure_set_label='CT_FINAL')).status, 0x0000)
        self.assertEqual(self._audit_status('ss1'), 'STORED')
        ct = make_test_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ct')
        ingest_dataset(ct)
        self.assertEqual(self._audit_status(ct.SOPInstanceUID), 'STORED')

        # Unapproved sibling plan in the SAME series: dropped.
        ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
            sop_uid='p2', modality='RTPLAN', rt_plan_label='final_v2',
            approval_status='UNAPPROVED'))
        self.assertEqual(self._audit_status('p2'), 'REJECTED')

        # Dose of the approved plan: not selected -> dropped.
        ingest_dataset(make_rt_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ds',
            sop_uid='d1', modality='RTDOSE'))
        self.assertEqual(self._audit_status('d1'), 'REJECTED')

        # Slice of an image series that was never selected: dropped.
        other = make_test_dataset(
            patient_id=pid, study_uid=self.STUDY_UID, series_uid='ct9')
        ingest_dataset(other)
        self.assertEqual(self._audit_status(other.SOPInstanceUID), 'REJECTED')

    def test_legacy_series_level_job_stores_all_plans_of_series(self):
        job = self._post_selection(series_uids=['pl'])
        self.assertEqual(job.studies.get().selected_sop_instance_uids, [])
        pid = self.patient.patient_id
        for sop in ('p1', 'p2'):
            ingest_dataset(make_rt_dataset(
                patient_id=pid, study_uid=self.STUDY_UID, series_uid='pl',
                sop_uid=sop, modality='RTPLAN'))
            self.assertEqual(self._audit_status(sop), 'STORED')

    def test_whole_study_job_stores_everything(self):
        self._post_selection(series_uids=None, sop_instance_uids=None)
        self.assertEqual(
            RetrievalJob.objects.get().studies.get()
            .selected_sop_instance_uids, [])
        ingest_dataset(make_rt_dataset(
            patient_id=self.patient.patient_id, study_uid=self.STUDY_UID,
            series_uid='pl', sop_uid='p2', modality='RTPLAN'))
        self.assertEqual(self._audit_status('p2'), 'STORED')
```

- [ ] **Step 2: Run the test**

Run: `venv/bin/python manage.py test dicom_server.tests.test_rt_instance_selection_e2e -v 2`
Expected: PASS (production code already exists from Tasks 2–4; if this fails, a previous task drifted — fix the production code or the earlier task's contract, not this test's expectations).

- [ ] **Step 3: Run the full app test suite**

Run: `venv/bin/python manage.py test dicom_server`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add dicom_server/tests/test_rt_instance_selection_e2e.py
git commit -m "test(dicom_server): e2e for instance-level selection through ingest"
```

### Task 6: Frontend — instance-level tree, selection, submit payload

**Files:**
- Modify: `templates/dicom_server/batch_select.html` (inline JS, ~lines 158–770)
- Test: `dicom_server/tests/test_bulk_retrieval.py` — `test_batch_select_page` (JS marker assertions)

**Interfaces:**
- Consumes: the study-tree JSON from `BatchStatusView` (shape per Global Constraints); the new `batch_retrieve` payload contract from Task 3.
- Produces: UI behaviour per spec rules 1–2. No server-visible interface beyond the Task 3 payload.

**JS identifier map** (all in the template's inline script):

| New | Replaces |
|---|---|
| `RT_DETAIL_MODS` (const array) | — (mirrors `constants.RT_DETAIL_MODALITIES`; RTREG/RTIMAGE stay series-level in the UI) |
| `studyIndex(study)` | — |
| `instanceTree(study)` | `seriesHierarchy(study)` |
| `allNodeIds(study)` | — |
| `nodeVisible(study, node, f)` | `seriesVisible(se, s, f)` |
| `instApproval(se, inst, idx)` | `planApprovalState(se)` |
| `nodeAncestors(study, id)` | `ancestorsOf(s, seuid)` |
| `nodeDescendants(study, id)` | `descendantsOf(s, seuid)` |
| `nodeSubRows(pid, s, f)` | `seriesSubRows(pid, s, f)` |
| `structDetail(s, inst)`, `doseDetail(s, inst)` | — |
| `findStudy(key)` | (inlines the duplicated lookup in the two check handlers) |
| checkbox class `.node-check` with `data-id` | `.se-check` with `data-seuid` |

Deleted outright (after their call sites move): `rtInstanceRows`, `approvalBadge`, `approvalVisible`, `seriesPassesApproval`, `seriesFilterActive`. **Keep** `rtInstanceLabel` and `rtDetailsCell` (used for fallback container rows) and `studyRtSummary`, `studyVisible`, `badge`, `selectStudy` (rewritten in Step 4).

Node id convention: `'s|<series_instance_uid>'` for series rows, `'i|<sop_instance_uid>'` for instance rows. The `sel` map value shape is unchanged (`'all' | Set`), only Set members change to node ids. Update the `sel` comment accordingly.

- [ ] **Step 1: Update the page-marker test (failing first)**

In `dicom_server/tests/test_bulk_retrieval.py`, `test_batch_select_page`, replace:

```python
        # RT detail rendering + labeled series sub-table are wired in the JS
        self.assertContains(resp, 'rt_instances')
        self.assertContains(resp, 'approvalBadge')
        self.assertContains(resp, 'sf-approval')
        self.assertContains(resp, 'parent_series_uids')
```

with:

```python
        # RT detail rendering + instance-level tree are wired in the JS
        self.assertContains(resp, 'rt_instances')
        self.assertContains(resp, 'instanceTree')
        self.assertContains(resp, 'node-check')
        self.assertContains(resp, 'sop_instance_uids')
        self.assertContains(resp, 'sf-approval')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test dicom_server.tests.test_bulk_retrieval.BulkRetrievalTestCase.test_batch_select_page -v 2`
Expected: FAIL (`instanceTree` not in response).

- [ ] **Step 3: Add the new core JS**

In `batch_select.html`, insert the following block immediately before the existing `/* ---------- selection ---------- */` comment (and delete the old `seriesHierarchy`, `rtInstanceRows`, `approvalBadge` functions wherever they sit — `rtInstanceLabel` and `rtDetailsCell` stay):

```js
/* ---------- instance-level tree (RT objects are selectable per instance) ----------
 * Node ids: 's|<series_uid>' | 'i|<sop_uid>'. Nesting follows DICOM
 * references: struct set -> its image series, plan -> its struct set,
 * dose -> its (single) plan. RT instances whose references do not resolve
 * within the study render under their own series row (fallback container).
 * RTREG/RTIMAGE stay series-level rows.
 */
const RT_DETAIL_MODS = ['RTSTRUCT', 'RTPLAN', 'RTDOSE'];

function studyIndex(study) {
  const bySeUid = {}, bySop = {};
  (study.series || []).forEach(function (se) {
    bySeUid[se.series_instance_uid] = se;
    (se.rt_instances || []).forEach(function (inst) {
      if (inst.sop_instance_uid) bySop[inst.sop_instance_uid] = {se: se, inst: inst};
    });
  });
  return {bySeUid: bySeUid, bySop: bySop};
}

function instanceTree(study) {
  const idx = studyIndex(study);
  const series = study.series || [];
  const rt = [];
  series.forEach(function (se) {
    if (!RT_DETAIL_MODS.includes((se.modality || '').toUpperCase())) return;
    (se.rt_instances || []).forEach(function (inst) {
      if (inst.sop_instance_uid) rt.push({se: se, inst: inst});
    });
  });
  const plansByStruct = {}, dosesByPlan = {};
  rt.forEach(function (x) {
    const m = (x.se.modality || '').toUpperCase();
    if (m === 'RTPLAN') (x.inst.referenced_structure_set_uids || []).forEach(function (u) {
      (plansByStruct[u] = plansByStruct[u] || []).push(x);
    });
    if (m === 'RTDOSE') (x.inst.referenced_plan_uids || []).forEach(function (u) {
      (dosesByPlan[u] = dosesByPlan[u] || []).push(x);
    });
  });
  function instName(x) {
    const m = (x.se.modality || '').toUpperCase();
    if (m === 'RTSTRUCT') return x.inst.structure_set_label || x.inst.structure_set_name || '(unnamed)';
    if (m === 'RTPLAN') return x.inst.rt_plan_label || x.inst.rt_plan_name || '(unnamed)';
    const p = (x.inst.referenced_plan_uids || []).map(function (u) { return idx.bySop[u]; }).filter(Boolean)[0];
    if (p) {
      const pn = p.inst.rt_plan_label || p.inst.rt_plan_name;
      if (pn) return 'dose — ' + pn;
    }
    return 'dose' + (x.inst.instance_number ? ' ' + x.inst.instance_number : '');
  }
  const out = [];
  const seen = new Set();
  function pushInst(x, depth, parentKey) {
    const id = 'i|' + x.inst.sop_instance_uid;
    if (seen.has(id)) return;
    seen.add(id);
    out.push({kind: 'instance', se: x.se, inst: x.inst, name: instName(x),
              depth: depth, parentKey: parentKey, id: id});
    (plansByStruct[x.inst.sop_instance_uid] || []).forEach(
      function (p) { pushInst(p, depth + 1, id); });
    (dosesByPlan[x.inst.sop_instance_uid] || []).forEach(
      function (d) { pushInst(d, depth + 1, id); });
  }
  series.forEach(function (se) {
    const m = (se.modality || '').toUpperCase();
    if (!RT_DETAIL_MODS.includes(m)) {
      out.push({kind: 'series', se: se, depth: 0, id: 's|' + se.series_instance_uid, parentKey: null});
      if (m !== 'RTREG' && m !== 'RTIMAGE') {
        rt.forEach(function (x) {
          if ((x.se.modality || '').toUpperCase() === 'RTSTRUCT' &&
              (x.inst.referenced_series_uids || []).includes(se.series_instance_uid)) {
            pushInst(x, 1, 's|' + se.series_instance_uid);
          }
        });
      }
      return;
    }
    const mine = rt.filter(function (x) {
      return x.se.series_instance_uid === se.series_instance_uid;
    });
    const orphan = mine.filter(function (x) {
      const mm = (x.se.modality || '').toUpperCase();
      if (mm === 'RTSTRUCT') return !(x.inst.referenced_series_uids || []).some(function (u) { return idx.bySeUid[u]; });
      if (mm === 'RTPLAN') return !(x.inst.referenced_structure_set_uids || []).some(function (u) { return idx.bySop[u]; });
      return !(x.inst.referenced_plan_uids || []).some(function (u) { return idx.bySop[u]; });
    });
    if (orphan.length) {
      out.push({kind: 'series', se: se, depth: 0, id: 's|' + se.series_instance_uid, parentKey: null});
      orphan.forEach(function (x) { pushInst(x, 1, 's|' + se.series_instance_uid); });
    }
  });
  return out;
}
function allNodeIds(study) {
  return instanceTree(study).map(function (n) { return n.id; });
}

/* ---------- visibility & approval (instance level) ---------- */
function instApproval(se, inst, idx) {
  /* 'approved' | 'unapproved' for one RT instance. Doses inherit their
     plan's verdict; a dose whose plan is unknown counts as unapproved so
     the filter never vouches for what it cannot verify. Struct sets have
     no approval — they always pass. */
  const m = (se.modality || '').toUpperCase();
  if (m === 'RTPLAN') return (inst.approval_status || '').toUpperCase() === 'APPROVED'
    ? 'approved' : 'unapproved';
  if (m === 'RTDOSE') {
    const p = (inst.referenced_plan_uids || []).map(function (u) { return idx.bySop[u]; }).filter(Boolean)[0];
    return p ? instApproval(p.se, p.inst, idx) : 'unapproved';
  }
  return 'approved';
}
function nodeVisible(study, node, f) {
  const idx = studyIndex(study);
  const mod = (node.se.modality || '').toUpperCase();
  if (f.mods.length && !f.mods.includes(mod)) return false;
  if (f.q) {
    const hay = node.kind === 'series'
      ? (node.se.series_description || '')
      : (node.name + ' ' + (node.se.series_description || ''));
    if (!hay.toLowerCase().includes(f.q)) return false;
  }
  if (f.approval && node.kind === 'instance' &&
      instApproval(node.se, node.inst, idx) !== f.approval) return false;
  return true;
}

/* ---------- ancestor / descendant closure over node ids ---------- */
function nodeAncestors(study, id) {
  if (id[0] === 's') return [];
  const idx = studyIndex(study);
  const hit = idx.bySop[id.slice(2)];
  if (!hit) return [];
  const m = (hit.se.modality || '').toUpperCase();
  const out = [];
  const addSop = function (u) {
    if (u && idx.bySop[u] && out.indexOf('i|' + u) === -1) {
      out.push('i|' + u);
      out.push.apply(out, nodeAncestors(study, 'i|' + u));
    }
  };
  if (m === 'RTDOSE') (hit.inst.referenced_plan_uids || []).forEach(addSop);
  else if (m === 'RTPLAN') (hit.inst.referenced_structure_set_uids || []).forEach(addSop);
  else if (m === 'RTSTRUCT') (hit.inst.referenced_series_uids || []).forEach(function (u) {
    if (idx.bySeUid[u] && out.indexOf('s|' + u) === -1) out.push('s|' + u);
  });
  return out;
}
function nodeDescendants(study, id) {
  const idx = studyIndex(study);
  const out = [];
  const addSop = function (u) {
    const nid = 'i|' + u;
    if (out.indexOf(nid) === -1) {
      out.push(nid);
      out.push.apply(out, nodeDescendants(study, nid));
    }
  };
  if (id[0] === 's') {
    const uid = id.slice(2);
    Object.keys(idx.bySop).forEach(function (u) {
      if ((idx.bySop[u].inst.referenced_series_uids || []).includes(uid)) addSop(u);
    });
  } else {
    const sop = id.slice(2);
    Object.keys(idx.bySop).forEach(function (u) {
      const x = idx.bySop[u];
      const m = (x.se.modality || '').toUpperCase();
      const refs = m === 'RTDOSE' ? (x.inst.referenced_plan_uids || [])
        : m === 'RTPLAN' ? (x.inst.referenced_structure_set_uids || [])
        : [];
      if (refs.includes(sop)) addSop(u);
    });
  }
  return out;
}
function findStudy(key) {
  const parts = key.split('|');
  let found = null;
  patientsData.forEach(function (p) {
    (p.studies || []).forEach(function (s) {
      if (p.patient_id === parts[0] && s.study_instance_uid === parts[1]) found = s;
    });
  });
  return found;
}
function structDetail(s, inst) {
  const idx = studyIndex(s);
  const on = (inst.referenced_series_uids || []).map(function (u) { return idx.bySeUid[u]; }).filter(Boolean);
  if (!on.length) return '<span class="text-gray-400">references missing</span>';
  return 'on ' + on.map(function (se) {
    return esc(se.series_description || ('series ' + se.series_number));
  }).join(', ');
}
function doseDetail(s, inst) {
  const idx = studyIndex(s);
  const p = (inst.referenced_plan_uids || []).map(function (u) { return idx.bySop[u]; }).filter(Boolean)[0];
  if (!p) return '<span class="text-gray-400">references missing</span>';
  const pn = p.inst.rt_plan_label || p.inst.rt_plan_name || 'plan ' + (p.inst.instance_number || '');
  return 'for ' + esc(pn);
}
```

- [ ] **Step 4: Rewrite selection state functions**

Replace `selectStudy`, `selCount`, and `updateSelCount` (and delete `seriesFilterActive`, `approvalVisible`, `seriesPassesApproval`, `planApprovalState`, `ancestorsOf`, `descendantsOf`, and the old `seriesVisible`):

```js
function selectStudy(pid, s, on) {
  const key = keyOf(pid, s.study_instance_uid);
  if (!on) { sel.delete(key); return; }
  const f = filters();
  if (!(f.mods.length || f.q.length || f.approval.length)) {
    sel.set(key, 'all');
    return;
  }
  const ids = new Set();
  instanceTree(s).forEach(function (n) {
    if (nodeVisible(s, n, f)) {
      ids.add(n.id);
      nodeAncestors(s, n.id).forEach(function (a) { ids.add(a); });
    }
  });
  if (ids.size) sel.set(key, ids);
}
function selCount() {
  let studies = 0, partial = 0, objects = 0;
  const pids = new Set();
  sel.forEach(function (v, k) {
    pids.add(k.split('|')[0]);
    studies++;
    const study = findStudy(k);
    const n = v === 'all' ? (study ? allNodeIds(study).length : 0) : v.size;
    if (v !== 'all') partial++;
    objects += n;
  });
  return {patients: pids.size, studies: studies, partial: partial, objects: objects};
}
function updateSelCount() {
  const c = selCount();
  $('#sel-count').text(
    c.patients + ' patients · ' + c.studies + ' studies' +
    (c.partial ? ' (' + c.partial + ' partial)' : '') + ' · ' +
    c.objects + ' objects selected');
}
```

Also update the `sel` declaration comment near the top of the script:

```js
const sel = new Map();       // 'pid|suid' -> 'all' | Set(node id: 's|…' | 'i|…')
```

- [ ] **Step 5: Replace the sub-table renderer**

Delete `seriesSubRows` and add:

```js
function nodeSubRows(pid, s, f) {
  const key = keyOf(pid, s.study_instance_uid);
  const v = sel.get(key);
  const rows = instanceTree(s).filter(function (n) { return nodeVisible(s, n, f); }).map(function (n) {
    const checked = v === 'all' || (v instanceof Set && v.has(n.id));
    const indent = n.depth ? ' style="padding-left:' + (8 + n.depth * 18) + 'px"' : '';
    const marker = n.depth ? '<span class="text-gray-300 mr-1">└</span>' : '';
    const mod = (n.se.modality || '').toUpperCase();
    let details = '<span class="text-gray-400">—</span>';
    if (n.kind === 'instance') {
      if (mod === 'RTPLAN') {
        const ok = (n.inst.approval_status || '').toUpperCase() === 'APPROVED';
        details = '<span class="' + (ok ? 'text-green-700 font-medium' : 'text-gray-500') + '">' +
          (ok ? 'approved' : 'unapproved') + '</span>';
      } else if (mod === 'RTDOSE') {
        details = doseDetail(s, n.inst);
      } else if (mod === 'RTSTRUCT') {
        details = structDetail(s, n.inst);
      }
    } else if (RT_DETAIL_MODS.includes(mod)) {
      /* Fallback container row (unresolved references): keep the existing
         aggregate details. */
      details = rtDetailsCell(n.se);
    }
    const name = n.kind === 'series' ? (n.se.series_description || '(no description)') : n.name;
    return '<tr class="text-xs">' +
      '<td class="px-2 py-1"><input type="checkbox" class="node-check h-4 w-4 text-chavi-primary border-gray-300 rounded focus:ring-chavi-primary" data-key="' + esc(key) + '" data-id="' + esc(n.id) + '"' + (checked ? ' checked' : '') + '></td>' +
      '<td class="px-2 py-1"' + indent + '>' + marker + esc(name) + '</td>' +
      '<td class="px-2 py-1">' + esc(mod || '—') + '</td>' +
      '<td class="px-2 py-1">' + esc(n.se.series_number == null ? '—' : n.se.series_number) + '</td>' +
      '<td class="px-2 py-1">' + esc(dcmDate(n.se.series_date) || '—') + '</td>' +
      '<td class="px-2 py-1 text-right">' + (n.kind === 'series' ? (n.se.instances == null ? '?' : n.se.instances) : '1') + '</td>' +
      '<td class="px-2 py-1">' + details + '</td></tr>';
  }).join('');
  const head = '<thead><tr class="text-xs text-gray-400 uppercase">' +
    '<th class="px-2 py-1 w-6"></th>' +
    '<th class="px-2 py-1 text-left font-medium">Description</th>' +
    '<th class="px-2 py-1 text-left font-medium">Modality</th>' +
    '<th class="px-2 py-1 text-left font-medium">Series #</th>' +
    '<th class="px-2 py-1 text-left font-medium">Date</th>' +
    '<th class="px-2 py-1 text-right font-medium">Instances</th>' +
    '<th class="px-2 py-1 text-left font-medium">Details</th>' +
    '</tr></thead>';
  return '<tr class="bg-gray-50"><td></td><td colspan="8" class="px-4 py-2">' +
    '<table class="w-full">' + head + '<tbody>' + rows +
    (rows ? '' : '<tr><td colspan="7" class="px-2 py-1 text-gray-400 text-xs">No objects match the filters.</td></tr>') +
    '</tbody></table></td></tr>';
}
```

In `renderStudies`, change the call site:

```js
            if (exp && nser) rows.push(seriesSubRows(pid, s, f));
```

to:

```js
            if (exp && nser) rows.push(nodeSubRows(pid, s, f));
```

Also, in `studyVisible`, extend the query match to RT instance labels (so searching a plan name finds the study):

```js
    if (f.q) {
      const studyMatch = ((s.study_description || '') + ' ' + (s.accession_number || ''))
        .toLowerCase().includes(f.q);
      const anySeries = (s.series || []).some(
          se => (se.series_description || '').toLowerCase().includes(f.q) ||
            (se.rt_instances || []).some(i =>
              ((i.structure_set_label || '') + ' ' + (i.structure_set_name || '') +
               ' ' + (i.rt_plan_label || '') + ' ' + (i.rt_plan_name || ''))
              .toLowerCase().includes(f.q)));
      if (!studyMatch && !anySeries) return false;
    }
```

(replacing the old `anySeries` computation).

- [ ] **Step 6: Replace the row-checkbox handler**

Delete the `$(document).on('change', '.se-check', ...)` handler and the inline study-lookup boilerplate in the `.st-check` handler (use `findStudy`), and add:

```js
$(document).on('change', '.node-check', function () {
  const key = $(this).data('key');
  const id = $(this).data('id');
  const study = findStudy(key);
  let v = sel.get(key);
  if (v === 'all' || v === undefined) v = new Set(study ? allNodeIds(study) : []);
  if (this.checked) {
    v.add(id);
    if (study) nodeAncestors(study, id).forEach(function (a) { v.add(a); });
  } else {
    v.delete(id);
    if (study) nodeDescendants(study, id).forEach(function (d) { v.delete(d); });
  }
  if (v.size) sel.set(key, v); else sel.delete(key);
  renderStudies();
});
```

and simplify the `.st-check` handler's body to:

```js
$(document).on('change', '.st-check', function () {
  const study = findStudy(this.dataset.key);
  const pid = this.dataset.key.split('|')[0];
  if (study) selectStudy(pid, study, this.checked);
  renderStudies();
});
```

- [ ] **Step 7: Update the submit payload**

In the `#btn-retrieve` click handler, replace the selection-serialization block:

```js
  const selections = {};
  sel.forEach(function (v, key) {
    const [pid, suid] = key.split('|');
    (selections[pid] = selections[pid] || []).push({
      study_instance_uid: suid,
      series_instance_uids: v === 'all' ? null : [...v],
    });
  });
```

with:

```js
  const selections = {};
  sel.forEach(function (v, key) {
    const [pid, suid] = key.split('|');
    const entry = {study_instance_uid: suid};
    if (v === 'all') {
      entry.series_uids = null;
      entry.sop_instance_uids = null;
    } else {
      const su = [], sp = [];
      v.forEach(function (id) {
        if (id[0] === 's') su.push(id.slice(2)); else sp.push(id.slice(2));
      });
      entry.series_uids = su.length ? su : null;
      entry.sop_instance_uids = sp.length ? sp : null;
    }
    (selections[pid] = selections[pid] || []).push(entry);
  });
```

- [ ] **Step 8: Run the test suite**

Run: `venv/bin/python manage.py test dicom_server`
Expected: PASS (page-marker assertions now match the new JS; no other test reads the removed functions).

- [ ] **Step 9: Manual QA in a browser** (needs a running app + a query batch that has at least one RT study; the ARIA patient `46e44ebd.865c.4364.9d64.b26dae3bd430` from the original screenshot is the reference case)

1. Open the batch selection page, expand the "RT Planning CT" study. Verify the rows render as:
   - `CECT` (CT, #3, 196)
   - `└ CT_FINAL` (RTSTRUCT, #13, details `on CECT`)
   - `└ final` (RTPLAN, #18, details `approved` as plain green text — **no pill badge**)
   - `└ dose — final` (RTDOSE, #19, details `for final`)
   The bare name `final` appears exactly once; there is no `ARIA RadOnc Plans`-style series row and no duplicate sub-row.
2. Check the `final` plan row → the `CT_FINAL` and `CECT` checkboxes become checked. Uncheck `CT_FINAL` → the plan row and its dose row uncheck.
3. Set the approval filter to "Approved" → unapproved plan rows (and their doses) disappear; CT/struct rows remain visible.
4. With a study containing multiple plans in one RTPLAN series (create via a test batch or DevTools-edit the polled `patientsData`): each plan renders under its struct set, each with its own dose beneath it.
5. Select the approved plan chain, click "Retrieve selected", and inspect the POST body in DevTools: the study entry must contain `sop_instance_uids` (plan + struct SOP UIDs) and `series_uids` (CT + struct + plan series UIDs), and must NOT contain the dose series unless a dose was selected.
6. After the job finishes: confirm the unselected sibling plan (if any) was not stored (its SOP file absent from `media/processed_dicom/...`) and that `InboundDICOMInstance` shows `REJECTED` rows with reject_reason `Instance not selected in retrieval job`.

- [ ] **Step 10: Commit**

```bash
git add templates/dicom_server/batch_select.html dicom_server/tests/test_bulk_retrieval.py
git commit -m "feat(dicom_server): instance-level RT tree + selection in batch select UI"
```

---

## Self-Review (run before executing)

**Spec coverage:**
- Rule 1 (display) → Task 6 (Steps 3, 5). Rule 2 (selection + ancestor pull + cascade) → Task 6 (Steps 4, 6) server side Task 3. Rule 3 (series-level retrieval, server-side closure) → Task 1 (`normalize_selection`) + Task 3; `tasks.py`/`qr_client.py` retrieval untouched by design. Rule 4 (ingest filter) → Task 4. Rule 5 (unchanged flows) → guarded by the untouched legacy tests in Task 3 (`test_batch_retrieve_creates_jobs_and_chord`, `test_batch_retrieve_rejects_unknown_uids`) and Task 5 (`test_legacy_series_level_job_stores_all_plans_of_series`, `test_whole_study_job_stores_everything`); `bulk_selection.py` is never modified. Rule 6 (limitation) → code comments in Task 3/4 + spec text.
- Placeholder scan: none — every step carries concrete code/test content.
- Type/name consistency: `normalize_selection` returns `{'series_uids', 'sop_uids'}` (Task 1) and is consumed with exactly those keys (Task 3); `selected_sop_instance_uids` is the same JSONField name in Tasks 2, 3, 4, 5; `constants.RT_DETAIL_MODALITIES` (Task 1) is consumed by Tasks 1 (qr_client) and 4; JS node ids `'s|…'/'i|…'` are produced (Task 6 Step 3), consumed by selection (Step 4), events (Step 6) and submit (Step 7), and match the Task 3 payload split.

**Known out-of-scope (do not implement):** SOP-level C-MOVE/C-GET, IMAGE-level capability probing in `probe_qr_capabilities`, per-series "dropped" counts in the job detail UI, instance-level filters for the scheduled bulk flow (`bulk_selection.py` stays series-level; its jobs get an empty SOP set and keep legacy ingest behaviour), RTREG/RTIMAGE instance drill-down. Note (accepted behaviour change): unchecking an image series no longer cascades to RTREG/RTIMAGE series rows — they remain individually selectable root rows; the spec rule 2 cascade applies to the RTSTRUCT/RTPLAN/RTDOSE reference chain.
