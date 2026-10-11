# Scheduled Bulk Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user create a *schedule* for the existing bulk-retrieval flow that runs at an off-peak time — either as a one-off (single eta/countdown Celery run) or as a repeating Celery Beat task — with a bounded number of patients retrieved concurrently so the remote DICOM nodes are not stressed.

**Architecture:** A new `BulkRetrievalSchedule` model stores the node, patient set, extra transforms, mode (ONE_OFF vs PERIODIC), timing, a `max_concurrent_patients` cap, and **declarative selection criteria** (modality, RT-plan approval, series description, RT plan/structure-set labels). At run time a new entry task creates a normal `RetrievalBatch` (query chord → per-patient C-FIND), then selects studies/series via `services/bulk_selection.py` — a server-side port of the interactive `batch_select` filtering (including parent→child series linkage) — and runs the retrieve phase in **bounded chunks** (one chunk in flight at a time, so at most `max_concurrent_patients` patients are retrieved concurrently) instead of one giant group. One-off runs are dispatched with `apply_async(eta=...)`; periodic runs are a `django_celery_beat.PeriodicTask` (crontab) created/updated/deleted by signals, mirroring the existing per-node auto-retrieval schedule sync.

**Tech Stack:** Django 4.x, Celery + django-celery-beat (DatabaseScheduler), pydicom Q/R (via `qr_client`), Tailwind/Crispy templates.

**Spec:** User request (this conversation): add scheduling to `templates/dicom_server/retrieve_bulk.html`'s flow — both one-off and periodic Celery-beat tasks — and bounded retrieval for large patient volumes; plus declarative per-object selection (modality, plan/structure-set approval, series description, labels, child→parent) so a scheduled run fetches only the requested objects instead of whole studies.

## Current behavior (context for executors)

Bulk retrieval today (`dicom_server/views.py`, `dicom_server/tasks.py`):
- Query phase: `group(task_query_patient_studies.s(batch.pk, p.patient_id) for p in patients)` + `chord → task_finalize_batch_query`. One C-FIND task **per patient**, all parallel.
- Retrieve phase: `group(task_retrieve_patient_selection.s(j.pk) for j in jobs)` + `chord → task_finalize_retrieval_batch`. One retrieve task **per patient**; each task retrieves **all of that patient's studies sequentially** inside the task.
- Parallelism across patients is bounded only by worker `concurrency`; **there is no inter-patient throttle/spacing**. This plan adds a bounded-concurrency retrieve phase.

The scheduled run must be **unattended** (no human study/series selection), so it selects objects **declaratively** from the discovered study→series→RT-instance tree. The criteria (modality, RT-plan approval, series description, RT plan/structure-set labels) and the parent→child rule (a plan pulls its structure set, a dose pulls its plan, etc.) must reproduce the interactive `batch_select` behaviour: see `series_visible`/`studyVisible`/`approvalVisible`/`ancestorsOf`/`descendantsOf` in `templates/dicom_server/batch_select.html`. `study['already_local']` (set by `task_query_patient_studies`) drives the "only new" behaviour.

## File Structure

- `dicom_server/models.py` — add `BulkRetrievalSchedule` model (with selection-criteria fields + `selection_criteria()`).
- `dicom_server/migrations/0008_bulkretrievalschedule.py` — migration.
- `dicom_server/services/bulk_selection.py` (new) — `SelectionCriteria` + the study/series/RT filtering and parent→child logic (port of `batch_select.js`).
- `dicom_server/tasks.py` — add `_aggregate_retrieval_batch` helper, `task_bulk_schedule_run`, `task_bulk_schedule_finalize_query` (driven by `bulk_selection`), `task_bulk_schedule_chunk_done`, `task_bulk_schedule_finalize_retrieval`.
- `dicom_server/services/schedule_bulk.py` (new) — one-off eta dispatch + periodic beat sync + cancel/disable.
- `dicom_server/signals.py` — add `post_save`/`post_delete` receivers for `BulkRetrievalSchedule`.
- `dicom_server/forms.py` — add `BulkScheduleForm`.
- `dicom_server/views.py` — add `BulkScheduleCreateView`, `BulkScheduleListView`, `BulkScheduleDeleteView`, `BulkScheduleRunNowView`.
- `dicom_server/urls.py` — add schedule routes.
- `templates/dicom_server/schedule_list.html` (new), `templates/dicom_server/schedule_form.html` (new).
- `templates/dicom_server/retrieve_bulk.html` — add a "Schedules" link/button.
- `dicom_server/tests/test_bulk_schedule.py` (new) — tests for all of the above.

## Global Constraints

- Follow existing patterns: reuse `chord`/`group`, `_create_task_run`/`_complete_task_run`/`_fail_task_run` (from `client_app.tasks`), `qr_client`, and the `django_celery_beat` `CrontabSchedule`/`PeriodicTask` sync style in `services/schedule_sync.py`.
- Cron field validation must reuse the same regex as `RemoteDICOMNode._CRON_FIELD_RE` (`^[\d\-\,\*/]+$`).
- Only consented `Patient`s are retrievable (existing invariant) — enforce on the form.
- Task name registered to Celery must be the dotted path `dicom_server.tasks.<fn>` (that is what beat stores).
- Retrieve concurrency: at most `max_concurrent_patients` patients in flight simultaneously (default 2). Query phase may run as a single group (lightweight C-FIND).
- Selection criteria must reproduce the interactive `batch_select` semantics: RTDOSE inherits its parent RTPLAN's approval verdict; selecting a series pulls in all of its ancestors (plan→structure set, dose→plan); an approved plan keeps its structure set visible even when that structure set itself does not match the modality/description filters.
- Tests run via Django `TestCase` with `CELERY_TASK_ALWAYS_EAGER=True`; mock `qr_client` and record dispatched retrieve tasks rather than hitting a real PACS.
- Commit after each task.

## Task breakdown (one commit each)

1. `BulkRetrievalSchedule` model + migration (incl. selection-criteria fields + `selection_criteria()`).
2. `_aggregate_retrieval_batch` helper + `task_bulk_schedule_run` (creates batch, dispatches query chord).
3. `services/bulk_selection.py` (declarative criteria + parent→child, port of `batch_select.js`) + `task_bulk_schedule_finalize_query` (builds per-patient jobs → starts first chunk).
4. `task_bulk_schedule_chunk_done` + `task_bulk_schedule_finalize_retrieval` (chunk relay + final aggregation + schedule bookkeeping).
5. `services/schedule_bulk.py` (one-off eta + periodic beat + cancel/disable) + signals wiring.
6. `BulkScheduleForm` (incl. selection-criteria fields).
7. Views + urls.
8. Templates + link from the bulk page (criteria fields render via crispy).

---

### Task 1: `BulkRetrievalSchedule` model + migration

**Files:**
- Modify: `dicom_server/models.py`
- Create: `dicom_server/migrations/0008_bulkretrievalschedule.py` (generated)
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Produces: `BulkRetrievalSchedule` with fields below; `crontab_tuple` property; `beat_name` property; `schedule_display` property (human summary of timing); `selection_criteria() -> SelectionCriteria` (from `services/bulk_selection`); `clean()` validating cron fields + one-off `run_at` present when mode=ONE_OFF. Later tasks reference `schedule.patients`, `schedule.mode`, `schedule.max_concurrent_patients`, `schedule.retrieve_new_only`, `schedule.extra_transforms`, `schedule.run_at`, `schedule.one_off_task_id`, `schedule.last_status`, and `schedule.selection_criteria()`.

- [ ] **Step 1: Write the failing test**

Create `dicom_server/tests/test_bulk_schedule.py`:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from client_app.models import Patient, SiteConfiguration
from dicom_server.models import BulkRetrievalSchedule, RemoteDICOMNode


class ModelSetupMixin:
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test',
        )
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1', port=104,
        )

    def _patient(self, patient_id='P001', consent=True):
        p = Patient.objects.create(patient_id=patient_id, gender='Female')
        if consent:
            Patient.objects.filter(pk=p.pk).update(chavi_consent=True)
            p.chavi_consent = True
        return p


class BulkRetrievalScheduleModelTests(ModelSetupMixin, TestCase):
    def test_one_off_defaults(self):
        run_at = timezone.now() + timedelta(hours=2)
        s = BulkRetrievalSchedule.objects.create(
            name='nightly-ish', node=self.node, mode='ONE_OFF', run_at=run_at,
        )
        s.patients.set([self._patient()])
        self.assertEqual(s.max_concurrent_patients, 2)
        self.assertTrue(s.retrieve_new_only)
        self.assertEqual(s.beat_name, f'dicom-bulk-schedule-{s.pk}')

    def test_crontab_tuple(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC',
            minute='30', hour='2', day_of_week='*',
            day_of_month='*', month_of_year='*',
        )
        self.assertEqual(s.crontab_tuple, ('30', '2', '*', '*', '*'))

    def test_invalid_cron_field_rejected(self):
        s = BulkRetrievalSchedule(
            name='x', node=self.node, mode='PERIODIC', minute='61x',
        )
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_one_off_requires_run_at(self):
        s = BulkRetrievalSchedule(name='x', node=self.node, mode='ONE_OFF')
        with self.assertRaises(ValidationError):
            s.full_clean()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `ImportError` / `cannot import name 'BulkRetrievalSchedule'`.

- [ ] **Step 3: Write the model**

Append to `dicom_server/models.py`:

```python
class BulkRetrievalSchedule(models.Model):
    """A saved, off-peak plan to bulk-query + retrieve a set of patients from a
    node. Runs either once (ONE_OFF, dispatched with an eta) or repeatedly
    (PERIODIC, a django_celery_beat.PeriodicTask). Retrieval is capped at
    ``max_concurrent_patients`` so remote nodes are not stressed."""
    class Mode(models.TextChoices):
        ONE_OFF = 'ONE_OFF', 'One-off (run once at a set time)'
        PERIODIC = 'PERIODIC', 'Periodic (repeats on a schedule)'

    name = models.CharField(max_length=200)
    node = models.ForeignKey(
        RemoteDICOMNode, on_delete=models.PROTECT, related_name='bulk_schedules',
    )
    patients = models.ManyToManyField(
        'client_app.Patient', related_name='bulk_schedules',
    )
    extra_transforms = models.JSONField(default=list, blank=True)
    mode = models.CharField(
        max_length=10, choices=Mode.choices, default=Mode.ONE_OFF,
    )
    # One-off timing
    run_at = models.DateTimeField(null=True, blank=True)
    # Periodic crontab (same field format as RemoteDICOMNode)
    minute = models.CharField(max_length=20, default='0')
    hour = models.CharField(max_length=20, default='2')
    day_of_week = models.CharField(max_length=20, default='*')
    day_of_month = models.CharField(max_length=20, default='*')
    month_of_year = models.CharField(max_length=20, default='*')
    max_concurrent_patients = models.PositiveIntegerField(
        default=2,
        help_text='Max patients retrieved at the same time (per chunk).',
    )
    retrieve_new_only = models.BooleanField(
        default=True,
        help_text='When set, only retrieve studies not already stored locally.',
    )
    # ---- Declarative selection criteria (empty = no constraint on that axis) ----
    select_modalities = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Comma-separated modalities to retrieve, e.g. "CT,MR,RTPLAN". Empty = all.',
    )
    select_approval = models.CharField(
        max_length=12, blank=True, default='',
        choices=[('', 'Any'), ('approved', 'Approved only'), ('unapproved', 'Not approved')],
        help_text='RT plan approval filter (RTDOSE inherits its parent plan\'s verdict).',
    )
    select_series_description = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Only series whose description contains this text (case-insensitive).',
    )
    select_rt_label = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Only RT series whose plan/structure-set label or name contains this text.',
    )
    study_date_from = models.DateField(null=True, blank=True)
    study_date_to = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    one_off_task_id = models.CharField(max_length=255, blank=True, default='')
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True, default='')
    last_batch = models.ForeignKey(
        'RetrievalBatch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedule_runs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    _CRON_FIELD_RE = re.compile(r'^[\d\-\,\*/]+$')

    @property
    def crontab_tuple(self):
        return (
            self.minute, self.hour, self.day_of_week,
            self.day_of_month, self.month_of_year,
        )

    @property
    def beat_name(self):
        return f'dicom-bulk-schedule-{self.pk}'

    @property
    def schedule_display(self):
        if self.mode == self.Mode.ONE_OFF:
            return (
                f"once at {self.run_at:%Y-%m-%d %H:%M %Z}" if self.run_at
                else 'one-off (no time set)'
            )
        return (
            f"cron: {self.minute} {self.hour} {self.day_of_month} "
            f"{self.month_of_year} {self.day_of_week}"
        )

    def selection_criteria(self):
        from dicom_server.services import bulk_selection
        mods = [
            m.strip()
            for m in (self.select_modalities or '').replace(',', ' ').split()
            if m.strip()
        ]
        return bulk_selection.SelectionCriteria(
            modalities=mods,
            approval=self.select_approval or '',
            series_description=(self.select_series_description or '').strip(),
            rt_label=(self.select_rt_label or '').strip(),
            study_date_from=self.study_date_from.isoformat() if self.study_date_from else '',
            study_date_to=self.study_date_to.isoformat() if self.study_date_to else '',
        )

    def clean(self):
        super().clean()
        for name, value in [
            ('minute', self.minute), ('hour', self.hour),
            ('day_of_week', self.day_of_week),
            ('day_of_month', self.day_of_month),
            ('month_of_year', self.month_of_year),
        ]:
            if not self._CRON_FIELD_RE.match(value or ''):
                raise ValidationError({name: 'Invalid cron field value.'})
        if self.mode == self.Mode.ONE_OFF and not self.run_at:
            raise ValidationError({'run_at': 'Required for one-off schedules.'})

    def __str__(self):
        return f'{self.name} [{self.get_mode_display()}]'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Bulk retrieval schedule'
        verbose_name_plural = 'Bulk retrieval schedules'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS (4 tests).

- [ ] **Step 5: Create the migration**

Run:
```bash
python manage.py makemigrations dicom_server
```
Expected: creates `dicom_server/migrations/0008_bulkretrievalschedule.py` (name may differ). Open it and confirm the `BulkRetrievalSchedule` model with all fields is present.

- [ ] **Step 6: Run the model tests again + full app suite sanity**

Run: `python manage.py test dicom_server -v 1`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add dicom_server/models.py dicom_server/migrations/ dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): add BulkRetrievalSchedule model"
```

---

### Task 2: aggregation helper + `task_bulk_schedule_run`

**Files:**
- Modify: `dicom_server/tasks.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `BulkRetrievalSchedule` (Task 1), `RetrievalBatch`, `RetrievalBatchPatient`, `task_query_patient_studies` (existing), `_create_task_run`/`_complete_task_run`/`_fail_task_run` (existing).
- Produces:
  - `_aggregate_retrieval_batch(batch) -> (final_status: str, summary: dict)` — pure logic, same shape as `task_finalize_retrieval_batch`'s bookkeeping. Used by `task_bulk_schedule_finalize_retrieval` (Task 4).
  - `_prepare_bulk_schedule_batch(schedule) -> (batch, patients)` — creates the `RetrievalBatch` + one `RetrievalBatchPatient` row per consented patient.
  - `task_bulk_schedule_run(self, schedule_id)` — entry task (used by both one-off eta and periodic beat).

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_bulk_schedule.py` (import `override_settings`, `patch`, `task_bulk_schedule_run`, `_prepare_bulk_schedule_batch`, `_aggregate_retrieval_batch`, `RetrievalBatch`, `RetrievalBatchPatient`):

```python
from django.test import override_settings
from unittest import mock
from dicom_server.tasks import (
    _aggregate_retrieval_batch, _prepare_bulk_schedule_batch,
    task_bulk_schedule_run,
)
from dicom_server.models import RetrievalBatch, RetrievalBatchPatient


def _fake_studies(uids, already_local=()):
    local = set(already_local)
    return [
        {'study_instance_uid': u, 'study_date': '20240101',
         'study_description': '', 'modalities': 'CT', 'instances': 1,
         'remote_patient_id': 'P001', 'already_local': u in local}
        for u in uids
    ], []


class PrepareBatchTests(ModelSetupMixin, TestCase):
    def test_one_row_per_consented_patient(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        p_con = self._patient('PC')
        p_no = self._patient('PN', consent=False)
        s.patients.set([p_con, p_no])
        batch, patients = _prepare_bulk_schedule_batch(s)
        self.assertIsInstance(batch, RetrievalBatch)
        self.assertEqual(batch.node_id, self.node.pk)
        self.assertEqual([p.patient_id for p in patients], ['PC'])
        self.assertEqual(batch.patients.count(), 1)


class AggregateTests(ModelSetupMixin, TestCase):
    def _batch_with_jobs(self):
        batch = RetrievalBatch.objects.create(node=self.node)
        p1 = self._patient('A'); p2 = self._patient('B'); p3 = self._patient('C')
        for p, status, instances in [
            (p1, 'SUCCESS', 5), (p2, 'PARTIAL', 2), (p3, 'FAILED', 0),
        ]:
            j = RetrievalJob.objects.create(
                node=self.node, patient=p, status=status,
                instances_received=instances, batch=batch,
            )
            RetrievalBatchPatient.objects.create(
                batch=batch, patient=p, selected=True, job=j,
            )
        return batch

    def test_aggregate_mixed(self):
        batch = self._batch_with_jobs()
        final, summary = _aggregate_retrieval_batch(batch)
        self.assertEqual(final, 'PARTIAL')
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['instances'], 7)
        self.assertEqual(sorted(summary['succeeded']), ['A'])
        self.assertEqual(sorted(summary['failed']), ['C'])


class RunTaskTests(ModelSetupMixin, TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch('dicom_server.tasks.task_bulk_schedule_finalize_query')
    @patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_creates_batch_and_dispatches(self, mock_find, mock_final):
        mock_find.return_value = _fake_studies(['1.1'])
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        task_bulk_schedule_run(schedule_id=s.pk)
        s.refresh_from_db()
        self.assertIsNotNone(s.last_batch_id)
        self.assertEqual(s.last_batch.patients.count(), 1)
        self.assertTrue(s.last_batch.query_group_id)
        mock_find.assert_called()
        mock_final.assert_called()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch('dicom_server.tasks.qr_client.find_studies_with_series')
    def test_inactive_node_skips(self, mock_find):
        self.node.is_active = False
        self.node.save()
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        s.patients.set([self._patient('P001')])
        res = task_bulk_schedule_run(schedule_id=s.pk)
        self.assertTrue(res.get('skipped'))
        self.assertFalse(RetrievalBatch.objects.exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `cannot import name '_aggregate_retrieval_batch'`.

- [ ] **Step 3: Implement**

Add to the top of `dicom_server/tasks.py` imports (extend the `from dicom_server.models import (...)` line):

```python
from dicom_server.models import (
    AutoRetrievalState, BulkRetrievalSchedule, RemoteDICOMNode, RetrievalBatch,
    RetrievalBatchPatient, RetrievalJob,
)
```

Append to `dicom_server/tasks.py`:

```python
# ---------------------------------------------------------------------------
# Scheduled bulk retrieval
# ---------------------------------------------------------------------------

def _aggregate_retrieval_batch(batch):
    """Compute (final_status, summary) for a retrieve-phase batch. Same shape as
    task_finalize_retrieval_batch uses. Returns RetrievalBatch.Status values."""
    jobs = list(batch.jobs.select_related('patient'))
    succeeded = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.SUCCESS]
    partial = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.PARTIAL]
    failed = [j.patient_id for j in jobs if j.status == RetrievalJob.Status.FAILED]
    running = [j.patient_id for j in jobs if j.status in (
        RetrievalJob.Status.PENDING, RetrievalJob.Status.RUNNING,
    )]
    skipped = list(
        batch.patients.filter(selected=False).values_list('patient_id', flat=True)
    )
    if running:
        final = batch.status
    elif not failed and not partial:
        final = RetrievalBatch.Status.SUCCESS
    elif succeeded or partial:
        final = RetrievalBatch.Status.PARTIAL
    else:
        final = RetrievalBatch.Status.FAILED
    summary = {
        'total': len(jobs), 'succeeded': succeeded, 'partial': partial,
        'failed': failed, 'skipped': skipped,
        'instances': sum(j.instances_received for j in jobs),
    }
    return final, summary


def _prepare_bulk_schedule_batch(schedule):
    """Create the RetrievalBatch + one row per consented schedule patient.
    Returns (batch, patients)."""
    patients = list(schedule.patients.filter(chavi_consent=True))
    batch = RetrievalBatch.objects.create(
        node=schedule.node, created_by=schedule.created_by,
        extra_transforms=schedule.extra_transforms,
    )
    if patients:
        RetrievalBatchPatient.objects.bulk_create(
            RetrievalBatchPatient(batch=batch, patient=p) for p in patients
        )
    return batch, patients


@shared_task(bind=True)
def task_bulk_schedule_run(self, schedule_id):
    """Entry task for a scheduled bulk retrieval (one-off eta or beat).
    Builds a RetrievalBatch, runs the per-patient C-FIND query chord, and hands
    off to task_bulk_schedule_finalize_query which auto-selects + retrieves."""
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_run',
        task_type='DICOM_IMPORT', celery_task_id=self.request.id,
    )
    try:
        schedule = BulkRetrievalSchedule.objects.get(
            pk=schedule_id, is_active=True,
        ).select_related('node')
    except BulkRetrievalSchedule.DoesNotExist as e:
        _fail_task_run(task_run, e)
        return {'schedule': schedule_id, 'skipped': True, 'error': str(e)}

    if not schedule.node.is_active:
        _complete_task_run(task_run, {'skipped': True, 'reason': 'node inactive'})
        return {'schedule': schedule_id, 'skipped': True, 'reason': 'node inactive'}

    batch, patients = _prepare_bulk_schedule_batch(schedule)
    schedule.last_batch = batch
    schedule.save(update_fields=['last_batch', 'updated_at'])

    if not patients:
        schedule.last_status = 'SKIPPED'
        schedule.last_run_at = timezone.now()
        schedule.save(update_fields=['last_status', 'last_run_at', 'updated_at'])
        _complete_task_run(task_run, {'skipped': True, 'reason': 'no consented patients'})
        return {'schedule': schedule_id, 'skipped': True, 'reason': 'no consented patients'}

    try:
        header = group(
            task_query_patient_studies.s(batch.pk, p.patient_id) for p in patients
        )
        result = chord(header)(task_bulk_schedule_finalize_query.s(batch.pk, schedule.pk))
        batch.query_group_id = str(result.id or '')
        batch.save(update_fields=['query_group_id'])
    except Exception as e:
        logger.exception('Failed to dispatch scheduled bulk query')
        batch.status = RetrievalBatch.Status.FAILED
        batch.save(update_fields=['status'])
        _fail_task_run(task_run, e)
        raise

    _complete_task_run(task_run, {'batch': batch.pk, 'patients': len(patients)})
    return {'schedule': schedule_id, 'batch': batch.pk, 'patients': len(patients)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add dicom_server/tasks.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): scheduled bulk run entry task + batch aggregation helper"
```

---

### Task 3: selection criteria service + `task_bulk_schedule_finalize_query`

**Files:**
- Create: `dicom_server/services/bulk_selection.py`
- Modify: `dicom_server/tasks.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `BulkRetrievalSchedule.selection_criteria()` (Task 1), `RetrievalBatch`/`RetrievalBatchPatient`/`RetrievalJob`, `_aggregate_retrieval_batch` (Task 2), `task_retrieve_patient_selection` (existing), `task_bulk_schedule_chunk_done` + `task_bulk_schedule_finalize_retrieval` (Task 4).
- Produces (in `services/bulk_selection.py`):
  - `SelectionCriteria` (dataclass): `modalities: list`, `approval: str`, `series_description: str`, `rt_label: str`, `study_date_from: str`, `study_date_to: str`, `search: str`; method `series_filter_active() -> bool`.
  - `ancestors_of(study, seuid) -> list[str]`, `descendants_of(study, seuid) -> list[str]`.
  - `series_visible(se, study, c) -> bool`, `study_visible(study, c) -> bool`.
  - `select_study(study, c) -> (study_uid, [series_uids]|None) | None` (None series list = whole study).
  - `build_selections_for_patient(studies, c, new_only=False) -> list[dict]` — the `selections` list for a patient's `RetrievalJob` (each `{study_instance_uid, series_instance_uids|None, remote_patient_id}`).
- Produces (in `tasks.py`):
  - `task_bulk_schedule_finalize_query(self, results, batch_id, schedule_id)` — builds one `RetrievalJob` per DONE patient via `build_selections_for_patient`, then starts the bounded retrieve.
  - `_dispatch_retrieval_chunk(batch, schedule, start, cap, total)` — dispatches one chunk's chord (next chunk relay or final body).
  - `_record_schedule_run(schedule, status)` — sets `last_status` + `last_run_at` on the schedule.

- [ ] **Step 1: Write the failing tests (selection service)**

Append to `dicom_server/tests/test_bulk_schedule.py` (these helpers are reused by the finalize tests below too):

```python
from dicom_server.services import bulk_selection
from dicom_server.services.bulk_selection import (
    SelectionCriteria, build_selections_for_patient, select_study,
)


def _series(uid, mod, desc='', parents=(), rt=None):
    se = {
        'series_instance_uid': uid, 'modality': mod,
        'series_description': desc, 'series_number': '',
        'series_date': '20240101', 'instances': 1,
    }
    if parents:
        se['parent_series_uids'] = list(parents)
    if rt is not None:
        se['rt_instances'] = rt
    return se


def _study(uid, series, already_local=False):
    mods = sorted({(s.get('modality') or '') for s in series if s.get('modality')})
    return {
        'study_instance_uid': uid, 'study_date': '20240101',
        'study_description': 'Study', 'accession_number': 'A1',
        'modalities': '\\'.join(mods) if mods else 'OT',
        'instances': sum(s.get('instances') or 0 for s in series),
        'remote_patient_id': 'P001', 'already_local': already_local,
        'series': series,
    }


def _rt_study(uid='ST-1', already_local=False):
    img = _series('S-IMG', 'CT', 'Images')
    struct = _series('S-STRUCT', 'RTSTRUCT', 'Structures', parents=('S-IMG',),
                     rt=[{'sop_instance_uid': 'SOP-SS', 'structure_set_label': 'Body',
                          'structure_set_name': 'Body',
                          'referenced_series_uids': ['S-IMG']}])
    plan = _series('S-PLAN', 'RTPLAN', 'Plan A', parents=('S-STRUCT',),
                   rt=[{'sop_instance_uid': 'SOP-PLAN', 'rt_plan_label': 'PlanA',
                        'rt_plan_name': 'Plan A', 'approval_status': 'APPROVED',
                        'referenced_structure_set_uids': ['SOP-SS']}])
    plan_bad = _series('S-PLAN2', 'RTPLAN', 'Plan B', parents=('S-STRUCT',),
                       rt=[{'sop_instance_uid': 'SOP-PLAN2', 'rt_plan_label': 'PlanB',
                            'approval_status': 'REJECTED',
                            'referenced_structure_set_uids': ['SOP-SS']}])
    dose = _series('S-DOSE', 'RTDOSE', 'Dose', parents=('S-PLAN',),
                   rt=[{'sop_instance_uid': 'SOP-DOSE',
                        'referenced_plan_uids': ['SOP-PLAN']}])
    return _study(uid, [img, struct, plan, plan_bad, dose], already_local)


class SelectionCriteriaParseTests(ModelSetupMixin, TestCase):
    def test_model_builds_criteria(self):
        s = BulkRetrievalSchedule.objects.create(
            name='x', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
            select_modalities='CT, MR', select_approval='approved',
            select_rt_label='Body', select_series_description='Dose',
        )
        c = s.selection_criteria()
        self.assertEqual(c.modalities, ['CT', 'MR'])
        self.assertEqual(c.approval, 'approved')
        self.assertEqual(c.rt_label, 'Body')
        self.assertTrue(c.series_filter_active())


class BulkSelectionTests(TestCase):
    def test_no_criteria_selects_whole_study(self):
        self.assertEqual(select_study(_rt_study(), SelectionCriteria()),
                         ('ST-1', None))

    def test_new_only_skips_local(self):
        st = _rt_study(already_local=True)
        self.assertEqual(build_selections_for_patient([st], SelectionCriteria(),
                                                         new_only=True), [])

    def test_modality_filter_no_ancestors(self):
        sel = select_study(_rt_study(), SelectionCriteria(modalities=['CT']))
        self.assertEqual(sel, ('ST-1', ['S-IMG']))

    def test_dose_pulls_plan_and_struct(self):
        sel = select_study(_rt_study(), SelectionCriteria(modalities=['RTDOSE']))
        self.assertIsNotNone(sel)
        self.assertEqual(set(sel[1]), {'S-DOSE', 'S-PLAN', 'S-STRUCT'})

    def test_approval_approved_excludes_unapproved_plan(self):
        sel = select_study(_rt_study(), SelectionCriteria(approval='approved'))
        chosen = set(sel[1])
        self.assertIn('S-PLAN', chosen)
        self.assertNotIn('S-PLAN2', chosen)

    def test_approval_unapproved_only(self):
        sel = select_study(_rt_study(), SelectionCriteria(approval='unapproved'))
        self.assertIn('S-PLAN2', sel[1])
        self.assertNotIn('S-PLAN', set(sel[1]))

    def test_rt_label_match_pulls_struct(self):
        sel = select_study(_rt_study(), SelectionCriteria(rt_label='PlanA'))
        self.assertIn('S-PLAN', sel[1])
        self.assertIn('S-STRUCT', set(sel[1]))
        self.assertNotIn('S-PLAN2', set(sel[1]))

    def test_series_description_match(self):
        sel = select_study(_rt_study(), SelectionCriteria(series_description='Dose'))
        self.assertEqual(set(sel[1]), {'S-STRUCT', 'S-DOSE', 'S-PLAN'})

    def test_no_matching_series_yields_none(self):
        self.assertIsNone(
            select_study(_rt_study(), SelectionCriteria(modalities=['MR'])))

    def test_build_selections_multiple_studies(self):
        a = _rt_study('ST-1')
        b = _study('ST-2', [_series('S2', 'MR', 'MRI')])
        entries = build_selections_for_patient([a, b],
                                               SelectionCriteria(modalities=['MR']))
        self.assertEqual([e['study_instance_uid'] for e in entries], ['ST-2'])
        self.assertEqual(entries[0]['series_instance_uids'], ['S2'])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `No module named 'dicom_server.services.bulk_selection'`.

- [ ] **Step 3: Implement `services/bulk_selection.py`**

Create `dicom_server/services/bulk_selection.py`:

```python
"""Declarative selection of DICOM objects for scheduled bulk retrieval.

Server-side port of the study/series/RT filtering + parent->child logic used by
the interactive batch_select UI (templates/dicom_server/batch_select.html) so an
unattended scheduled run can retrieve exactly the requested objects instead of
every study.
"""
import re
from dataclasses import dataclass, field

APPROVAL_ANY = ''
APPROVAL_APPROVED = 'approved'
APPROVAL_UNAPPROVED = 'unapproved'


@dataclass
class SelectionCriteria:
    """Declarative 'what to retrieve'. Empty values = no constraint on that
    axis. When every series-level axis is empty the whole (new) study is
    retrieved, matching the UI default."""
    modalities: list = field(default_factory=list)   # e.g. ['CT', 'RTPLAN']
    approval: str = APPROVAL_ANY                     # '' | 'approved' | 'unapproved'
    series_description: str = ''                     # substring, case-insensitive
    rt_label: str = ''                               # substring on plan/struct label/name
    study_date_from: str = ''                        # 'YYYY-MM-DD' or ''
    study_date_to: str = ''
    search: str = ''                                 # description/accession substring

    def series_filter_active(self) -> bool:
        return bool(
            self.modalities or self.approval
            or self.series_description or self.rt_label
        )


def _series_modality(se):
    return (se.get('modality') or '').upper()


def _study_mods(study):
    return [m for m in re.split(r'[,/\\ ]+', (study.get('modalities') or '')) if m]


def _dcm_date_to_iso(d):
    d = d or ''
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}' if len(d) == 8 and d.isdigit() else ''


def _rt_labels(se):
    out = []
    for inst in se.get('rt_instances') or []:
        for k in ('structure_set_label', 'structure_set_name',
                  'rt_plan_label', 'rt_plan_name'):
            v = (inst.get(k) or '').strip()
            if v:
                out.append(v)
    return out


def _plan_approval_state(se):
    return APPROVAL_APPROVED if any(
        (i.get('approval_status') or '').upper() == 'APPROVED'
        for i in (se.get('rt_instances') or [])
    ) else APPROVAL_UNAPPROVED


def _series_by_uid(study):
    return {se.get('series_instance_uid'): se for se in (study.get('series') or [])}


def ancestors_of(study, seuid):
    by = _series_by_uid(study)
    out, seen, queue = [], {seuid}, [seuid]
    while queue:
        cur = queue.pop(0)
        for p in (by.get(cur) or {}).get('parent_series_uids') or []:
            if p in by and p not in seen:
                seen.add(p)
                out.append(p)
                queue.append(p)
    return out


def descendants_of(study, seuid):
    by = _series_by_uid(study)
    children = {}
    for se in by.values():
        for p in se.get('parent_series_uids') or []:
            children.setdefault(p, []).append(se.get('series_instance_uid'))
    out, seen, queue = [], {seuid}, [seuid]
    while queue:
        cur = queue.pop(0)
        for c in children.get(cur) or []:
            if c not in seen:
                seen.add(c)
                out.append(c)
                queue.append(c)
    return out


def _series_passes_approval(study, se, approval):
    mod = _series_modality(se)
    if mod == 'RTPLAN':
        return _plan_approval_state(se) == approval
    if mod == 'RTDOSE' and se.get('parent_series_uids'):
        parents = [x for x in study.get('series') or []
                   if x.get('series_instance_uid') in set(se['parent_series_uids'])]
        return any(_series_passes_approval(study, p, approval) for p in parents)
    return True


def _approval_visible(study, se, approval):
    if _series_passes_approval(study, se, approval):
        return True
    for d in descendants_of(study, se.get('series_instance_uid')):
        child = next((x for x in study.get('series') or []
                      if x.get('series_instance_uid') == d), None)
        if child and _series_passes_approval(study, child, approval):
            return True
    return False


def series_visible(se, study, c):
    mod = _series_modality(se)
    if c.modalities and mod not in [m.upper() for m in c.modalities]:
        return False
    if c.series_description and c.series_description.lower() not in \
            (se.get('series_description') or '').lower():
        return False
    if c.rt_label:
        needle = c.rt_label.lower()
        if not any(needle in lab.lower() for lab in _rt_labels(se)):
            return False
    if c.approval and not _approval_visible(study, se, c.approval):
        return False
    return True


def study_visible(study, c):
    """Study-level gate (mirrors the UI's studyVisible; already_local is handled
    by the caller via new_only)."""
    if c.search:
        needle = c.search.lower()
        study_match = ((study.get('study_description') or '') + ' ' +
                       (study.get('accession_number') or '')).lower()
        if needle not in study_match and not any(
            needle in (se.get('series_description') or '').lower()
            for se in study.get('series') or []
        ):
            return False
    if c.modalities:
        mods = [m.upper() for m in c.modalities]
        study_hit = any(m.upper() in mods for m in _study_mods(study))
        ser_hit = any(_series_modality(se) in mods for se in study.get('series') or [])
        if not study_hit and not ser_hit:
            return False
    if c.approval and not any(
        _approval_visible(study, se, c.approval)
        for se in study.get('series') or []
    ):
        return False
    iso = _dcm_date_to_iso(study.get('study_date'))
    if c.study_date_from and (not iso or iso < c.study_date_from):
        return False
    if c.study_date_to and (not iso or iso > c.study_date_to):
        return False
    return True


def select_study(study, c):
    """Return (study_instance_uid, [series_uids]|None) for a study, or None if it
    yields nothing under the criteria. A None series list means 'whole study'."""
    suid = study.get('study_instance_uid')
    if not suid or not study_visible(study, c):
        return None
    series = study.get('series') or []
    if not c.series_filter_active() or not series:
        return suid, None
    chosen = set()
    for se in series:
        if series_visible(se, study, c):
            uid = se.get('series_instance_uid')
            if uid:
                chosen.add(uid)
    for uid in list(chosen):
        chosen.update(ancestors_of(study, uid))
    if not chosen:
        return None
    return suid, sorted(chosen)


def build_selections_for_patient(studies, c, new_only=False):
    """Flatten a patient's study tree into a `selections` list for its
    RetrievalJob. `new_only` skips studies already stored locally."""
    out = []
    for study in studies or []:
        if new_only and study.get('already_local'):
            continue
        sel = select_study(study, c)
        if sel is None:
            continue
        suid, series_uids = sel
        out.append({
            'study_instance_uid': suid,
            'series_instance_uids': series_uids,
            'remote_patient_id': study.get('remote_patient_id'),
        })
    return out
```

- [ ] **Step 4: Run tests to verify the selection service passes**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS for the `SelectionCriteriaParseTests` + `BulkSelectionTests` classes (the finalize tests are not present yet).

- [ ] **Step 5: Commit the selection service**

```bash
git add dicom_server/services/bulk_selection.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): declarative bulk selection service (modality/approval/label + parent-child)"
```

- [ ] **Step 6: Write the failing tests (finalize_query)**

Append to `dicom_server/tests/test_bulk_schedule.py`:

```python
from dicom_server.tasks import task_bulk_schedule_finalize_query


class FinalizeQueryTests(ModelSetupMixin, TestCase):
    def _schedule(self, **kw):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        for k, v in kw.items():
            setattr(s, k, v)
        s.save()
        return s

    def _row(self, batch, pid, studies):
        p = self._patient(pid)
        row = RetrievalBatchPatient.objects.create(
            batch=batch, patient=p, query_status='DONE',
        )
        row.studies = studies
        row.save(update_fields=['studies'])
        return row

    @patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_no_criteria_selects_whole_study(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study()])
        s = self._schedule(retrieve_new_only=True)
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        j = batch.jobs.first()
        self.assertIsNotNone(j)
        self.assertIsNone(j.selections[0]['series_instance_uids'])
        self.assertEqual(j.selections[0]['study_instance_uid'], 'ST-1')
        mock_dispatch.assert_called_once()
        args = mock_dispatch.call_args[0]
        self.assertIs(args[0], batch)
        self.assertEqual(args[2], 0)   # start
        self.assertEqual(args[4], 1)   # total jobs

    @patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_new_only_skips_local(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study(already_local=True)])
        s = self._schedule(retrieve_new_only=True)
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'SUCCESS')
        self.assertEqual(batch.jobs.count(), 0)
        mock_dispatch.assert_not_called()

    @patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_modality_criteria_selects_series(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='QUERYING')
        self._row(batch, 'P001', [_rt_study()])
        s = self._schedule(retrieve_new_only=False, select_modalities='RTDOSE')
        task_bulk_schedule_finalize_query(results=[], batch_id=batch.pk, schedule_id=s.pk)
        sel = batch.jobs.first().selections[0]
        self.assertEqual(
            set(sel['series_instance_uids']), {'S-DOSE', 'S-PLAN', 'S-STRUCT'},
        )
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `cannot import name 'task_bulk_schedule_finalize_query'`.

- [ ] **Step 8: Implement**

Change the Celery import at the top of `dicom_server/tasks.py` so `chord` and `group` are available (the chunk dispatcher uses them):

```python
from celery import chord, group, shared_task
```

Append to `dicom_server/tasks.py`:

```python
def _record_schedule_run(schedule, status):
    schedule.last_status = status
    schedule.last_run_at = timezone.now()
    schedule.save(update_fields=['last_status', 'last_run_at', 'updated_at'])


def _dispatch_retrieval_chunk(batch, schedule, start, cap, total):
    """Dispatch one chunk (cap patients) of retrieval as a chord. The chord
    body is the next-chunk relay, or the finalizer when this is the last
    chunk. Because only one chunk is ever in flight, at most `cap` patients
    are retrieved concurrently."""
    chunk = batch.jobs.order_by('pk')[start:start + cap]
    if not chunk:
        return None
    if start + cap >= total:
        body = task_bulk_schedule_finalize_retrieval.s(batch.pk, schedule.pk)
    else:
        body = task_bulk_schedule_chunk_done.s(batch.pk, start + cap, total, cap, schedule.pk)
    return chord(group(task_retrieve_patient_selection.s(j.pk) for j in chunk))(body)


@shared_task(bind=True)
def task_bulk_schedule_finalize_query(self, results, batch_id, schedule_id):
    """Chord body for the query phase of a scheduled bulk run. Selects
    studies/series via bulk_selection (per the schedule's criteria) into
    per-patient RetrievalJobs, then starts the bounded retrieve phase."""
    from dicom_server.services import bulk_selection
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_finalize_query',
        task_type='DICOM_IMPORT', celery_task_id=self.request.id,
    )
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
        schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    except (RetrievalBatch.DoesNotExist, BulkRetrievalSchedule.DoesNotExist) as e:
        _fail_task_run(task_run, e)
        return {'batch': batch_id, 'status': 'ERROR', 'error': str(e)}
    if batch.created_by_id:
        task_run.user_id = batch.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    if batch.status != RetrievalBatch.Status.QUERYING:
        _finish_task_run_quiet(task_run, {'skipped': True, 'status': batch.status})
        return {'batch': batch_id, 'status': batch.status, 'skipped': True}

    criteria = schedule.selection_criteria()
    new_only = schedule.retrieve_new_only
    for row in batch.patients.select_related('patient'):
        if row.query_status != RetrievalBatchPatient.QueryStatus.DONE:
            continue
        entries = bulk_selection.build_selections_for_patient(
            row.studies or [], criteria, new_only=new_only,
        )
        if not entries:
            continue
        chosen_uids = {e['study_instance_uid'] for e in entries}
        found_subset = [
            s for s in (row.studies or [])
            if s.get('study_instance_uid') in chosen_uids
        ]
        job = RetrievalJob.objects.create(
            node=batch.node, patient=row.patient, created_by=batch.created_by,
            selections=entries, studies_found=found_subset, batch=batch,
        )
        row.selected = True
        row.job = job
        row.save(update_fields=['selected', 'job'])

    total_jobs = batch.jobs.count()
    if total_jobs == 0:
        final, summary = _aggregate_retrieval_batch(batch)
        batch.summary = summary
        batch.status = final
        batch.completed_at = timezone.now()
        batch.save(update_fields=['status', 'summary', 'completed_at'])
        _record_schedule_run(schedule, final)
        _complete_task_run(task_run, summary)
        return {'batch': batch_id, 'status': final, **summary}

    batch.status = RetrievalBatch.Status.RETRIEVING
    batch.save(update_fields=['status'])
    cap = schedule.max_concurrent_patients or 2
    _dispatch_retrieval_chunk(batch, schedule, 0, cap, total_jobs)
    _complete_task_run(task_run, {'dispatched': True, 'jobs': total_jobs, 'cap': cap})
    return {'batch': batch_id, 'status': batch.status, 'jobs': total_jobs}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add dicom_server/tasks.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): criteria-driven finalize_query + bounded retrieve start"
```

---

### Task 4: `task_bulk_schedule_chunk_done` + `task_bulk_schedule_finalize_retrieval`

**Files:**
- Modify: `dicom_server/tasks.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `_dispatch_retrieval_chunk` (Task 3), `_aggregate_retrieval_batch` (Task 2), `_record_schedule_run` (Task 3).
- Produces:
  - `task_bulk_schedule_chunk_done(self, results, batch_id, next_start, total, cap, schedule_id)` — relay that dispatches the next chunk.
  - `task_bulk_schedule_finalize_retrieval(self, results, batch_id, schedule_id)` — final chord body; aggregates + records schedule run.

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_bulk_schedule.py` (import the two tasks, plus `override_settings` and `task_retrieve_patient_selection`):

```python
from dicom_server.tasks import (
    task_bulk_schedule_chunk_done, task_bulk_schedule_finalize_retrieval,
)


class ChunkRelayTests(ModelSetupMixin, TestCase):
    @patch('dicom_server.tasks._dispatch_retrieval_chunk')
    def test_dispatches_next_chunk(self, mock_dispatch):
        batch = RetrievalBatch.objects.create(node=self.node, status='RETRIEVING')
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )
        task_bulk_schedule_chunk_done(
            results=[], batch_id=batch.pk, next_start=2, total=6,
            cap=2, schedule_id=s.pk,
        )
        mock_dispatch.assert_called_once_with(batch, s, 2, 2, 6)


class FinalizeRetrievalTests(ModelSetupMixin, TestCase):
    def _schedule(self):
        return BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1),
        )

    def test_aggregates_and_records(self):
        batch = RetrievalBatch.objects.create(node=self.node, status='RETRIEVING')
        s = self._schedule()
        for pid, status, inst in [('A', 'SUCCESS', 5), ('B', 'FAILED', 0)]:
            p = self._patient(pid)
            j = RetrievalJob.objects.create(
                node=self.node, patient=p, status=status,
                instances_received=inst, batch=batch,
            )
            RetrievalBatchPatient.objects.create(
                batch=batch, patient=p, selected=True, job=j,
            )
        task_bulk_schedule_finalize_retrieval(results=[], batch_id=batch.pk, schedule_id=s.pk)
        batch.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual(batch.status, 'PARTIAL')
        self.assertEqual(batch.summary['instances'], 5)
        self.assertEqual(s.last_status, 'PARTIAL')
        self.assertIsNotNone(s.last_run_at)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ScheduledRunIntegrationTests(ModelSetupMixin, TestCase):
    """End-to-end scheduled run (query chord -> auto-select -> chunked
    retrieve -> finalize) with Q/R mocked. Asserts the bounded flow reaches a
    terminal state and every patient got a job + instances."""

    def _studies_for(self, pid):
        return ([
            {'study_instance_uid': f'1.2.{pid}', 'study_date': '20240101',
             'study_description': '', 'modalities': 'CT', 'instances': 1,
             'remote_patient_id': pid, 'already_local': False},
        ]), []

    def test_end_to_end_retrieves_all_patients(self):
        from dicom_server.tasks import task_bulk_schedule_run
        p1 = self._patient('A'); p2 = self._patient('B'); p3 = self._patient('C')
        with mock.patch.object(
                'dicom_server.tasks.qr_client', 'find_studies_with_series') as mf, \
                mock.patch('dicom_server.tasks.qr_client.move_study') as mm:
            mf.side_effect = lambda node, ids: self._studies_for(ids[0])
            mm.return_value = {'status': '0000', 'completed': 1, 'failed': 0}
            s = BulkRetrievalSchedule.objects.create(
                name='e2e', node=self.node, mode='ONE_OFF',
                run_at=timezone.now() + timedelta(hours=1),
                max_concurrent_patients=1, retrieve_new_only=True,
            )
            s.patients.set([p1, p2, p3])
            task_bulk_schedule_run(schedule_id=s.pk)

        s.refresh_from_db()
        batch = s.last_batch
        batch.refresh_from_db()
        self.assertEqual(batch.jobs.count(), 3)
        self.assertEqual(batch.status, 'SUCCESS')
        self.assertEqual(batch.summary['instances'], 3)
        self.assertEqual(s.last_status, 'SUCCESS')
        # All three patients were retrieved (jobs succeeded, instances counted).
        self.assertEqual(
            sorted(batch.summary['succeeded']), ['A', 'B', 'C'])

> **Note (eager nested chords):** this test runs a nested chord (chunk → relay → chunk → … → finalize) under `CELERY_TASK_ALWAYS_EAGER=True`, which Celery executes synchronously. If this specific test is flaky in your environment due to eager-mode chord recursion, do **not** weaken the production code — instead assert the chunk count by patching `dicom_server.tasks.chord` to a counter and asserting it was invoked `ceil(jobs / cap)` times for `cap=1, jobs=3` → 3 calls.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `cannot import name 'task_bulk_schedule_chunk_done'`.

- [ ] **Step 3: Implement**

Append to `dicom_server/tasks.py`:

```python
@shared_task(bind=True)
def task_bulk_schedule_chunk_done(self, results, batch_id, next_start, total, cap, schedule_id):
    """Chord body for a non-final retrieve chunk — dispatch the next chunk so
    the next `cap` patients start only after this chunk has completed."""
    batch = RetrievalBatch.objects.get(pk=batch_id)
    schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    _dispatch_retrieval_chunk(batch, schedule, next_start, cap, total)
    return {'batch': batch_id, 'next_start': next_start}


@shared_task(bind=True)
def task_bulk_schedule_finalize_retrieval(self, results, batch_id, schedule_id):
    """Final chord body for a scheduled bulk run — aggregate job statuses onto
    the batch, record the run on the schedule, and notify the owner."""
    task_run = _create_task_run(
        task_name='dicom_server.tasks.task_bulk_schedule_finalize_retrieval',
        task_type='DICOM_IMPORT', celery_task_id=self.request.id,
    )
    try:
        batch = RetrievalBatch.objects.get(pk=batch_id)
        schedule = BulkRetrievalSchedule.objects.get(pk=schedule_id)
    except (RetrievalBatch.DoesNotExist, BulkRetrievalSchedule.DoesNotExist) as e:
        _fail_task_run(task_run, e)
        return {'batch': batch_id, 'status': 'ERROR', 'error': str(e)}
    if batch.created_by_id:
        task_run.user_id = batch.created_by_id
        task_run.save(update_fields=['user_id', 'updated_at'])

    final, summary = _aggregate_retrieval_batch(batch)
    batch.summary = summary
    batch.status = final
    batch.completed_at = timezone.now()
    batch.save(update_fields=['status', 'summary', 'completed_at'])
    _record_schedule_run(schedule, final)
    _complete_task_run(task_run, summary)
    return {'batch': batch_id, 'schedule': schedule_id, 'status': final, **summary}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/tasks.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): chunk relay + final aggregation for scheduled bulk retrieval"
```

---

### Task 5: `services/schedule_bulk.py` (one-off eta + periodic beat + cancel) + signals

**Files:**
- Create: `dicom_server/services/schedule_bulk.py`
- Modify: `dicom_server/signals.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `BulkRetrievalSchedule` (Task 1), `task_bulk_schedule_run` (Task 2), `CrontabSchedule`/`PeriodicTask`.
- Produces: `sync_bulk_schedule(schedule)` (called by `post_save`), `revoke_one_off(schedule)`, `RUN_TASK = 'dicom_server.tasks.task_bulk_schedule_run'`.

- [ ] **Step 1: Write the failing tests**

First, because the `post_save` signal (added in this task) dispatches a real Celery task when a one-off schedule is saved, tests must never reach the broker. Add a broker-free guard to the shared `ModelSetupMixin` in `dicom_server/tests/test_bulk_schedule.py`. Replace its current `setUpTestData`-only body by adding an instance `setUp` (keep `setUpTestData`):

```python
class ModelSetupMixin:
    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test',
        )
        cls.node = RemoteDICOMNode.objects.create(
            name='Stub PACS', ae_title='STUBPACS', host='127.0.0.1', port=104,
        )

    def setUp(self):
        super().setUp()
        # Never touch the broker when a schedule is saved (post_save dispatches).
        patcher = mock.patch('dicom_server.tasks.task_bulk_schedule_run.apply_async')
        self.mock_apply = patcher.start()
        self.mock_apply.return_value = _fake_result()
        self.addCleanup(patcher.stop)

    def _patient(self, patient_id='P001', consent=True):
        p = Patient.objects.create(patient_id=patient_id, gender='Female')
        if consent:
            Patient.objects.filter(pk=p.pk).update(chavi_consent=True)
            p.chavi_consent = True
        return p
```

Then append the scheduling tests (import `PeriodicTask`, `sync_bulk_schedule`; `_fake_result` is defined below the mixin, before the classes):

```python
from django_celery_beat.models import PeriodicTask
from dicom_server.services.schedule_bulk import sync_bulk_schedule


def _fake_result():
    r = mock.MagicMock(); r.id = 'oneoff-id'; return r


class OneOffScheduleTests(ModelSetupMixin, TestCase):
    def test_dispatch_with_eta_on_create(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=3),
        )
        s.refresh_from_db()
        self.assertEqual(s.one_off_task_id, 'oneoff-id')
        self.mock_apply.assert_called_once()
        kwargs = self.mock_apply.call_args.kwargs
        self.assertEqual(kwargs['kwargs'], {'schedule_id': s.pk})
        self.assertEqual(kwargs['eta'], s.run_at)

    @patch('celery.app.control.Control.revoke')
    def test_deactivate_revokes(self, mock_revoke):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=3),
        )
        s.is_active = False
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.one_off_task_id, '')
        mock_revoke.assert_called_once()

    def test_delete_clears_state(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=3),
        )
        s.one_off_task_id = ''  # skip broker revoke on delete
        s.save()
        pk = s.pk
        s.delete()
        self.assertFalse(BulkRetrievalSchedule.objects.filter(pk=pk).exists())


class PeriodicScheduleTests(ModelSetupMixin, TestCase):
    def test_creates_periodic_task(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='PERIODIC',
            minute='15', hour='3', day_of_week='*',
            day_of_month='*', month_of_year='*',
        )
        pt = PeriodicTask.objects.get(name=s.beat_name)
        self.assertEqual(pt.task, 'dicom_server.tasks.task_bulk_schedule_run')
        self.assertEqual(pt.args, json.dumps([s.pk]))
        self.assertTrue(pt.enabled)
        self.assertEqual(pt.crontab.minute, '15')
        self.assertEqual(pt.crontab.hour, '3')

    def test_deactivate_disables_periodic(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='PERIODIC',
        )
        s.is_active = False
        s.save()
        self.assertFalse(PeriodicTask.objects.get(name=s.beat_name).enabled)
```

Note: add `import json` at the top of the test file if not present. `sync_bulk_schedule` is exercised indirectly via the signal in these tests.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `No module named 'dicom_server.services.schedule_bulk'`.

- [ ] **Step 3: Implement the service**

Create `dicom_server/services/schedule_bulk.py`:

```python
"""Dispatch/sync BulkRetrievalSchedule runs: one-off (Celery eta) or periodic
(django_celery_beat.PeriodicTask). Mirrors services/schedule_sync.py."""
import json
import logging

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

logger = logging.getLogger(__name__)

RUN_TASK = 'dicom_server.tasks.task_bulk_schedule_run'


def _ensure_periodic(schedule):
    minute, hour, dow, dom, moy = schedule.crontab_tuple
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute, hour=hour, day_of_week=dow,
        day_of_month=dom, month_of_year=moy,
        timezone=str(settings.TIME_ZONE),
    )
    PeriodicTask.objects.update_or_create(
        name=schedule.beat_name,
        defaults={
            'task': RUN_TASK,
            'args': json.dumps([schedule.pk]),
            'crontab': crontab,
            'enabled': True,
        },
    )


def _dispatch_one_off(schedule):
    from dicom_server.tasks import task_bulk_schedule_run
    result = task_bulk_schedule_run.apply_async(
        kwargs={'schedule_id': schedule.pk}, eta=schedule.run_at,
    )
    schedule.one_off_task_id = result.id or ''
    schedule.save(update_fields=['one_off_task_id', 'updated_at'])
    return result


def revoke_one_off(schedule):
    if not schedule.one_off_task_id:
        return
    from celery import current_app
    try:
        current_app.control.revoke(schedule.one_off_task_id, terminate=False)
    except Exception:
        logger.exception('Failed to revoke one-off task %s', schedule.one_off_task_id)
    schedule.one_off_task_id = ''
    schedule.save(update_fields=['one_off_task_id', 'updated_at'])


def sync_bulk_schedule(schedule):
    """Idempotently bring the dispatch in line with the schedule's state."""
    if not schedule.is_active:
        PeriodicTask.objects.filter(name=schedule.beat_name).update(enabled=False)
        if schedule.one_off_task_id:
            revoke_one_off(schedule)
        return
    if schedule.mode == schedule.Mode.PERIODIC:
        _ensure_periodic(schedule)
        if schedule.one_off_task_id:
            revoke_one_off(schedule)
    elif schedule.mode == schedule.Mode.ONE_OFF:
        PeriodicTask.objects.filter(name=schedule.beat_name).update(enabled=False)
        if not schedule.one_off_task_id:
            _dispatch_one_off(schedule)
```

- [ ] **Step 4: Wire the signals**

In `dicom_server/signals.py`, extend the model import and add two receivers:

```python
from dicom_server.models import BulkRetrievalSchedule, RemoteDICOMNode
from dicom_server.services.schedule_sync import sync_node_schedule
from dicom_server.services.schedule_bulk import sync_bulk_schedule
```

Append receivers at the end of the file:

```python
@receiver(post_save, sender=BulkRetrievalSchedule)
def _sync_bulk_schedule_on_save(sender, instance, **kwargs):
    sync_bulk_schedule(instance)


@receiver(post_delete, sender=BulkRetrievalSchedule)
def _disable_bulk_schedule_on_delete(sender, instance, **kwargs):
    PeriodicTask.objects.filter(name=instance.beat_name).delete()
    if instance.one_off_task_id:
        from celery import current_app
        try:
            current_app.control.revoke(instance.one_off_task_id, terminate=False)
        except Exception:
            logger.exception('Failed to revoke one-off task on delete')
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dicom_server/services/schedule_bulk.py dicom_server/signals.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): schedule one-off/periodic bulk retrieval dispatch + signals"
```

---

### Task 6: `BulkScheduleForm`

**Files:**
- Modify: `dicom_server/forms.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `BulkRetrievalSchedule` (Task 1, incl. selection-criteria fields), `Patient`, `RemoteDICOMNode`, `patient_ids.parse_transform_lines`/`validate_transforms` (existing).
- Produces: `BulkScheduleForm` (ModelForm). `cleaned_data` includes `transforms`-parsed value on `instance.extra_transforms` after `save()`. Cron fields validated for PERIODIC; `run_at` required + future for ONE_OFF. Selection-criteria fields (`select_modalities`, `select_approval`, `select_series_description`, `select_rt_label`, `study_date_from`, `study_date_to`) are blank-allowed.

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_bulk_schedule.py` (import `BulkScheduleForm`; import `re` for the cron test):

```python
from dicom_server.forms import BulkScheduleForm


class BulkScheduleFormTests(ModelSetupMixin, TestCase):
    def _base(self, **over):
        data = {
            'name': 'night pull',
            'node': self.node.pk,
            'mode': 'ONE_OFF',
            'patients': [self._patient('P001').pk],
            'run_at': (timezone.now() + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'minute': '0', 'hour': '2', 'day_of_week': '*',
            'day_of_month': '*', 'month_of_year': '*',
            'max_concurrent_patients': 2,
            'retrieve_new_only': 'on',
            'extra_transforms': '',
            'select_modalities': 'CT', 'select_approval': 'approved',
            'select_series_description': '', 'select_rt_label': '',
            'study_date_from': '', 'study_date_to': '',
        }
        data.update(over)
        return data

    def test_valid_one_off(self):
        form = BulkScheduleForm(data=self._base())
        self.assertTrue(form.is_valid(), form.errors)

    def test_one_off_requires_run_at(self):
        form = BulkScheduleForm(data=self._base(run_at=''))
        self.assertFalse(form.is_valid())
        self.assertIn('run_at', form.errors)

    def test_one_off_rejects_past_run_at(self):
        past = (timezone.now() - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')
        form = BulkScheduleForm(data=self._base(run_at=past))
        self.assertFalse(form.is_valid())
        self.assertIn('run_at', form.errors)

    def test_periodic_rejects_bad_cron(self):
        form = BulkScheduleForm(data=self._base(mode='PERIODIC', run_at='', minute='61x'))
        self.assertFalse(form.is_valid())
        self.assertIn('minute', form.errors)

    def test_transforms_parsed(self):
        form = BulkScheduleForm(data=self._base(
            extra_transforms='^MR/(\\d+)/(\\d+)$ => \\1_\\2',
        ))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['extra_transforms'],
                         [{'pattern': r'^MR/(\d+)/(\d+)$', 'replacement': r'\1_\2'}])

    def test_non_consent_patient_rejected(self):
        p = self._patient('NOC', consent=False)
        form = BulkScheduleForm(data=self._base(patients=[p.pk]))
        self.assertFalse(form.is_valid())

    def test_invalid_approval_choice_rejected(self):
        form = BulkScheduleForm(data=self._base(select_approval='bogus'))
        self.assertFalse(form.is_valid())
        self.assertIn('select_approval', form.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `cannot import name 'BulkScheduleForm'`.

- [ ] **Step 3: Implement the form**

In `dicom_server/forms.py`, add the import for the model and add the class:

```python
from dicom_server.models import (
    BulkRetrievalSchedule, DICOMServerConfiguration, RemoteDICOMNode,
)
```

Append:

```python
_CRON_RE = re.compile(r'^[\d\-\,\*/]+$')


class BulkScheduleForm(forms.ModelForm):
    patients = forms.ModelMultipleChoiceField(
        queryset=Patient.objects.filter(chavi_consent=True),
        widget=forms.SelectMultiple(attrs={'class': 'patient-select w-full'}),
        error_messages={
            'invalid_choice': 'One or more selected patients cannot be scheduled '
                              '— CHAVI consent is required.',
        },
        help_text="Only consented patients registered in the Patient model.",
    )
    extra_transforms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional extra remote-ID rules. ' + _TRANSFORM_HELP,
        label='Extra patient ID transforms',
    )
    run_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='When to run the one-off retrieval (required for one-off mode).',
    )

    class Meta:
        model = BulkRetrievalSchedule
        fields = [
            'name', 'node', 'mode', 'patients', 'run_at',
            'minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year',
            'max_concurrent_patients', 'retrieve_new_only',
            'select_modalities', 'select_approval',
            'select_series_description', 'select_rt_label',
            'study_date_from', 'study_date_to',
        ]
        widgets = {'mode': forms.RadioSelect}

    def clean_extra_transforms(self):
        transforms = patient_ids.parse_transform_lines(
            self.cleaned_data['extra_transforms'],
        )
        errors = patient_ids.validate_transforms(transforms)
        if errors:
            raise forms.ValidationError(' '.join(errors))
        return transforms

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get('mode')
        if mode == BulkRetrievalSchedule.Mode.PERIODIC:
            for name in ('minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year'):
                value = cleaned.get(name) or ''
                if not _CRON_RE.match(value):
                    self.add_error(name, 'Invalid cron field value.')
        elif mode == BulkRetrievalSchedule.Mode.ONE_OFF:
            run_at = cleaned.get('run_at')
            if not run_at:
                self.add_error('run_at', 'Required for one-off schedules.')
            elif timezone.now().timezone and run_at < timezone.now():
                self.add_error('run_at', 'Run time must be in the future.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.extra_transforms = self.cleaned_data['extra_transforms']
        # Re-scheduling a one-off: clear the old task id so the signal re-dispatches.
        if instance.mode == BulkRetrievalSchedule.Mode.ONE_OFF:
            if not instance.pk or instance.run_at:
                instance.one_off_task_id = ''
        if commit:
            instance.save()
            self.save_m2m()
        return instance
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dicom_server/forms.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): BulkScheduleForm with mode-specific validation"
```

---

### Task 7: Views + urls

**Files:**
- Modify: `dicom_server/views.py`
- Modify: `dicom_server/urls.py`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `BulkScheduleForm` (Task 6), `BulkRetrievalSchedule` (Task 1), `task_bulk_schedule_run` (Task 2), existing `DicomPermissionRequiredMixin`.
- Produces views + URL names:
  - `BulkScheduleListView` → `dicom_server:schedule_list` (perm `view_retrievaljob`)
  - `BulkScheduleCreateView` → `dicom_server:schedule_create` (perm `add_retrievaljob`)
  - `BulkScheduleRunNowView` → `dicom_server:schedule_run_now` (POST, perm `add_retrievaljob`)
  - `BulkScheduleToggleView` → `dicom_server:schedule_toggle` (POST, perm `add_retrievaljob`)
  - `BulkScheduleDeleteView` → `dicom_server:schedule_delete` (perm `add_retrievaljob`)

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_bulk_schedule.py` (import `reverse`, `User`, `Permission` from `django.contrib.auth.models`; `BulkRetrievalSchedule` already imported):

```python
from django.contrib.auth.models import Permission, User
from django.urls import reverse


class BulkScheduleViewTests(ModelSetupMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create_user('schedop', password='pw')
        cls.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_server',
            codename__in=['view_remotedicomnode', 'add_retrievaljob',
                          'view_retrievaljob'],
        ))
        cls.plain = User.objects.create_user('plainuser2', password='pw')

    def _form_data(self, schedule=None, **over):
        p = self._patient('VP')
        data = {
            'name': 'sched', 'node': self.node.pk, 'mode': 'ONE_OFF',
            'patients': [p.pk],
            'run_at': (timezone.now() + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'minute': '0', 'hour': '2', 'day_of_week': '*',
            'day_of_month': '*', 'month_of_year': '*',
            'max_concurrent_patients': 2, 'retrieve_new_only': 'on',
            'extra_transforms': '',
        }
        data.update(over)
        return data

    @patch('dicom_server.tasks.task_bulk_schedule_run.apply_async')
    def test_create_dispatches_and_redirects(self, mock_apply):
        mock_apply.return_value = _fake_result()
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('dicom_server:schedule_create'), self._form_data(),
        )
        self.assertEqual(resp.status_code, 302)
        s = BulkRetrievalSchedule.objects.get()
        self.assertEqual(s.one_off_task_id, 'oneoff-id')
        self.assertEqual(s.created_by_id, self.user.pk)

    def test_list_requires_permission(self):
        self.client.force_login(self.plain)
        self.assertEqual(
            self.client.get(reverse('dicom_server:schedule_list')).status_code,
            403)
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse('dicom_server:schedule_list')).status_code,
            200)

    @patch('dicom_server.tasks.task_bulk_schedule_run.apply_async')
    def test_run_now(self, mock_apply):
        mock_apply.return_value = _fake_result()
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1), one_off_task_id='old',
        )
        self.client.force_login(self.user)
        resp = self.client.post(reverse('dicom_server:schedule_run_now', args=[s.pk]))
        self.assertEqual(resp.status_code, 302)
        mock_apply.assert_called_once()
        self.assertEqual(mock_apply.call_args.kwargs.get('kwargs'), {'schedule_id': s.pk})

    def test_toggle_flips_active(self):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1), one_off_task_id='',
        )
        self.client.force_login(self.user)
        self.client.post(reverse('dicom_server:schedule_toggle', args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_active)

    @patch('dicom_server.tasks.task_bulk_schedule_run')
    def test_delete(self, _task):
        s = BulkRetrievalSchedule.objects.create(
            name='s', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1), one_off_task_id='',
        )
        self.client.force_login(self.user)
        pk = s.pk
        self.client.post(reverse('dicom_server:schedule_delete', args=[pk]))
        self.assertFalse(BulkRetrievalSchedule.objects.filter(pk=pk).exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — `NoReverseMatch` for `dicom_server:schedule_create`.

- [ ] **Step 3: Implement the views**

In `dicom_server/views.py`, extend imports:

```python
from django.views.generic import (
    TemplateView, ListView, CreateView, UpdateView, DeleteView,
    DetailView, FormView,
)
from dicom_server.forms import (
    BulkRetrieveForm, BulkScheduleForm, DICOMServerConfigForm,
    RemoteDICOMNodeForm, RetrieveStudiesForm,
)
from dicom_server.models import (
    BulkRetrievalSchedule, DICOMServerConfiguration, RemoteDICOMNode,
    InboundDICOMInstance, PatientIDAlias, RetrievalBatch, RetrievalBatchPatient,
    RetrievalJob,
)
from dicom_server.tasks import (
    task_bulk_schedule_run, task_finalize_batch_query,
    task_finalize_retrieval_batch, task_query_patient_studies,
    task_retrieve_patient_selection, task_retrieve_studies,
)
```

Append these view classes to `dicom_server/views.py`:

```python
# --- Scheduled bulk retrieval ---

class BulkScheduleListView(DicomPermissionRequiredMixin, ListView):
    model = BulkRetrievalSchedule
    template_name = 'dicom_server/schedule_list.html'
    permission_required = 'dicom_server.view_retrievaljob'
    context_object_name = 'schedules'
    paginate_by = 25


class BulkScheduleCreateView(DicomPermissionRequiredMixin, CreateView):
    model = BulkRetrievalSchedule
    form_class = BulkScheduleForm
    template_name = 'dicom_server/schedule_form.html'
    permission_required = 'dicom_server.add_retrievaljob'
    success_url = reverse_lazy('dicom_server:schedule_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.save()  # post_save signal performs the one-off/periodic dispatch
        messages.success(self.request, 'Bulk retrieval schedule saved.')
        return redirect(self.success_url)


class BulkScheduleRunNowView(DicomPermissionRequiredMixin, View):
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request, pk):
        schedule = get_object_or_404(BulkRetrievalSchedule, pk=pk)
        try:
            task_bulk_schedule_run.apply_async(kwargs={'schedule_id': schedule.pk})
            messages.success(request, f'Schedule "{schedule.name}" is running now.')
        except Exception as e:
            logger.exception('Failed to run schedule now')
            messages.error(request, f'Could not start schedule: {e}')
        return redirect('dicom_server:schedule_list')


class BulkScheduleToggleView(DicomPermissionRequiredMixin, View):
    permission_required = 'dicom_server.add_retrievaljob'

    def post(self, request, pk):
        schedule = get_object_or_404(BulkRetrievalSchedule, pk=pk)
        schedule.is_active = not schedule.is_active
        schedule.save()  # signal enables/disables the dispatch
        if schedule.is_active:
            messages.success(request, f'Schedule "{schedule.name}" enabled.')
        else:
            messages.info(request, f'Schedule "{schedule.name}" disabled.')
        return redirect('dicom_server:schedule_list')


class BulkScheduleDeleteView(DicomPermissionRequiredMixin, DeleteView):
    model = BulkRetrievalSchedule
    template_name = 'dicom_server/schedule_confirm_delete.html'
    permission_required = 'dicom_server.add_retrievaljob'
    success_url = reverse_lazy('dicom_server:schedule_list')
```

- [ ] **Step 4: Add the URL routes**

In `dicom_server/urls.py`, add (before the closing `]`):

```python
    path('retrieve/bulk/schedules/', views.BulkScheduleListView.as_view(), name='schedule_list'),
    path('retrieve/bulk/schedules/add/', views.BulkScheduleCreateView.as_view(), name='schedule_create'),
    path('retrieve/bulk/schedules/<int:pk>/run/', views.BulkScheduleRunNowView.as_view(), name='schedule_run_now'),
    path('retrieve/bulk/schedules/<int:pk>/toggle/', views.BulkScheduleToggleView.as_view(), name='schedule_toggle'),
    path('retrieve/bulk/schedules/<int:pk>/delete/', views.BulkScheduleDeleteView.as_view(), name='schedule_delete'),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dicom_server/views.py dicom_server/urls.py dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): scheduled bulk retrieval views + urls"
```

---

### Task 8: Templates + link from the bulk page

**Files:**
- Create: `templates/dicom_server/schedule_list.html`
- Create: `templates/dicom_server/schedule_form.html`
- Create: `templates/dicom_server/schedule_confirm_delete.html`
- Modify: `templates/dicom_server/retrieve_bulk.html`
- Test: `dicom_server/tests/test_bulk_schedule.py`

**Interfaces:**
- Consumes: `schedules` (list) + `schedules.has_more`/pagination (ListView), `form` (CreateView), `object` (DeleteView); URL names from Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `dicom_server/tests/test_bulk_schedule.py`:

```python
class BulkScheduleTemplateTests(BulkScheduleViewTests):
    def test_list_renders_schedule(self):
        s = BulkRetrievalSchedule.objects.create(
            name='visible-name', node=self.node, mode='ONE_OFF',
            run_at=timezone.now() + timedelta(hours=1), one_off_task_id='',
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse('dicom_server:schedule_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'visible-name')
        self.assertContains(resp, s.schedule_display)

    def test_create_page_renders_form(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('dicom_server:schedule_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id_name')
        self.assertContains(resp, 'id_node')

    def test_bulk_page_links_to_schedules(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('dicom_server:retrieve_bulk'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('dicom_server:schedule_list'))
```

Note: `BulkScheduleTemplateTests` subclasses `BulkScheduleViewTests` to reuse `self.user`/`self.node`. `retrieve_bulk` requires `add_retrievaljob` (granted to `self.user`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_server.tests.test_bulk_schedule -v 2`
Expected: FAIL — template not found / 500 for `schedule_list`.

- [ ] **Step 3: Create `templates/dicom_server/schedule_list.html`**

```html
{% extends "base.html" %}
{% block title %}Bulk Retrieval Schedules - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-5xl mx-auto px-4 py-8">
    {% url 'dicom_server:schedule_create' as add_url %}
    {% url 'dicom_server:retrieve_bulk' as back_url %}
    {% component "page_header" title="Bulk Retrieval Schedules" icon="fas fa-clock" back_url=back_url back_text="Back to bulk retrieve" %}
        {% fill "actions" %}
            {% if perms.dicom_server.add_retrievaljob %}
            {% component "button" style="primary" href=add_url icon="fas fa-plus" %}New Schedule{% endcomponent %}
            {% endif %}
        {% endfill %}
    {% endcomponent %}

    {% component "card" %}{% fill "body" %}
        {% if schedules %}
        {% component "table" %}
            {% fill "head" %}
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Name</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Node</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Mode</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Schedule</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Concurrency</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Patients</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Active</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Last run</th>
                <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Actions</th>
            {% endfill %}
            {% fill "body" %}
                {% for s in schedules %}
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{{ s.name }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.node.name }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.get_mode_display }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{{ s.schedule_display }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.max_concurrent_patients }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">{{ s.patients.count }}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        {% if s.is_active %}{% component "badge" style="success" %}Yes{% endcomponent %}{% else %}{% component "badge" style="danger" %}No{% endcomponent %}{% endif %}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                        {% if s.last_run_at %}{{ s.last_run_at|date:"Y-m-d H:i" }} · {{ s.last_status }}{% else %}—{% endif %}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm space-x-2">
                        {% if perms.dicom_server.add_retrievaljob %}
                        <form method="post" action="{% url 'dicom_server:schedule_run_now' s.pk %}" class="inline">
                            {% csrf_token %}
                            {% component "icon_button" icon="fas fa-play" type="submit" aria_label="Run now" title="Run now" %}{% endcomponent %}
                        </form>
                        <form method="post" action="{% url 'dicom_server:schedule_toggle' s.pk %}" class="inline">
                            {% csrf_token %}
                            {% if s.is_active %}
                            {% component "icon_button" icon="fas fa-pause" type="submit" aria_label="Disable" title="Disable" %}{% endcomponent %}
                            {% else %}
                            {% component "icon_button" icon="fas fa-play" type="submit" aria_label="Enable" title="Enable" %}{% endcomponent %}
                            {% endif %}
                        </form>
                        {% component "icon_button" icon="fas fa-trash" style="danger" aria_label="Delete" href="{% url 'dicom_server:schedule_delete' s.pk %}" title="Delete" %}{% endcomponent %}
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% else %}
        {% component "empty_state" title="No schedules yet" description="Create a schedule to run bulk retrieval off-peak." %}
            {% fill "action" %}
                {% if perms.dicom_server.add_retrievaljob %}
                {% component "button" style="primary" href=add_url icon="fas fa-plus" %}New Schedule{% endcomponent %}
                {% endif %}
            {% endfill %}
        {% endcomponent %}
        {% endif %}
        {% endfill %}{% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 4: Create `templates/dicom_server/schedule_form.html`**

```html
{% extends "base.html" %}
{% load crispy_forms_tags %}
{% block title %}New Bulk Retrieval Schedule - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto px-4 py-8">
    {% url 'dicom_server:schedule_list' as back_url %}
    {% component "page_header" title="New Bulk Retrieval Schedule" icon="fas fa-clock" back_url=back_url back_text="Back to schedules" %}{% endcomponent %}
    {% component "card" %}{% fill "body" %}
        <form method="post">
            {% csrf_token %}
            {{ form|crispy }}
            <div class="mt-2 text-xs text-gray-500 mb-4">
                One-off runs at the set time (no repeat). Periodic runs on the
                crontab below. Retrieval is limited to <em>Concurrency</em>
                patients at a time so remote nodes are not stressed. Leave the
                selection fields blank to retrieve every (new) study; set
                Modality / Plan approval / Series description / RT label to
                fetch only matching series (their structure sets and plans are
                pulled in automatically).
            </div>
            <div class="mt-6 flex space-x-3">
                {% component "button" style="primary" type="submit" icon="fas fa-save" %}Save{% endcomponent %}
                {% component "button" style="secondary" href=back_url %}Cancel{% endcomponent %}
            </div>
        </form>
    {% endfill %}{% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 5: Create `templates/dicom_server/schedule_confirm_delete.html`**

```html
{% extends "base.html" %}
{% block title %}Delete Schedule - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-xl mx-auto px-4 py-8">
    {% url 'dicom_server:schedule_list' as back_url %}
    {% component "page_header" title="Delete Schedule" icon="fas fa-trash" back_url=back_url back_text="Back to schedules" %}{% endcomponent %}
    {% component "card" accent="peach" %}{% fill "body" %}
        <p class="text-sm text-gray-700 mb-4">Delete schedule <strong>{{ object.name }}</strong>? Any pending one-off run will be cancelled. This cannot be undone.</p>
        <form method="post" class="flex space-x-3">
            {% csrf_token %}
            {% component "button" style="danger" type="submit" icon="fas fa-trash" %}Delete{% endcomponent %}
            {% component "button" style="secondary" href=back_url %}Cancel{% endcomponent %}
        </form>
    {% endfill %}{% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 6: Add a link from the bulk page**

In `templates/dicom_server/retrieve_bulk.html`, immediately after the existing query button row:

```html
        <div class="mt-6 flex items-center space-x-3">
            {% component "button" style="primary" type="button" icon="fas fa-search" id="btn-query" %}Query Remote Node{% endcomponent %}
            <span id="query-status" class="text-sm text-gray-500"></span>
        </div>
```

add a sibling row for schedules:

```html
        <div class="mt-4 flex items-center space-x-3 text-sm">
            <span class="text-gray-500">Prefer off-peak? </span>
            {% url 'dicom_server:schedule_list' as sched_list_url %}
            {% url 'dicom_server:schedule_create' as sched_new_url %}
            <a class="text-chavi-primary hover:underline" href="{{ sched_list_url }}">View schedules</a>
            {% if perms.dicom_server.add_retrievaljob %}
            <a class="text-chavi-primary hover:underline" href="{{ sched_new_url }}">New schedule</a>
            {% endif %}
        </div>
```

- [ ] **Step 7: Run the full test suite**

Run: `python manage.py test dicom_server -v 1`
Expected: PASS (including the new `test_bulk_schedule` tests and existing suites).

- [ ] **Step 8: Commit**

```bash
git add templates/dicom_server/schedule_list.html templates/dicom_server/schedule_form.html templates/dicom_server/schedule_confirm_delete.html templates/dicom_server/retrieve_bulk.html dicom_server/tests/test_bulk_schedule.py
git commit -m "feat(dicom): scheduled bulk retrieval templates + bulk-page link"
```
