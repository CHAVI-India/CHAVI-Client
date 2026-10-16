# RetrievalJob Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize `RetrievalJob`'s JSON fields into proper `RetrievalJobStudy` / `RetrievalJobSeries` child models so that `ingest_dataset` can authoritatively resolve the target patient from the running job instead of re-deriving it via `find_patient`.

**Architecture:** Replace four JSON fields (`study_uids`, `selections`, `item_results`, `studies_found`) on `RetrievalJob` with two child models that maintain the Patient → Study → Series hierarchy. The retrieval task writes work items as related rows; `ingest_dataset` queries `RetrievalJobStudy` by `study_instance_uid` + `job__status='RUNNING'` to get the authoritative patient.

**Tech Stack:** Django 5.x, PostgreSQL, pynetdicom, Celery

## Global Constraints

- The SCP runs as a separate process (`python -m dicom_server`) — cross-process communication is via the database only.
- `ingest_dataset` must never raise (it runs in a pynetdicom association thread).
- C-FIND metadata (study\_date, description, modalities) must survive the refactor for the job detail template.
- `instances_received` remains a denormalized counter on `RetrievalJob` (used in list views, dashboard, batch summaries).
- Existing test suite (207 tests) must pass at the end of each task.

---

## File Structure


| File                                      | Responsibility                                                                                                                           |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `dicom_server/models.py`                  | Add `RetrievalJobStudy`, `RetrievalJobSeries`; remove JSON fields from `RetrievalJob`                                                    |
| `dicom_server/tasks.py`                   | Rewrite `_job_work_items`, `_run_job_retrieval`, `_auto_retrieve_patient_node`, `task_bulk_schedule_finalize_query` to use new relations |
| `dicom_server/views.py`                   | Update `RetrievalJobDetailView`, `BatchRetrieveView` to create/read new relations                                                        |
| `dicom_server/services/bulk_selection.py` | `build_selections_for_patient` returns data shaped for `RetrievalJobStudy`/`RetrievalJobSeries` creation                                 |
| `dicom_server/services/ingest.py`         | `ingest_dataset` queries running job for patient resolution                                                                              |
| `dicom_server/admin.py`                   | Update admin for new models                                                                                                              |
| `templates/dicom_server/job_detail.html`  | Iterate `job.studies` instead of `job.studies_found` JSON                                                                                |
| `dicom_server/tests/*.py`                 | Update all test fixtures and assertions                                                                                                  |


---

### Task 1: Add `RetrievalJobStudy` and `RetrievalJobSeries` models

**Files:**

- Modify: `dicom_server/models.py`
- Test: `dicom_server/tests/test_job_models.py` (new)

**Interfaces:**

- Produces: `RetrievalJobStudy` model with fields: `job` (FK), `study_instance_uid`, `remote_patient_id`, `study_date`, `study_description`, `modalities`, `accession_number`, `status`, `completed`, `failed`, `warning`
- Produces: `RetrievalJobSeries` model with fields: `study` (FK to RetrievalJobStudy), `series_instance_uid`, `series_description`, `modality`, `series_date`, `status`, `completed`, `failed`, `warning`
- Produces: `RetrievalJob.studies` related\_name for querying child studies

- [ ] **Step 1: Write the failing test**

```python
# dicom_server/tests/test_job_models.py
from django.test import TestCase
from client_app.models import Patient, SiteConfiguration
from dicom_server.models import (
    RetrievalJob, RetrievalJobStudy, RetrievalJobSeries, RemoteDICOMNode,
)


class RetrievalJobStudyTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='T', center_name='T')
        self.patient = Patient.objects.create(patient_id='P1', gender='M')
        self.node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1',
        )

    def test_create_study_and_series(self):
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient,
        )
        study = RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='1.2.3',
            remote_patient_id='REMOTE1',
            study_date=None, study_description='CT Head',
            modalities='CT',
        )
        series = RetrievalJobSeries.objects.create(
            study=study, series_instance_uid='4.5.6',
            series_description='Series 1', modality='CT',
        )
        self.assertEqual(job.studies.count(), 1)
        self.assertEqual(study.series.count(), 1)
        self.assertEqual(study.job.patient, self.patient)

    def test_unique_constraint(self):
        from django.db import IntegrityError
        from django.db.transaction import atomic
        job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        RetrievalJobStudy.objects.create(job=job, study_instance_uid='1.2.3')
        with self.assertRaises(IntegrityError):
            with atomic():
                RetrievalJobStudy.objects.create(job=job, study_instance_uid='1.2.3')

    def test_query_by_study_uid_and_running_status(self):
        """This is the query ingest_dataset will use."""
        job = RetrievalJob.objects.create(
            node=self.node, patient=self.patient, status=RetrievalJob.Status.RUNNING,
        )
        RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='9.9.9',
        )
        result = RetrievalJobStudy.objects.filter(
            study_instance_uid='9.9.9',
            job__status=RetrievalJob.Status.RUNNING,
        ).select_related('job__patient').first()
        self.assertIsNotNone(result)
        self.assertEqual(result.job.patient, self.patient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test dicom_server.tests.test_job_models --noinput --keepdb`
Expected: FAIL — `cannot import name 'RetrievalJobStudy'`

- [ ] **Step 3: Add the models**

Add to `dicom_server/models.py` (after the `RetrievalJob` class):

```python
class RetrievalJobStudy(models.Model):
    """One study targeted by a retrieval job. Carries C-FIND metadata and
    retrieval outcome so the job detail view and ingest can use it."""
    job = models.ForeignKey(
        RetrievalJob, on_delete=models.CASCADE, related_name='studies',
    )
    study_instance_uid = models.CharField(max_length=255)
    remote_patient_id = models.CharField(max_length=255, null=True, blank=True)
    # C-FIND metadata
    study_date = models.DateField(null=True, blank=True)
    study_description = models.CharField(max_length=255, null=True, blank=True)
    accession_number = models.CharField(max_length=255, null=True, blank=True)
    # Retrieval outcome (populated by _run_job_retrieval)
    status = models.CharField(max_length=20, null=True, blank=True)
    completed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    warning = models.IntegerField(default=0)

    class Meta:
        unique_together = ['job', 'study_instance_uid']
        ordering = ['study_instance_uid']

    def __str__(self):
        return f'{self.job_id} / {self.study_instance_uid[:20]}'


class RetrievalJobSeries(models.Model):
    """One series targeted within a RetrievalJobStudy. Empty set = whole study."""
    study = models.ForeignKey(
        RetrievalJobStudy, on_delete=models.CASCADE, related_name='series',
    )
    series_instance_uid = models.CharField(max_length=255)
    # C-FIND metadata
    series_description = models.CharField(max_length=255, null=True, blank=True)
    modality = models.CharField(max_length=16, null=True, blank=True)
    series_date = models.DateField(null=True, blank=True)
    # Retrieval outcome
    status = models.CharField(max_length=20, null=True, blank=True)
    completed = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    warning = models.IntegerField(default=0)

    class Meta:
        unique_together = ['study', 'series_instance_uid']
        ordering = ['series_instance_uid']

    def __str__(self):
        return f'{self.study_id} / {self.series_instance_uid[:20]}'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python manage.py test dicom_server.tests.test_job_models --noinput --keepdb`
Expected: PASS

- [ ] **Step 5: Create migration and commit**

```bash
venv/bin/python manage.py makemigrations dicom_server
git add dicom_server/models.py dicom_server/migrations/ dicom_server/tests/test_job_models.py
git commit -m "feat(dicom_server): add RetrievalJobStudy and RetrievalJobSeries models"
```

---

### Task 2: Update `tasks.py` to write new relations

**Files:**

- Modify: `dicom_server/tasks.py:44-165` (`_job_work_items`, `_run_job_retrieval`)
- Modify: `dicom_server/tasks.py:460-510` (`_auto_retrieve_patient_node`)
- Modify: `dicom_server/tasks.py:720-745` (`task_bulk_schedule_finalize_query`)
- Test: `dicom_server/tests/test_job_models.py` (extend)

**Interfaces:**

- Consumes: `RetrievalJobStudy`, `RetrievalJobSeries` from Task 1
- Produces: `_job_work_items(job)` returns `list[RetrievalJobStudy]` (ordered) instead of `list[dict]` or `None`. Returns empty list when job is None or has no studies.
- Produces: `_run_job_retrieval` updates `RetrievalJobStudy.status/completed/failed/warning` and `RetrievalJobSeries.status/completed/failed/warning` in-place after each C-MOVE/C-GET call.

- [ ] **Step 1: Write the failing test for `_job_work_items`**

```python
# Add to dicom_server/tests/test_job_models.py

class JobWorkItemsTests(TestCase):
    def setUp(self):
        SiteConfiguration.objects.create(chavi_center_id='T', center_name='T')
        self.patient = Patient.objects.create(patient_id='P1', gender='M')
        self.node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1',
        )

    def test_returns_studies_with_series(self):
        from dicom_server.tasks import _job_work_items
        job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        study = RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='1.1', remote_patient_id='REM',
        )
        RetrievalJobSeries.objects.create(study=study, series_instance_uid='s1')
        RetrievalJobSeries.objects.create(study=study, series_instance_uid='s2')
        study2 = RetrievalJobStudy.objects.create(
            job=job, study_instance_uid='2.2', remote_patient_id='REM',
        )
        items = _job_work_items(job)
        self.assertEqual(len(items), 4)  # 2 series + 1 whole study
        uids = [(i['study_instance_uid'], i['series_instance_uid']) for i in items]
        self.assertIn(('1.1', 's1'), uids)
        self.assertIn(('1.1', 's2'), uids)
        self.assertIn(('2.2', None), uids)

    def test_empty_job_returns_empty_list(self):
        from dicom_server.tasks import _job_work_items
        job = RetrievalJob.objects.create(node=self.node, patient=self.patient)
        self.assertEqual(_job_work_items(job), [])

    def test_none_job_returns_empty_list(self):
        from dicom_server.tasks import _job_work_items
        self.assertEqual(_job_work_items(None), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test dicom_server.tests.test_job_models.JobWorkItemsTests --noinput --keepdb`
Expected: FAIL — `_job_work_items` still reads JSON fields

- [ ] **Step 3: Rewrite `_job_work_items`**

Replace the function in `dicom_server/tasks.py`:

```python
def _job_work_items(job):
    """Flatten a job's study/series relations into per-series work items.

    Returns a list of dicts:
      [{'study_instance_uid': str, 'series_instance_uid': str|None,
        'remote_patient_id': str|None}]

    A study with no series rows yields one item with series_instance_uid=None
    (meaning "whole study"). Returns [] when job is None or has no studies."""
    if job is None:
        return []
    flat = []
    for study in job.studies.prefetch_related('series').order_by('study_instance_uid'):
        remote_pid = study.remote_patient_id
        if study.series.exists():
            for s in study.series.order_by('series_instance_uid'):
                flat.append({
                    'study_instance_uid': study.study_instance_uid,
                    'series_instance_uid': s.series_instance_uid,
                    'remote_patient_id': remote_pid,
                })
        else:
            flat.append({
                'study_instance_uid': study.study_instance_uid,
                'series_instance_uid': None,
                'remote_patient_id': remote_pid,
            })
    return flat
```

- [ ] **Step 4: Rewrite `_run_job_retrieval` to update study/series rows**

The key changes:

- Remove the `item_results = []` list accumulation
- After each C-MOVE/C-GET, update the corresponding `RetrievalJobStudy` (and `RetrievalJobSeries` if applicable) row
- For the C-FIND-all path (no pre-existing studies), create `RetrievalJobStudy` rows from the C-FIND results before the retrieval loop
- Replace `_job_update(item_results=...)` with updating the related rows

```python
def _run_job_retrieval(job, node, patient, task_run=None, patient_id_aliases=None):
    """Retrieve all of a job's requested items via C-MOVE/C-GET.
    Updates RetrievalJobStudy/Series rows with outcome. Returns
    {'studies': [item results], 'instances_completed': n, 'status': ...}."""

    def _job_update(**fields):
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
            job.save()

    # If no studies are pre-registered, run C-FIND and create them
    if job and not job.studies.exists():
        _update_task_run(task_run, None, 10, 100, description='Querying studies (C-FIND)')
        found = qr_client.find_studies_for_patient(node, patient, patient_id_aliases)
        for s in found:
            RetrievalJobStudy.objects.create(
                job=job,
                study_instance_uid=s['study_instance_uid'],
                remote_patient_id=s.get('remote_patient_id'),
                study_date=_parse_dicom_date(s.get('study_date')),
                study_description=s.get('study_description'),
                modalities=s.get('modalities'),
                accession_number=s.get('accession_number'),
            )

    flat = _job_work_items(job)
    total = len(flat)
    instances = 0
    item_results = []  # still returned in result dict for API compat

    for i, target in enumerate(flat):
        study_uid = target['study_instance_uid']
        series_uid = target['series_instance_uid']
        remote_pid = target['remote_patient_id'] or patient.patient_id
        _update_task_run(
            task_run, None, 10 + int(80 * i / max(total, 1)), 100,
            description=f'Retrieving {i + 1}/{total}',
        )
        try:
            if node.prefer_c_get:
                stats = (
                    qr_client.get_series(node, study_uid, series_uid, remote_pid)
                    if series_uid else
                    qr_client.get_study(node, study_uid, remote_pid)
                )
            else:
                stats = (
                    qr_client.move_series(node, study_uid, series_uid, remote_pid)
                    if series_uid else
                    qr_client.move_study(node, study_uid, remote_pid)
                )
        except qr_client.QRModelNotAcceptedError as e:
            logger.error('Retrieve method not supported by %s: %s', node, e)
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            # Mark all remaining as failed
            for remaining in flat[i:]:
                _mark_item_failed(job, remaining['study_instance_uid'],
                                  remaining['series_instance_uid'], str(e))
                item_results.append({
                    'study_instance_uid': remaining['study_instance_uid'],
                    'series_instance_uid': remaining['series_instance_uid'],
                    **stats,
                })
            break
        except Exception as e:
            logger.exception('Retrieval of %s/%s failed', study_uid, series_uid)
            stats = {'status': None, 'completed': 0, 'failed': -1, 'error': str(e)}
            _mark_item_failed(job, study_uid, series_uid, str(e))

        _mark_item_done(job, study_uid, series_uid, stats)
        item_results.append({
            'study_instance_uid': study_uid,
            'series_instance_uid': series_uid,
            **stats,
        })
        instances += stats.get('completed', 0)

    failed = sum(1 for s in item_results if s['failed'])
    if total == 0 or failed == 0:
        final = RetrievalJob.Status.SUCCESS
    elif failed < total:
        final = RetrievalJob.Status.PARTIAL
    else:
        final = RetrievalJob.Status.FAILED

    result = {'studies': item_results, 'instances_completed': instances, 'status': final}
    _job_update(
        status=final, instances_received=instances,
        completed_at=timezone.now(),
        error_log='' if failed == 0 else str(item_results),
    )
    return result


def _mark_item_done(job, study_uid, series_uid, stats):
    """Update the RetrievalJobStudy (and Series if applicable) with outcome."""
    if job is None:
        return
    qs = job.studies.filter(study_instance_uid=study_uid)
    if series_uid:
        # Update at series level; roll up to study after all series done
        RetrievalJobSeries.objects.filter(
            study__job=job, study__study_instance_uid=study_uid,
            series_instance_uid=series_uid,
        ).update(
            status='done',
            completed=stats.get('completed', 0),
            failed=stats.get('failed', 0),
            warning=stats.get('warning', 0),
        )
    else:
        qs.update(
            status='done',
            completed=stats.get('completed', 0),
            failed=stats.get('failed', 0),
            warning=stats.get('warning', 0),
        )


def _mark_item_failed(job, study_uid, series_uid, error):
    if job is None:
        return
    if series_uid:
        RetrievalJobSeries.objects.filter(
            study__job=job, study__study_instance_uid=study_uid,
            series_instance_uid=series_uid,
        ).update(status='failed', failed=1)
    else:
        job.studies.filter(study_instance_uid=study_uid).update(
            status='failed', failed=1,
        )


def _parse_dicom_date(value):
    """Parse a DICOM date string (YYYYMMDD) to date or None."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y%m%d').date()
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 5: Update `_auto_retrieve_patient_node` to create `RetrievalJobStudy` rows**

Replace the job creation block:

```python
    # Create job + study rows with the remote_patient_id from C-FIND
    job = RetrievalJob.objects.create(
        node=node, patient=patient, created_by=None,
    )
    remote_pid_by_uid = {
        s['study_instance_uid']: s.get('remote_patient_id')
        for s in studies if s.get('study_instance_uid')
    }
    RetrievalJobStudy.objects.bulk_create([
        RetrievalJobStudy(
            job=job, study_instance_uid=uid,
            remote_patient_id=remote_pid_by_uid.get(uid),
        )
        for uid in sorted(unknown_uids)
    ])
```

- [ ] **Step 6: Update `task_bulk_schedule_finalize_query` to create study/series rows**

Replace the job creation block (around line 730-742):

```python
        entries = bulk_selection.build_selections_for_patient(
            row.studies or [], criteria, new_only=new_only,
        )
        if not entries:
            continue
        job = RetrievalJob.objects.create(
            node=batch.node, patient=row.patient,
            created_by=batch.created_by, batch=batch,
        )
        # Create study + series rows
        study_rows = []
        for entry in entries:
            suid = entry['study_instance_uid']
            study = RetrievalJobStudy(
                job=job, study_instance_uid=suid,
                remote_patient_id=entry.get('remote_patient_id'),
            )
            study_rows.append(study)
        RetrievalJobStudy.objects.bulk_create(study_rows)
        # Link series
        for entry in entries:
            suid = entry['study_instance_uid']
            series_uids = entry.get('series_instance_uids')
            if series_uids:
                job_study = job.studies.get(study_instance_uid=suid)
                RetrievalJobSeries.objects.bulk_create([
                    RetrievalJobSeries(study=job_study, series_instance_uid=suid2)
                    for suid2 in series_uids
                ])
        # Store studies_found metadata (C-FIND data for display)
        chosen_uids = {e['study_instance_uid'] for e in entries}
        found_subset = [
            s for s in (row.studies or [])
            if s.get('study_instance_uid') in chosen_uids
        ]
        _populate_study_metadata(job, found_subset)
        row.selected = True
        row.job = job
        row.save(update_fields=['selected', 'job'])
```

Add helper:

```python
def _populate_study_metadata(job, found_list):
    """Copy C-FIND metadata from the found-list dicts onto job study rows."""
    for found in found_list:
        suid = found.get('study_instance_uid')
        if not suid:
            continue
        RetrievalJobStudy.objects.filter(
            job=job, study_instance_uid=suid,
        ).update(
            study_date=_parse_dicom_date(found.get('study_date')),
            study_description=found.get('study_description'),
            modalities=found.get('modalities'),
            accession_number=found.get('accession_number'),
        )
        # Series metadata
        for se in (found.get('series') or []):
            RetrievalJobSeries.objects.filter(
                study__job=job, study__study_instance_uid=suid,
                series_instance_uid=se.get('series_instance_uid', ''),
            ).update(
                series_description=se.get('series_description'),
                modality=se.get('modality'),
                series_date=_parse_dicom_date(se.get('series_date')),
            )
```

- [ ] **Step 7: Run all dicom\_server tests**

Run: `venv/bin/python manage.py test dicom_server --noinput --keepdb`
Expected: Some tests will fail (they still use old JSON field assertions). Note which ones for Task 6.

- [ ] **Step 8: Commit**

```bash
git add dicom_server/tasks.py
git commit -m "feat(dicom_server): rewrite retrieval tasks to use job study/series relations"
```

---

### Task 3: Update `ingest.py` to resolve patient from running job

**Files:**

- Modify: `dicom_server/services/ingest.py:85-155` (`ingest_dataset`)
- Test: `dicom_server/tests/test_cmove_patient_id.py` (extend)

**Interfaces:**

- Consumes: `RetrievalJobStudy` (Task 1), `RetrievalJob.Status.RUNNING`
- Produces: `ingest_dataset` resolves patient from the running job first; falls back to `find_patient` only for unsolicited C-STOREs

- [ ] **Step 1: Write the failing test**

```python
# Add to dicom_server/tests/test_cmove_patient_id.py

    def test_ingest_uses_running_job_patient_not_find_patient(self):
        """When a RUNNING job exists for the study, ingest uses that job's
        patient directly — even if find_patient would resolve differently."""
        from dicom_server.services.ingest import ingest_dataset
        from dicom_server.models import RetrievalJob, RetrievalJobStudy

        # Create a second patient that find_patient might match
        other_patient = Patient.objects.create(patient_id='xx_12345', gender='F')
        Patient.objects.filter(pk=other_patient.pk).update(chavi_consent=True)

        # The running job says this study belongs to self.patient (MR/xx/12345)
        node = RemoteDICOMNode.objects.create(
            name='n', ae_title='TEST', host='127.0.0.1',
        )
        job = RetrievalJob.objects.create(
            node=node, patient=self.patient, status=RetrievalJob.Status.RUNNING,
        )

        ds = make_test_dataset(patient_id='xx_12345')
        RetrievalJobStudy.objects.create(
            job=job, study_instance_uid=ds.StudyInstanceUID,
            remote_patient_id='xx_12345',
        )

        result = ingest_dataset(ds)
        self.assertEqual(result.status, 0x0000)
        # File should be stored under the JOB's patient, not the other one
        self.assertEqual(result.patient, self.patient)

        # Verify the file on disk has the job's patient ID
        from pydicom import dcmread
        ds_disk = dcmread(result.file_path)
        self.assertEqual(ds_disk.PatientID, self.patient.patient_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python manage.py test dicom_server.tests.test_cmove_patient_id.CMovePatientIDFlowTests.test_ingest_uses_running_job_patient_not_find_patient --noinput --keepdb`
Expected: FAIL — `find_patient('xx_12345')` matches the other patient (exact match, Stage 1)

- [ ] **Step 3: Update `ingest_dataset`**

In `dicom_server/services/ingest.py`, replace the patient resolution block:

```python
    raw_patient_id = str(getattr(ds, 'PatientID', '') or '').strip()
    if not raw_patient_id:
        return reject(STATUS_MISSING_ATTRIBUTE, 'Missing PatientID')
    study_uid = str(getattr(ds, 'StudyInstanceUID', '') or '').strip()
    sop_uid = str(getattr(ds, 'SOPInstanceUID', '') or '').strip()
    if not study_uid or not sop_uid:
        return reject(STATUS_MISSING_ATTRIBUTE, 'Missing StudyInstanceUID or SOPInstanceUID')

    # Resolve patient: prefer the running retrieval job (authoritative),
    # fall back to find_patient for unsolicited C-STOREs.
    patient = None
    job_study = (
        RetrievalJobStudy.objects
        .filter(study_instance_uid=study_uid, job__status=RetrievalJob.Status.RUNNING)
        .select_related('job__patient')
        .first()
    )
    if job_study:
        patient = job_study.job.patient
    else:
        patient = find_patient(raw_patient_id)

    if patient is None:
        return reject(STATUS_UNKNOWN_PATIENT, f'Unknown PatientID {raw_patient_id}')
    if not patient.chavi_consent:
        return reject(STATUS_NO_CONSENT, f'Patient {raw_patient_id} has not consented')
```

Add the import at the top of `ingest.py`:

```python
from dicom_server.models import InboundDICOMInstance, PatientIDAlias, RetrievalJob, RetrievalJobStudy
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python manage.py test dicom_server.tests.test_cmove_patient_id --noinput --keepdb`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run full ingest tests**

Run: `venv/bin/python manage.py test dicom_server.tests.test_ingest --noinput --keepdb`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dicom_server/services/ingest.py dicom_server/tests/test_cmove_patient_id.py
git commit -m "feat(dicom_server): ingest resolves patient from running retrieval job"
```

---

### Task 4: Update `views.py` and `bulk_selection.py`

**Files:**

- Modify: `dicom_server/views.py:249-265` (`RetrievalJobDetailView`)
- Modify: `dicom_server/views.py:605-675` (`BatchRetrieveView`)
- Modify: `dicom_server/services/bulk_selection.py:192-210` (`build_selections_for_patient`)
- Test: existing tests in `dicom_server/tests/test_bulk_retrieval.py`

**Interfaces:**

- Consumes: `RetrievalJobStudy`, `RetrievalJobSeries` (Task 1)
- Produces: `BatchRetrieveView.post` creates `RetrievalJobStudy`/`RetrievalJobSeries` rows after job creation
- Produces: `RetrievalJobDetailView` queries `job.studies` for the template

- [ ] **Step 1: Update `RetrievalJobDetailView.get_context_data`**

```python
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        uids = list(
            self.object.studies.values_list('study_instance_uid', flat=True)
        )
        context['instances'] = (
            InboundDICOMInstance.objects.filter(study_instance_uid__in=uids)
            if uids else []
        )
        return context
```

- [ ] **Step 2: Update `BatchRetrieveView.post` to create study/series rows**

After the `RetrievalJob.objects.create(...)` call, add:

```python
            # Create study + series rows
            study_objs = []
            for entry in normalized:
                suid = entry['study_instance_uid']
                study_meta = known.get(suid, {})
                study_objs.append(RetrievalJobStudy(
                    job=job,
                    study_instance_uid=suid,
                    remote_patient_id=entry.get('remote_patient_id'),
                    study_date=_parse_dicom_date(study_meta.get('study_date')),
                    study_description=study_meta.get('study_description'),
                    modalities=study_meta.get('modalities'),
                    accession_number=study_meta.get('accession_number'),
                ))
            RetrievalJobStudy.objects.bulk_create(study_objs)
            # Series
            for entry in normalized:
                series_uids = entry.get('series_instance_uids')
                if series_uids:
                    job_study = job.studies.get(study_instance_uid=entry['study_instance_uid'])
                    RetrievalJobSeries.objects.bulk_create([
                        RetrievalJobSeries(study=job_study, series_instance_uid=su)
                        for su in series_uids
                    ])
```

Remove `selections=normalized, studies_found=found_subset` from the `RetrievalJob.objects.create(...)` call.

Add import: `from dicom_server.models import RetrievalJobStudy, RetrievalJobSeries`
Import `_parse_dicom_date` from `dicom_server.tasks` (or move it to a shared utils location).

- [ ] **Step 3: Update `build_selections_for_patient` return shape**

The function already returns `[{'study_instance_uid', 'series_instance_uids', 'remote_patient_id'}]` — this shape is still valid as input for creating `RetrievalJobStudy`/`RetrievalJobSeries` rows. No change needed to the function itself; the callers (Task 2 Step 6, Task 4 Step 2) are responsible for creating the DB rows from the returned dicts.

- [ ] **Step 4: Run bulk retrieval tests**

Run: `venv/bin/python manage.py test dicom_server.tests.test_bulk_retrieval --noinput --keepdb`
Expected: Some failures in assertions that check `job.selections` or `job.studies_found`. Note for Task 6.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/views.py dicom_server/services/bulk_selection.py
git commit -m "feat(dicom_server): update views to create/read job study relations"
```

---

### Task 5: Update template and admin

**Files:**

- Modify: `templates/dicom_server/job_detail.html:38-55`
- Modify: `dicom_server/admin.py:99-107`
- Test: `dicom_server/tests/test_frontend.py` (job detail page test)

**Interfaces:**

- Consumes: `job.studies` related manager (Task 1)

- [ ] **Step 1: Update `job_detail.html`**

Replace the `{% if job.studies_found %}` block:

```html
    {% if job.studies.exists %}
    {% component "card" extra_class="mb-6" %}
        {% fill "header" %}<h3 class="text-lg font-semibold text-gray-900">Studies ({{ job.studies.count }})</h3>{% endfill %}
        {% fill "body" %}
        {% component "table" %}
            {% fill "head" %}
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Study Instance UID</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Date</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Description</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Modalities</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Status</th>
            {% endfill %}
            {% fill "body" %}
                {% for s in job.studies.all %}
                <tr>
                    <td class="px-6 py-4 text-sm font-mono text-xs">{{ s.study_instance_uid|truncatechars:45 }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.study_date|default:"-" }}</td>
                    <td class="px-6 py-4 text-sm">{{ s.study_description|default:"-" }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.modalities|default:"-" }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        {% if s.status == 'done' %}{{ s.completed }}/{{ s.completed|add:s.failed }}
                        {% elif s.status == 'failed' %}Failed
                        {% else %}-{% endif %}
                    </td>
                </tr>
                {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% endfill %}
    {% endcomponent %}
    {% endif %}
```

- [ ] **Step 2: Update admin**

```python
@admin.register(RetrievalJob)
class RetrievalJobAdmin(ModelAdmin):
    list_display = ['pk', 'patient', 'node', 'status', 'instances_received', 'created_by', 'created_at']
    list_filter = ['status', 'node']
    readonly_fields = [f.name for f in RetrievalJob._meta.fields if f.name not in ('study_uids', 'selections', 'item_results', 'studies_found')]
    inlines = [RetrievalJobStudyInline]

    def has_add_permission(self, request):
        return False


class RetrievalJobStudyInline(admin.TabularInline):
    model = RetrievalJobStudy
    extra = 0
    readonly_fields = ['study_instance_uid', 'remote_patient_id', 'study_date',
                       'study_description', 'modalities', 'status',
                       'completed', 'failed', 'warning']
```

- [ ] **Step 3: Run frontend tests**

Run: `venv/bin/python manage.py test dicom_server.tests.test_frontend --noinput --keepdb`
Expected: PASS (or minor fix needed in test that checks studies\_found rendering)

- [ ] **Step 4: Commit**

```bash
git add templates/dicom_server/job_detail.html dicom_server/admin.py
git commit -m "feat(dicom_server): update job detail template and admin for new relations"
```

---

### Task 6: Remove old JSON fields from `RetrievalJob`

**Files:**

- Modify: `dicom_server/models.py` (remove 4 fields)
- Create: migration (remove fields + data migration for historical rows)
- Test: Full test suite

**Interfaces:**

- Consumes: All code from Tasks 1-5 no longer reads the old fields
- Produces: Clean `RetrievalJob` model without JSON blobs

- [ ] **Step 1: Verify no remaining reads of old fields**

Run: `grep -rn "job\.selections\|job\.study_uids\|job\.item_results\|job\.studies_found" --include="*.py" --include="*.html" dicom_server/ templates/ | grep -v __pycache__ | grep -v migrations`
Expected: No results (or only in test files that will be updated in this task)

- [ ] **Step 2: Write data migration**

This is not needed ! This is a dev environment and old jobs that have been run will not need this information anyways.  In production env also the same applies. 

- [ ] **Step 3: Remove the fields from the model**

Remove from `RetrievalJob`:

- `study_uids`
- `selections`
- `item_results`
- `studies_found`

- [ ] **Step 4: Create migration to drop columns**

```bash
venv/bin/python manage.py makemigrations dicom_server
```

- [ ] **Step 5: Update remaining test assertions**

Update all test files that still reference the old fields:

- `dicom_server/tests/test_bulk_retrieval.py` — assertions on `job.selections`, `job.item_results`, `job.study_uids`
- `dicom_server/tests/test_qr.py` — `study_uids=[...]` in job creation
- `dicom_server/tests/test_bulk_schedule.py` — `j.selections` assertions

Replace with assertions on `job.studies` / `job.studies.first().series` etc.

- [ ] **Step 6: Run full test suite**

Run: `venv/bin/python manage.py test dicom_server --noinput --keepdb`
Expected: All 207+ tests PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(dicom_server): remove JSON fields from RetrievalJob, use relations"
```

---

## Summary of the `ingest_dataset` patient resolution (after all tasks)

```
C-STORE arrives at SCP
        │
        ▼
ingest_dataset(ds)
        │
        ├── Query: RetrievalJobStudy WHERE study_instance_uid=X AND job.status='RUNNING'
        │       │
        │       ├── FOUND → patient = job.patient  (authoritative, no ambiguity)
        │       │
        │       └── NOT FOUND → find_patient(raw_patient_id)  (fallback for unsolicited pushes) # No unsolicated pushes are accepted so this is not required. 
        │
        ▼
ds.PatientID = patient.patient_id
ds.PatientName = patient.patient_id
save to processed_dicom/<sanitize(patient.patient_id)>/...
```