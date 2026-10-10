# DICOM Archive — Deidentification Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire DICOM de-archival into the deidentification Celery chain so archived studies are restored before any deid job touches a patient's files, both at dispatch time and as a per-study safety net.

**Architecture:** Two hooks in `deidentification/tasks.py` only — no deidentification model/view changes. (1) The dispatcher `deidentify_dicom_studies_bulk_task` calls `dicom_archive.services.dearchive.dearchival_required_for_studies()` after the parent `TaskRun` exists and, if anything is archived, restores them **in-process** via `dicom_archive.services.dearchive.dearchive_studies(required)` before dispatching the first serial link; a de-archive failure fails the parent run. (2) Each link `deidentify_dicom_study_task` calls `ensure_studies_local([study_id])` before `deidentify_study()`; a `'failed'` state records an error on the parent run, fails the child run, and still advances the chain (per-study failure isolation).

**Tech Stack:** Django (TestCase, no pytest), Celery `shared_task`, `client_app.TaskRun` tracking, Django `unittest.mock.patch`.

**Spec:** `docs/superpowers/plans/2026-10-10-dicom-archive-00-overview.md` (binding contract — "Deidentification hooks (plan 02)" section).

## Global Constraints

- **Prerequisite: plan 01 (`2026-10-10-dicom-archive-01-core.md`) must be complete first.** This plan consumes `dicom_archive.models.ArchiveLocation`, `dicom_archive.models.ArchivedStudy`, `dicom_archive.services.dearchive.dearchival_required_for_studies`, `dicom_archive.services.dearchive.dearchive_studies`, `dicom_archive.services.dearchive.ensure_studies_local`, and `TaskRun.TaskType.DICOM_DEARCHIVE` — all owned by plan 01.
- **No git commits until the user approves.** Every "commit" step below must be executed as a local commit ONLY after explicit user approval of the overall implementation.
- Use the binding contract's exact names: `dearchival_required_for_studies(study_uids) -> list[str]`, `ensure_studies_local(study_uids) -> dict` returning `{'<uid>': 'local' | 'dearchived' | 'failed'}`, `dearchive_studies(study_uids, user=None) -> dict` returning `{'dearchived': [...], 'failed': {uid: str}}`.
- Hooks live ONLY in `deidentification/tasks.py`. No changes to `deidentification` models, views, urls, or permissions.
- `DICOMStudy.folder_path` is an absolute POSIX path — never re-join `MEDIA_ROOT` in archive code.
- Per-study failure isolation: one bad study must not fail a batch (the guard advances the chain).
- Tests are Django `TestCase` under `deidentification/`; `*.dcm` test files are plain text (no pydicom parsing needed).
- Never edit existing migration files; never hand-edit migrations (plan 02 creates none).

## Design notes

- **Hook placement (dispatcher):** inserted between the `_update_task_run(...)` call and the `if next_index is None:` dispatch decision in `deidentify_dicom_studies_bulk_task`, guarded by `if next_index == 0:` — i.e. de-archival happens exactly on the FIRST link dispatch. On a dispatcher resume after a pre-dispatch failure, `next_index` is again 0 and the call is idempotent (successfully de-archived rows are `DEARCHIVED`, so `dearchival_required_for_studies` returns `[]`).
- **In-process de-archive in the dispatcher (NOT a celery subtask).** Celery forbids `result.get()` inside a task: under a real worker it risks deadlocking the pool (the dispatcher occupies a slot while waiting for the de-archive to get one), and under `task_always_eager` it raises `RuntimeError: Never call result.get() within a task!` outright. The hook therefore calls `dearchive_studies(required)` directly in the dispatcher — the same pattern as the `ensure_studies_local([study_id])` safety net inside each link. De-archival is local file moves, per-study failures are isolated in the returned `failed` map, and the dispatcher's global `CELERY_TASK_TIME_LIMIT = 3600` bounds the worst case. (An earlier draft of this plan used `dearchive_studies_task.delay(...).get(timeout=...)` with a `DICOM_ARCHIVE_DEARCHIVE_TIMEOUT_SECONDS` budget — superseded; the setting was removed.)
- **Failure semantics differ by level (contract):** dispatcher-level de-archive failure fails the PARENT run and stops everything (`_fail_task_run(task_run, ...)` + `return`); guard-level failure fails only the child run and the chain continues via `_deid_dispatch_next`.
- **Imports are module-level** (`from dicom_archive.services.dearchive import dearchival_required_for_studies, dearchive_studies, ensure_studies_local`). No circular import: `dicom_archive.services.dearchive` imports only `dicom_archive.models` and Django utilities.
- **Existing tests in `deidentification/tests.py` need no changes:** they create no `ArchivedStudy` rows, so `dearchival_required_for_studies` returns `[]` and `ensure_studies_local` returns `{'<uid>': 'local'}` — both hooks are no-ops there. Task 4 proves this by re-running the suite.
- The guard sets the pre-created `DeidentificationJob` row to `FAILURE` (it is created before the guard; leaving it `PENDING` would hang the job view).

---

### Task 1: Dispatcher hook — de-archive archived roster studies before the first link

**Files:**
- Create: `deidentification/test_archive_hooks.py`
- Modify: `deidentification/tasks.py:27-28` (imports) and `deidentification/tasks.py:126-134` (dispatcher body)

**Interfaces:**
- Consumes: `dearchival_required_for_studies(study_uids: list[str]) -> list[str]` (uids with an `ARCHIVED` `archive_record`); `dearchive_studies(study_uids, user=None) -> dict` `{'dearchived': [uid, ...], 'failed': {uid: str(err)}}` (in-process, per-study isolation); `_fail_task_run(task_run, error)` from `client_app.tasks`.
- Produces: dispatcher behavior — on first dispatch, any uids returned by `dearchival_required_for_studies` are de-archived synchronously before `deidentify_dicom_study_task.delay(...)`; on de-archive failure the parent `TaskRun` is set to `FAILURE` and the task returns `{'status': 'failed', 'run_id': <id>, 'error': <msg>}` without dispatching any link.

- [ ] **Step 1: Write the failing test**

Create `deidentification/test_archive_hooks.py` with the shared test harness and test (a) — the dispatcher de-archives archived studies before the first link:

```python
"""Tests for the de-archival hooks wired into the deidentification chain.

Coverage:
  (a) the dispatcher de-archives archived roster studies before the first
      serial link is dispatched;
  (b) no archived studies => no de-archive dispatch;
  (c) de-archive failure => parent TaskRun FAILURE, no link dispatched;
  (d) the per-study guard 'failed' path records on the parent run, fails
      the child run, and advances the chain.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone


class ArchiveHookTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from client_app.models import Patient, DICOMStudy, SiteConfiguration
        from deidentification.tasks import (
            deidentify_dicom_studies_bulk_task,
            deidentify_dicom_study_task,
        )

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._media = override_settings(MEDIA_ROOT=self._tmp.name)
        self._media.enable()
        self.addCleanup(self._media.disable)

        self.bulk_task = deidentify_dicom_studies_bulk_task
        self.link_task = deidentify_dicom_study_task

        # close_old_connections() would drop the TestCase's wrapped
        # transaction connection — patch it out.
        self._conn_patch = patch('deidentification.tasks.close_old_connections')
        self._conn_patch.start()
        self.addCleanup(self._conn_patch.stop)

        self.user = User.objects.create_user(username='archhook', password='pw')
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Center')
        self.patient = Patient.objects.create(patient_id='P1')
        self.study_a = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-A')
        self.study_b = DICOMStudy.objects.create(
            patient=self.patient, study_instance_uid='UID-B')
        self._location = None

    def _make_parent(self, run_id, results=None):
        from client_app.models import TaskRun
        return TaskRun.objects.create(
            task_id=run_id,
            task_name='deidentify_dicom_studies_bulk',
            task_type=TaskRun.TaskType.DEIDENTIFICATION,
            status=TaskRun.Status.PROGRESS,
            user=self.user,
            task_args=[['UID-A', 'UID-B']],
            task_kwargs={'user_id': self.user.id},
            result_summary={'results': results or {}},
        )

    def _archive_study(self, study, uid):
        """Create the ArchiveLocation + on-disk archive folder + an
        ArchivedStudy(ARCHIVED) row for `study` (uid == its study_instance_uid).
        The study's local folder deliberately does NOT exist on disk."""
        from dicom_archive.models import ArchiveLocation, ArchivedStudy

        if self._location is None:
            archive_root = Path(self._tmp.name) / 'archive_root'
            archive_root.mkdir(parents=True, exist_ok=True)
            self._location = ArchiveLocation.objects.create(
                name='hook-test-loc',
                storage_type=ArchiveLocation.StorageType.LOCAL,
                path=str(archive_root),
                is_active=True,
            )

        local_before = (Path(self._tmp.name) / 'processed_dicom'
                        / study.patient.patient_id / uid)
        dest = Path(self._location.path) / study.patient.patient_id / uid
        dest.mkdir(parents=True, exist_ok=True)
        (dest / 'IMG1.dcm').write_text('fake dicom bytes')
        (dest / '_archive_manifest.json').write_text('{"file_count": 1}')

        return ArchivedStudy.objects.create(
            study=study,
            location=self._location,
            status=ArchivedStudy.Status.ARCHIVED,
            reason=ArchivedStudy.Reason.SCHEDULED,
            local_path_before=str(local_before),
            archive_rel_path=f"{study.patient.patient_id}/{uid}",
            size_bytes=15,
            instance_count=1,
            archived_at=timezone.now(),
        )

    def test_bulk_deid_dearchives_archived_studies_before_first_link(self):
        """(a) Mix of archived + local studies for one patient: the archived
        one is de-archived before the first serial link is dispatched."""
        self._archive_study(self.study_a, 'UID-A')
        # study_b stays local — no ArchivedStudy row for it.

        order = []
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay',
                             side_effect=lambda *a, **k: (order.append('link'), None)[1]) as mock_delay:
            mock_dearch.side_effect = lambda *a, **k: (
                order.append('dearchive'),
                {'dearchived': ['UID-A'], 'failed': {}})[1]
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-a1',
            )

        # The real service must have found exactly the archived study.
        mock_dearch.assert_called_once_with(['UID-A'])
        # De-archive happened strictly before the first link dispatch.
        self.assertEqual(order, ['dearchive', 'link'])
        mock_delay.assert_called_once_with('arch-a1', 0, user_id=self.user.id)
        self.assertEqual(res.result['status'], 'dispatched')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python manage.py test deidentification.test_archive_hooks -v 2`
Expected: FAIL — `AttributeError: <module 'deidentification.tasks' ...> does not have the attribute 'dearchive_studies'` (the `patch(...)` target does not exist yet).

- [ ] **Step 3: Implement the dispatcher hook**

Edit `deidentification/tasks.py` with two changes.

Import addition — after line 28 (`from deidentification.services.dicom_deidentification_flow import deidentify_study`), add:

```python
from dicom_archive.services.dearchive import dearchival_required_for_studies, dearchive_studies
```

Dispatcher hook — inside `deidentify_dicom_studies_bulk_task`, replace this block:

```python
        if next_index is None:
            finalize_deidentification_batch_task.delay(self.request.id)
        else:
            deidentify_dicom_study_task.delay(self.request.id, next_index, user_id=user_id)
```

with:

```python
        if next_index == 0:
            # De-archival hook (dicom_archive): any study in this roster that
            # is currently archived must be restored to its local folder
            # before the serial deid chain is allowed to touch it.
            # In-process call — NOT a celery subtask: result.get() inside a
            # task is forbidden (deadlocks the pool / raises under
            # task_always_eager). Same pattern as ensure_studies_local().
            required = dearchival_required_for_studies(list(study_ids))
            if required:
                result = dearchive_studies(required)
                failed = (result or {}).get('failed') or {}
                if failed:
                    message = (
                        f"De-archival failed for {len(failed)} of {len(required)} "
                        f"archived study(s); deidentification not started. Details: "
                        + "; ".join(
                            f"{uid} — {err}" for uid, err in sorted(failed.items())
                        )
                    )
                    _fail_task_run(task_run, message)
                    return {
                        'status': 'failed', 'run_id': self.request.id,
                        'error': message,
                    }
                logger.info(
                    f"De-archival complete for {len(required)} archived study(s) "
                    f"ahead of deidentification run {self.request.id}"
                )

        if next_index is None:
            finalize_deidentification_batch_task.delay(self.request.id)
        else:
            deidentify_dicom_study_task.delay(self.request.id, next_index, user_id=user_id)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python manage.py test deidentification.test_archive_hooks -v 2`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

Commit ONLY after explicit user approval of the overall implementation (global constraint — no git commits till approval):

```bash
git add deidentification/tasks.py deidentification/test_archive_hooks.py
git commit -m "feat(dicom_archive): de-archive archived studies in deid dispatcher before first link"
```

---

### Task 2: Per-study safety net — `ensure_studies_local` guard in `deidentify_dicom_study_task`

**Files:**
- Modify: `deidentification/tasks.py:225-227` (link body, just before `def progress_callback`)
- Test: `deidentification/test_archive_hooks.py` (append test (d) to the existing `ArchiveHookTests` class)

**Interfaces:**
- Consumes: `ensure_studies_local(study_uids: list[str]) -> dict` mapping each uid to `'local'` (no ARCHIVED record, folder assumed present), `'dearchived'` (restored now), or `'failed'` (restoration attempt failed); `_deid_record_result(run_id, index, entry) -> int`; `_deid_dispatch_next(run_id, index, total, user_id) -> None`; `_fail_task_run(task_run, error)`.
- Produces: link behavior — when `ensure_studies_local([study_id]).get(study_id) == 'failed'`, the link records an error entry under `parent.result_summary['results'][str(index)]` containing `{'index', 'study_id', 'error', 'processed': 0, 'failed': 0}`, sets the `DeidentificationJob` to `FAILURE`, fails the child `TaskRun`, dispatches the next link (or finalize) via `_deid_dispatch_next`, and returns `{'status': 'failed', 'error': <msg>}` — the chain always advances.

- [ ] **Step 1: Write the failing test**

Append this method inside the `ArchiveHookTests` class in `deidentification/test_archive_hooks.py`, immediately after `test_bulk_deid_dearchives_archived_studies_before_first_link`:

```python
    def test_guard_failure_records_parent_failure_and_advances_chain(self):
        """(d) The per-study guard reports 'failed' for this study: the
        failure is recorded on the parent run, the child run is failed, and
        the chain still advances to the next study."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-d1')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'failed'}) as mock_ensure, \
                patch('deidentification.tasks.deidentify_study') as mock_deid, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-d1', 0], kwargs={'user_id': self.user.id},
                task_id='arch-d1-link0',
            )

        self.assertEqual(res.result['status'], 'failed')
        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_not_called()
        # Chain advances despite the per-study failure.
        mock_delay.assert_called_once_with('arch-d1', 1, user_id=self.user.id)

        parent = TaskRun.objects.get(task_id='arch-d1')
        entry = parent.result_summary['results']['0']
        self.assertEqual(entry['study_id'], 'UID-A')
        self.assertEqual(entry['processed'], 0)
        self.assertEqual(entry['failed'], 0)
        self.assertIn('de-archival failed', entry['error'])
        child = TaskRun.objects.get(task_id='arch-d1-link0')
        self.assertEqual(child.status, TaskRun.Status.FAILURE)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python manage.py test deidentification.test_archive_hooks.ArchiveHookTests.test_guard_failure_records_parent_failure_and_advances_chain -v 2`
Expected: FAIL — `AttributeError: <module 'deidentification.tasks' ...> does not have the attribute 'ensure_studies_local'`.

- [ ] **Step 3: Implement the per-study guard**

In `deidentification/tasks.py`, first add `ensure_studies_local` to the import added in Task 1 — it becomes:

```python
from dicom_archive.services.dearchive import (
    dearchival_required_for_studies,
    dearchive_studies,
    ensure_studies_local,
)
```

Then, inside `deidentify_dicom_study_task`, replace this block (it appears once, right after the manifest read):

```python
        completed_items = read_manifest(manifest_path)

        def progress_callback(phase, cur, tot):
```

with:

```python
        completed_items = read_manifest(manifest_path)

        # Per-study archive safety net: the dispatcher restores the whole
        # roster up front, but a study can be archived between dispatch and
        # execution (e.g. by the nightly sweep). Ensure the local folder is
        # available before deidentify_study() reads it.
        state = ensure_studies_local([study_id]).get(study_id)
        if state == 'failed':
            guard_error = (
                f"Study {study_id} is archived and its local copy could not "
                f"be restored (de-archival failed) — deidentification skipped"
            )
            done_count = _deid_record_result(run_id, index, {
                'index': index,
                'study_id': study_id,
                'error': guard_error,
                'processed': 0,
                'failed': 0,
            })
            job.status = DeidentificationJob.Status.FAILURE
            job.error_log = guard_error
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'error_log', 'completed_at', 'updated_at'])
            _fail_task_run(child_run, guard_error)
            parent_progress(
                done_count,
                f"[{index + 1}/{total}] Study {study_id[:40]} — skipped (de-archival failed)",
                force=True,
            )
            _deid_dispatch_next(run_id, index, total, user_id)
            return {'status': 'failed', 'error': guard_error}

        def progress_callback(phase, cur, tot):
```

(`ensure_studies_local` is imported at module level; `job`, `child_run`, `study_id`, `total`, and `parent_progress` are all in scope at this point in the link body.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test deidentification.test_archive_hooks -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

Commit ONLY after explicit user approval of the overall implementation (global constraint — no git commits till approval):

```bash
git add deidentification/tasks.py deidentification/test_archive_hooks.py
git commit -m "feat(dicom_archive): per-study de-archival guard in deid chain link"
```

---

### Task 3: Complete the hook test suite — `deidentification/test_archive_hooks.py`

Tests (a) and (d) were written in the TDD cycles of Tasks 1 and 2. This task adds the remaining required coverage — (b) no archived studies means no de-archive dispatch, (c) de-archive failure fails the parent `TaskRun` — plus pass-through and multi-failure edge tests, and runs the whole file.

**Files:**
- Test: `deidentification/test_archive_hooks.py` (append four methods to `ArchiveHookTests`)

**Interfaces:**
- Consumes: everything produced by Tasks 1 and 2 (dispatcher hook behavior, guard behavior); `ArchivedStudy` rows built with the `_archive_study` helper; real `dearchival_required_for_studies` DB query (only `dearchive_studies` is patched).
- Produces: a complete regression-guarding suite; the four required scenarios (a)–(d) all present in `deidentification/test_archive_hooks.py`.

- [ ] **Step 1: Append the remaining tests**

Append the following four methods inside the `ArchiveHookTests` class in `deidentification/test_archive_hooks.py`, after the last method added in Task 2:

```python
    def test_bulk_deid_with_no_archived_studies_does_not_dispatch_dearchive(self):
        """(b) No ArchivedStudy rows in the roster => the real service returns
        [] and the dispatcher must not de-archive anything."""
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-b1',
            )

        mock_dearch.assert_not_called()
        mock_delay.assert_called_once_with('arch-b1', 0, user_id=self.user.id)
        self.assertEqual(res.result['status'], 'dispatched')

    def test_bulk_deid_dearchival_failure_fails_parent_run(self):
        """(c) De-archive reports a failure => parent TaskRun is FAILURE,
        the error names the study, and no deid link is dispatched."""
        from client_app.models import TaskRun

        self._archive_study(self.study_a, 'UID-A')
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            mock_dearch.return_value = {
                'dearchived': [],
                'failed': {'UID-A': 'archive source folder missing'},
            }
            res = self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-c1',
            )

        self.assertEqual(res.result['status'], 'failed')
        mock_task.delay.assert_called_once_with(['UID-A'])
        mock_delay.assert_not_called()
        parent = TaskRun.objects.get(task_id='arch-c1')
        self.assertEqual(parent.status, TaskRun.Status.FAILURE)
        self.assertIn('1 of 1', parent.error_log)
        self.assertIn('UID-A', parent.error_log)
        self.assertIn('archive source folder missing', parent.error_log)

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_guard_local_state_passes_through_to_deidentify(self, mock_deid):
        """Guard returns 'local' (nothing archived): the study deidentifies
        normally and the chain advances."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-e1')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'local'}) as mock_ensure, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-e1', 0], kwargs={'user_id': self.user.id},
                task_id='arch-e1-link0',
            )

        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_called_once()
        self.assertEqual(res.result['processed'], 5)
        mock_delay.assert_called_once_with('arch-e1', 1, user_id=self.user.id)
        child = TaskRun.objects.get(task_id='arch-e1-link0')
        self.assertEqual(child.status, TaskRun.Status.SUCCESS)

    @patch('deidentification.tasks.deidentify_study', return_value=(5, 0))
    def test_guard_dearchived_state_passes_through_to_deidentify(self, mock_deid):
        """Guard returns 'dearchived' (restored now): the study deidentifies
        normally and the chain advances."""
        from client_app.models import TaskRun

        self._make_parent(run_id='arch-e2')
        with patch('deidentification.tasks.ensure_studies_local',
                   return_value={'UID-A': 'dearchived'}) as mock_ensure, \
                patch.object(self.link_task, 'delay') as mock_delay:
            res = self.link_task.apply(
                args=['arch-e2', 0], kwargs={'user_id': self.user.id},
                task_id='arch-e2-link0',
            )

        mock_ensure.assert_called_once_with(['UID-A'])
        mock_deid.assert_called_once()
        self.assertEqual(res.result['processed'], 5)
        mock_delay.assert_called_once_with('arch-e2', 1, user_id=self.user.id)
        child = TaskRun.objects.get(task_id='arch-e2-link0')
        self.assertEqual(child.status, TaskRun.Status.SUCCESS)

    def test_bulk_deid_dearchival_partial_failure_message_lists_all_uids(self):
        """Dispatcher failure message lists every failed study (sorted)."""
        from client_app.models import TaskRun

        self._archive_study(self.study_a, 'UID-A')
        self._archive_study(self.study_b, 'UID-B')
        with patch('deidentification.tasks.dearchive_studies') as mock_dearch, \
                patch.object(self.link_task, 'delay') as mock_delay:
            mock_dearch.return_value = {
                'dearchived': [],
                'failed': {'UID-B': 'disk full', 'UID-A': 'timeout'},
            }
            self.bulk_task.apply(
                args=[['UID-A', 'UID-B']], kwargs={'user_id': self.user.id},
                task_id='arch-f1',
            )

        parent = TaskRun.objects.get(task_id='arch-f1')
        self.assertEqual(parent.status, TaskRun.Status.FAILURE)
        self.assertIn('2 of 2', parent.error_log)
        self.assertIn('UID-A — timeout', parent.error_log)
        self.assertIn('UID-B — disk full', parent.error_log)
        mock_delay.assert_not_called()
```

- [ ] **Step 2: Run the whole hook suite**

Run: `python manage.py test deidentification.test_archive_hooks -v 2`
Expected: PASS — 7 tests (`test_bulk_deid_dearchives_archived_studies_before_first_link`, `test_bulk_deid_with_no_archived_studies_does_not_dispatch_dearchive`, `test_bulk_deid_dearchival_failure_fails_parent_run`, `test_bulk_deid_dearchival_partial_failure_message_lists_all_uids`, `test_guard_failure_records_parent_failure_and_advances_chain`, `test_guard_local_state_passes_through_to_deidentify`, `test_guard_dearchived_state_passes_through_to_deidentify`).

- [ ] **Step 3: Commit**

Commit ONLY after explicit user approval of the overall implementation (global constraint — no git commits till approval):

```bash
git add deidentification/test_archive_hooks.py
git commit -m "test(dicom_archive): full archive-hook suite for the deid chain"
```

---

### Task 4: Verification — run the existing deidentification suite (no regression)

**Files:**
- Test: (none created; runs the existing `deidentification/tests.py` plus the new `deidentification/test_archive_hooks.py`)

**Interfaces:**
- Consumes: the modified `deidentification/tasks.py` from Tasks 1–2; the existing `DeidentificationChainTests` in `deidentification/tests.py` (untouched).
- Produces: proof that the hooks are no-ops when no `ArchivedStudy` rows exist — dispatcher tests (`test_dispatcher_creates_parent_and_dispatches_first_link`, `test_dispatcher_resume_skips_recorded_indices`, `test_dispatcher_finalizes_when_all_done`) and link tests (`test_link_records_result_and_dispatches_next`, `test_last_link_dispatches_finalize`, `test_link_failure_recorded_and_chain_continues`, `test_link_skips_already_recorded_index`) all still pass without any archive-related patching.

- [ ] **Step 1: Run the full deidentification test suite**

Run: `python manage.py test deidentification`
Expected: PASS — all existing tests in `deidentification.tests` plus all 7 tests in `deidentification.test_archive_hooks` (e.g. `Ran 19 tests ... OK`).

- [ ] **Step 2: Investigate if anything fails**

If any pre-existing test fails, the failure is caused by the new module-level `dicom_archive` imports or the two hooks. Check: (1) plan 01's app is registered in `INSTALLED_APPS`; (2) `dearchival_required_for_studies([] or no ARCHIVED rows)` returns `[]` and `ensure_studies_local` returns `{'<uid>': 'local'}` in a clean test DB. Fix the cause (plan 01 defect or a wrong import path in `deidentification/tasks.py`); never work around it by patching archive symbols into `deidentification/tests.py`.

---

## Self-Review

**1. Spec coverage** — mapping from the overview's "Deidentification hooks (plan 02)" to tasks:
- "Dispatcher hook — after the study roster is known and the parent TaskRun created, before dispatching the first link" → Task 1 (exact `dearchival_required_for_studies` / in-process `dearchive_studies(required)` shape; `failed` → `_fail_task_run` + return). ✓
- "Per-study safety net — after the study is loaded and before `deidentify_study(...)` is called: `ensure_studies_local([study_id])`; on `'failed'` record `_deid_record_result`, fail child run, then `_deid_dispatch_next`" → Task 2. ✓
- "Hooks live only in `deidentification/tasks.py`; no changes to deidentification models or permissions" → Global Constraints + the Files blocks (only `deidentification/tasks.py` modified). ✓
- Required tests (a)–(d) → (a) Task 1 Step 1, (b)+(c) Task 3 Step 1, (d) Task 2 Step 1; all use Django `TestCase`, patch `dicom_archive` services/tasks, and construct real `ArchivedStudy` rows + temp folders via `_archive_study`. ✓
- Regression proof → Task 4 (`python manage.py test deidentification`). ✓
- Gap check: none — the contract specifies no deid-side changes beyond the two hooks.

**2. Placeholder scan** — no "TBD"/"TODO"/"appropriate error handling"/"similar to Task N" in the plan; every code step contains complete, executable code (full test file in Task 1, full appended methods in Tasks 2–3, exact before/after hunks in Tasks 1–2); every run step states the exact command and expected outcome; every commit step states the explicit-user-approval precondition.

**3. Type/name consistency** — `dearchival_required_for_studies` returns `list[str]` consumed by `dearchive_studies(required)`; the in-process result dict `{'dearchived': [...], 'failed': {uid: str}}` matches the TaskRun failure-message code (`failed.items()`); `ensure_studies_local([study_id]).get(study_id)` yields one of `'local' | 'dearchived' | 'failed'`, and only `'failed'` branches (both pass-through states are tested in Task 3); entry keys recorded via `_deid_record_result` (`index`, `study_id`, `error`, `processed`, `failed`) match what `finalize_deidentification_batch_task` aggregates; `TaskRun.Status.FAILURE`, `TaskRun.TaskType.DEIDENTIFICATION`, `DeidentificationJob.Status.FAILURE`, `ArchivedStudy.Status.ARCHIVED`, `ArchivedStudy.Reason.SCHEDULED` all match the contract/model definitions.
