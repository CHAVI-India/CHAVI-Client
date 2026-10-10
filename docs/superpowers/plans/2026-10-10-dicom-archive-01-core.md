# DICOM Archive — Core (Plan 01) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `dicom_archive` Django app core: app scaffold, three models
(`ArchiveLocation`, `ArchiveConfiguration` singleton, `ArchivedStudy`),
path-based location/archive/de-archive services, Celery tasks tracked on
`client_app.TaskRun`, and django-celery-beat schedule sync.

**Architecture:** New app mirroring `dicom_server` patterns: a singleton
configuration model with a 30 s cache (like
`dicom_server.models.DICOMServerConfiguration`), pure file move/copy services
(no DICOM network transfer), Celery batch tasks using
`client_app.tasks` TaskRun helpers + `celery_progress.ProgressRecorder`, and a
`post_save` signal on `ArchiveConfiguration` that keeps a
`django_celery_beat.PeriodicTask` in sync (mirroring
`dicom_server/services/schedule_sync.py`).

**Tech Stack:** Django (repo venv, `./venv/bin/python`), Celery +
django-celery-beat (DatabaseScheduler), celery_progress, Django `TestCase`
(no pytest), default DB engine (sqlite locally / Postgres in prod).

**Spec:** `docs/superpowers/plans/2026-10-10-dicom-archive-00-overview.md`
(binding contract — exact model names/fields, function names, task names,
url names and permission names). Read it before implementing.

## Global Constraints

- All schema migrations are created with `python manage.py makemigrations` —
  never hand-edited.
- **No git commits until the user approves.** Every "Commit" step in this
  plan executes ONLY after explicit user approval of the overall
  implementation; until then, skip the commit step.
- Never edit existing migration files.
- No remote-DICOM (C-MOVE/C-GET) storage backend. Storage backends are
  path-based only: `LOCAL` (any folder) and `MOUNT` (mounted NAS/LAN share).
- `DICOMStudy.folder_path` is an **absolute** POSIX path string. Archive code
  must not re-join `MEDIA_ROOT` when touching study folders.
- Per-study failure isolation everywhere: one bad study must not fail a batch.
- New app registered in `chavi_client/settings.py` `INSTALLED_APPS` after
  `'dicom_server'`.
- Exact contract names — do not rename: `ArchiveLocation`,
  `ArchiveConfiguration`, `ArchivedStudy`, `resolve_location_path`,
  `prepare_location`, `study_age_days`, `candidate_studies`, `MANIFEST_NAME`,
  `ArchiveError`, `archive_study`, `archive_studies`,
  `dearchival_required_for_studies`, `dearchive_study`,
  `dearchive_studies`, `ensure_studies_local`, `archive_studies_task`,
  `dearchive_studies_task`, `task_scheduled_archive`, `sync_archive_schedule`,
  `SCHEDULE_TASK`, `PERIODIC_TASK_NAME`, `TaskRun.TaskType.DICOM_ARCHIVE`,
  `TaskRun.TaskType.DICOM_DEARCHIVE`,
  app_name `'dicom_archive'`.
- Run all commands with the repo venv: `./venv/bin/python manage.py ...`.
  Tests are Django `TestCase` under `dicom_archive/tests/`, run with
  `./venv/bin/python manage.py test dicom_archive -v 2`.

## Design notes (decisions where the contract is silent)

1. **`admin.py` and `signals.py` are stubs in Task A, filled in later tasks.**
   Django runs admin autodiscover at `django.setup()`, so an admin module that
   imports not-yet-existing models would break every management command
   (including Task A's own test run). Task A ships docstring-only stubs;
   Task B adds the ModelAdmin registrations and Task G adds the signal
   receiver. `AppConfig.ready()` already imports `dicom_archive.signals`
   from Task A so wiring is in place when the receiver lands.
2. **`ArchiveLocation.resolved_path` imports
   `dicom_archive.services.locations` inside the property body** (lazy
   import) so the model module is importable and testable in Task B, before
   `services/locations.py` exists in Task C.
3. **`sync_archive_schedule(config=None)` takes an optional config argument.**
   The contract signature `sync_archive_schedule() -> None` is preserved via
   the default (`config = config or ArchiveConfiguration.load()`). The
   `post_save` signal passes the saved instance because the signal fires
   during `save()` — before `save()` deletes the singleton's 30 s cache key —
   so `load()` inside the handler would read a stale copy.
4. **Django does not clear caches between tests.** Every test that reads
   `ArchiveConfiguration` starts with `reset_archive_config(...)` (from
   `dicom_archive/tests/utils.py`) or `cache.clear()` in `setUp`, otherwise a
   cached singleton instance survives the per-test DB rollback.
5. **`candidate_studies` implements the contract's
   `Coalesce(study_date, created_at)` age rule with `Q` joins**
   (`study_date__lte` when set, else `created_at__lte` of the same cutoff
   date). Same predicate, portable across sqlite and Postgres.
6. **Archiving never rewrites `DICOMStudy.folder_path`.** The study keeps its
   original absolute path; de-archive restores to exactly
   `ArchivedStudy.local_path_before`. Archive state is tracked on the
   `ArchivedStudy` record, not on the folder's absence.
7. **`ArchivedStudy.instance_count` counts `*.dcm` files** in the study
   folder (case-insensitive suffix). Test fixtures are plain text files
   named `*.dcm`, so no pydicom parsing is needed anywhere in this plan.
8. **After a de-archive, an empty per-patient directory may remain under the
   archive location.** It is harmless; no cleanup is performed (YAGNI).
9. **`chavi_client/urls.py` is NOT touched in this plan** — the plan-01 file
   map ships only the `dicom_archive/urls.py` stub. Plan 03 adds the
   `include()` and all view URLs.
10. **Celery task tests use `task.apply(args=..., task_id=...)`** (eager
    in-process execution), the same pattern as `deidentification/tests.py`;
    dispatch assertions use `patch.object(<task>, 'delay')`.
11. **Re-archival is allowed by design.** `candidate_studies` excludes only
    `ARCHIVING`/`ARCHIVED`/`DEARCHIVING` records, so a `DEARCHIVED` study that
    is again older than `archive_after_days` is archived again (scheduled or
    manual); the `ArchivedStudy` row is updated in place (upsert) with fresh
    timestamps. No archive history is kept (YAGNI).

---

### Task A: `dicom_archive` app scaffold + settings

**Files:**
- Create: `dicom_archive/__init__.py` (empty)
- Create: `dicom_archive/apps.py`
- Create: `dicom_archive/signals.py` (docstring stub — receiver added in Task G)
- Create: `dicom_archive/admin.py` (docstring stub — registrations added in Task B)
- Create: `dicom_archive/urls.py` (empty stub, `app_name = 'dicom_archive'`)
- Create: `dicom_archive/migrations/__init__.py` (empty)
- Create: `dicom_archive/services/__init__.py`
- Create: `dicom_archive/tests/__init__.py` (empty)
- Create: `dicom_archive/tests/utils.py`
- Create: `dicom_archive/tests/test_app_scaffold.py`
- Modify: `chavi_client/settings.py` (INSTALLED_APPS + timeout constant)

**Interfaces:**
- Consumes: `client_app.models.Patient` (PK = `patient_id` CharField),
  `client_app.models.DICOMStudy` (`study_instance_uid` PK, `patient` FK,
  `study_date` nullable DateField, `folder_path` nullable absolute path,
  `created_at`).
- Produces (used by every later task):
  - `dicom_archive.tests.utils.make_study(patient_id='ARCH001',
    study_uid='1.2.826.0.1.3.000099-ARCH-0001', tmp_root=None, n_files=3,
    study_date=None, study_description='Archive test study')
    -> (Patient, DICOMStudy, pathlib.Path)` — creates a Patient (get_or_create
    by `patient_id`), a `DICOMStudy`, and fake `*.dcm` text files at
    `<tmp_root>/processed_dicom/<patient_id>/<study_uid>/img_NN.dcm`;
    `study.folder_path` is the absolute string of that folder.
  - `dicom_archive.tests.utils.reset_archive_config(**fields)
    -> ArchiveConfiguration` — sets fields on the singleton via
    `instance.save()` (fires `post_save`) and returns a fresh `load()`
    (cache-bypassing).
  - `dicom_archive` registered in `INSTALLED_APPS` after `'dicom_server'`.

- [ ] **Step 1: Write the failing test**

Create `dicom_archive/tests/test_app_scaffold.py` — but first the package must
exist for the file to live; create the empty init files exactly as below in
Step 3. For now write the test file content (it will not import cleanly yet —
that is the point):

```python
from django.conf import settings
from django.test import SimpleTestCase


class AppScaffoldTests(SimpleTestCase):
    def test_app_registered_after_dicom_server(self):
        apps = list(settings.INSTALLED_APPS)
        self.assertIn('dicom_server', apps)
        self.assertIn('dicom_archive', apps)
        self.assertGreater(apps.index('dicom_archive'), apps.index('dicom_server'))

    def test_urls_stub(self):
        from dicom_archive import urls
        self.assertEqual(urls.app_name, 'dicom_archive')
        self.assertEqual(urls.urlpatterns, [])

    def test_app_config(self):
        from django.apps import apps as django_apps
        config = django_apps.get_app_config('dicom_archive')
        self.assertEqual(config.verbose_name, 'DICOM Archive')
        self.assertEqual(config.default_auto_field, 'django.db.models.BigAutoField')
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: ERROR — `No module named 'dicom_archive'` (test module cannot
import / app not installed).

- [ ] **Step 3: Create the scaffold files**

`dicom_archive/__init__.py`, `dicom_archive/migrations/__init__.py`,
`dicom_archive/tests/__init__.py` — all three are **empty files** (0 bytes).

`dicom_archive/apps.py`:

```python
from django.apps import AppConfig


class DicomArchiveConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dicom_archive'
    verbose_name = 'DICOM Archive'

    def ready(self):
        import dicom_archive.signals  # noqa: F401
```

`dicom_archive/signals.py` (stub — Task G replaces the body):

```python
"""Signal receivers for dicom_archive (loaded via DicomArchiveConfig.ready).

Stub — the post_save schedule-sync receiver is added by the schedule-sync
task. Kept importable from the scaffold step so AppConfig.ready() can
import it unconditionally."""
```

`dicom_archive/admin.py` (stub — Task B replaces it with registrations):

```python
"""Admin registrations for dicom_archive.

Stub — ModelAdmin registrations are added by the models task (they must
import the models, which do not exist until that task lands)."""
```

`dicom_archive/urls.py`:

```python
"""URLconf for dicom_archive.

Stub — view URLs are added by the frontend plan (03)."""

app_name = 'dicom_archive'

urlpatterns = []
```

`dicom_archive/services/__init__.py`:

```python
"""Service modules for dicom_archive (pure file operations, no DICOM network)."""
```

`dicom_archive/tests/utils.py`:

```python
"""Shared fixture helpers for dicom_archive tests.

Study folders are plain text files named ``*.dcm`` — file operations only,
no pydicom parsing (the services in this plan never parse DICOM).
"""
import tempfile
from pathlib import Path


def make_study(
    patient_id='ARCH001',
    study_uid='1.2.826.0.1.3.000099-ARCH-0001',
    tmp_root=None,
    n_files=3,
    study_date=None,
    study_description='Archive test study',
):
    """Create a Patient + DICOMStudy plus a temp folder of fake ``*.dcm``
    text files under a processed_dicom-style layout.

    Layout: ``<tmp_root>/processed_dicom/<patient_id>/<study_uid>/img_NN.dcm``.
    ``tmp_root`` defaults to a fresh tempdir (no automatic cleanup — pass a
    tmpdir you control when you need teardown).

    Returns ``(patient, study, study_dir)`` where ``study_dir`` is a
    ``pathlib.Path`` and ``study.folder_path`` is its absolute string.
    """
    from client_app.models import DICOMStudy, Patient, SiteConfiguration

    if tmp_root is None:
        tmp_root = Path(tempfile.mkdtemp(prefix='dicom_archive_'))
    study_dir = Path(tmp_root) / 'processed_dicom' / patient_id / study_uid
    study_dir.mkdir(parents=True, exist_ok=False)
    for i in range(n_files):
        (study_dir / f'img_{i:02d}.dcm').write_text(
            f'fake dicom content {i} for {study_uid}\n'
        )
    # Patient.center defaults to the first SiteConfiguration row
    # (get_default_site) and Patient.save() runs full_clean() — a site
    # row must exist in the (fresh) test database before any Patient.
    site, _ = SiteConfiguration.objects.get_or_create(
        chavi_center_id='TESTSITE',
        defaults={'center_name': 'Test site'},
    )
    patient, _ = Patient.objects.get_or_create(
        patient_id=patient_id, defaults={'center': site},
    )
    study = DICOMStudy.objects.create(
        patient=patient,
        study_instance_uid=study_uid,
        study_date=study_date,
        study_description=study_description,
        folder_path=str(study_dir.absolute()),
    )
    return patient, study, study_dir


def reset_archive_config(**fields):
    """Apply field updates to the ArchiveConfiguration singleton and return
    a fresh instance (bypassing the 30 s singleton cache).

    Uses ``instance.save()`` so the post_save signal chain runs exactly as
    in production. Must be the first config read in any test — Django does
    not clear caches between tests."""
    from dicom_archive.models import ArchiveConfiguration

    config, _ = ArchiveConfiguration.objects.get_or_create(pk=1)
    for key, value in fields.items():
        setattr(config, key, value)
    config.save()
    return ArchiveConfiguration.load()
```

- [ ] **Step 4: Modify `chavi_client/settings.py`**

Two edits in `chavi_client/settings.py`:

1. In `INSTALLED_APPS`, after the last entry `'dicom_server',` add
   `'dicom_archive',`:

```python
    'deidentification',
    'dicom_server',
    'dicom_archive',
]
```

2. Right after the `MEDIA_ROOT` / `MEDIA_URL` block (line ~328) there is nothing to add for this plan — the earlier draft's `DICOM_ARCHIVE_DEARCHIVE_TIMEOUT_SECONDS` setting was superseded when plan 02's dispatcher hook moved to an in-process `dearchive_studies()` call (celery forbids `result.get()` inside a task), and the setting was removed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: 4 tests PASS.

- [ ] **Step 6: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive chavi_client/settings.py
git commit -m "feat(dicom_archive): app scaffold, settings registration, test fixture helpers"
```

---

### Task B: models (`ArchiveLocation`, `ArchiveConfiguration`, `ArchivedStudy`) + TaskType additions + migration

**Files:**
- Create: `dicom_archive/models.py`
- Modify: `client_app/models.py` (TaskRun.TaskType, ~line 2296)
- Modify: `dicom_archive/admin.py` (replace Task A stub with registrations)
- Create: `dicom_archive/migrations/0001_initial.py` (via makemigrations)
- Create: `client_app/migrations/0030_*.py` (via makemigrations — choices-only AlterField)
- Test: `dicom_archive/tests/test_models.py`

**Interfaces:**
- Consumes: `dicom_archive.tests.utils.make_study`,
  `dicom_archive.tests.utils.reset_archive_config` (Task A);
  `client_app.models.TaskRun` (~line 2292), `client_app.models.DICOMStudy`
  (~line 231); `django.core.cache.cache`.
- Produces (exact contract shapes — later tasks import these):
  - `dicom_archive.models.ArchiveLocation` — fields `name` (unique
    CharField(100)), `storage_type` (`StorageType.LOCAL`/`MOUNT`), `path`
    (CharField(500)), `is_default`, `is_active`, `created_at`, `updated_at`;
    `clean()`; `resolved_path` property -> `pathlib.Path` (delegates to
    `services.locations.resolve_location_path` via lazy import);
    `Meta.ordering = ['name']`.
  - `dicom_archive.models.ArchiveConfiguration` — singleton mirroring
    `DICOMServerConfiguration`: fields `enabled`, `archive_after_days`,
    `delete_local_after_archive`, `archive_minute/hour/day_of_week/day_of_month/
    month_of_year`, `batch_limit`, `updated_at`; `CACHE_KEY =
    'dicom_archive_config'`; `save()` (pk forced to first row +
    `cache.delete`); `load()` classmethod (cache.get / get_or_create(pk=1) /
    cache.set 30 s); `crontab_tuple` property -> 5-tuple; `clean()` (cron
    field validation via `_CRON_FIELD_RE`).
  - `dicom_archive.models.ArchivedStudy` — `Status` (ARCHIVING/ARCHIVED/
    DEARCHIVING/DEARCHIVED), `Reason` (SCHEDULED/MANUAL), `study` OneToOne
    (`related_name='archive_record'`), `location` FK PROTECT
    (`related_name='archived_studies'`), `status`, `reason`,
    `local_path_before`, `archive_rel_path`, `size_bytes`,
    `instance_count`, `archived_at`, `dearchived_at`, `error_log`,
    `archived_by` FK auth.User SET_NULL, `created_at`, `updated_at`;
    `Meta.ordering = ['-id']`.
  - `client_app.models.TaskRun.TaskType.DICOM_ARCHIVE == 'DICOM_ARCHIVE'`,
    `TaskRun.TaskType.DICOM_DEARCHIVE == 'DICOM_DEARCHIVE'`.

- [ ] **Step 1: Add the two TaskType choices to `client_app/models.py`**

In `client_app/models.py`, inside `class TaskRun ... class TaskType
(models.TextChoices)`, after the `DEIDENTIFICATION` line add exactly:

```python
        DEIDENTIFICATION = 'DEIDENTIFICATION', 'Deidentification'
        DICOM_ARCHIVE = 'DICOM_ARCHIVE', 'DICOM Archive'
        DICOM_DEARCHIVE = 'DICOM_DEARCHIVE', 'DICOM De-archive'
```

- [ ] **Step 2: Write the failing tests**

Create `dicom_archive/tests/test_models.py`:

```python
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase

from client_app.models import TaskRun
from dicom_archive.models import ArchiveConfiguration, ArchivedStudy


class ArchiveConfigurationTests(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests

    def test_load_creates_singleton_with_defaults(self):
        config = ArchiveConfiguration.load()
        self.assertEqual(config.pk, 1)
        self.assertEqual(ArchiveConfiguration.objects.count(), 1)
        self.assertFalse(config.enabled)
        self.assertEqual(config.archive_after_days, 90)
        self.assertTrue(config.delete_local_after_archive)
        self.assertEqual(config.batch_limit, 25)
        self.assertEqual(config.crontab_tuple, ('0', '2', '*', '*', '*'))

    def test_save_keeps_single_row_and_invalidates_cache(self):
        first = ArchiveConfiguration.load()
        first.enabled = True
        first.archive_after_days = 30
        first.save()
        self.assertEqual(ArchiveConfiguration.objects.count(), 1)
        fresh = ArchiveConfiguration.load()
        self.assertEqual(fresh.pk, 1)
        self.assertTrue(fresh.enabled)
        self.assertEqual(fresh.archive_after_days, 30)

    def test_clean_accepts_default_cron_fields(self):
        config = ArchiveConfiguration.load()
        config.full_clean()  # no exception

    def test_clean_rejects_bad_cron_field(self):
        config = ArchiveConfiguration.load()
        config.archive_hour = '2pm'
        with self.assertRaises(ValidationError):
            config.clean()


class TaskTypeAdditionsTests(TestCase):
    def test_new_task_types(self):
        self.assertEqual(TaskRun.TaskType.DICOM_ARCHIVE, 'DICOM_ARCHIVE')
        self.assertEqual(TaskRun.TaskType.DICOM_DEARCHIVE, 'DICOM_DEARCHIVE')

    def test_archived_study_choices(self):
        self.assertEqual(ArchivedStudy.Status.ARCHIVED, 'ARCHIVED')
        self.assertEqual(ArchivedStudy.Status.DEARCHIVED, 'DEARCHIVED')
        self.assertEqual(ArchivedStudy.Reason.SCHEDULED, 'SCHEDULED')
        self.assertEqual(ArchivedStudy.Reason.MANUAL, 'MANUAL')

    def test_admin_registry(self):
        from django.contrib import admin
        from dicom_archive.models import ArchiveLocation
        self.assertIn(ArchiveLocation, admin.site._registry)
        self.assertIn(ArchiveConfiguration, admin.site._registry)
        self.assertIn(ArchivedStudy, admin.site._registry)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_models -v 2`
Expected: FAIL — `ImportError: cannot import name 'ArchiveConfiguration' from 'dicom_archive.models'` (module does not exist yet).

- [ ] **Step 4: Write `dicom_archive/models.py`**

```python
"""Models for the dicom_archive app.

Storage backends are path-based only (LOCAL folder or MOUNTed NAS/LAN
share) — no remote DICOM (C-MOVE/C-GET) storage is in scope.
"""
import re

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models


class ArchiveLocation(models.Model):
    """Where archived study folders are stored."""

    class StorageType(models.TextChoices):
        LOCAL = 'LOCAL', 'Local folder'
        MOUNT = 'MOUNT', 'Mounted share (NAS/LAN)'

    name = models.CharField(max_length=100, unique=True)
    storage_type = models.CharField(
        max_length=10, choices=StorageType.choices, default=StorageType.LOCAL,
    )
    path = models.CharField(
        max_length=500,
        help_text="LOCAL: absolute, or relative to MEDIA_ROOT. "
                  "MOUNT: must be an absolute path to the mounted share.",
    )
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        _ = self.resolved_path  # raises ValidationError for invalid paths

    @property
    def resolved_path(self) -> "pathlib.Path":
        from dicom_archive.services.locations import resolve_location_path
        return resolve_location_path(self)

    def __str__(self):
        return f"{self.name} ({self.storage_type})"

    class Meta:
        verbose_name = 'Archive Location'
        verbose_name_plural = 'Archive Locations'
        ordering = ['name']


class ArchiveConfiguration(models.Model):
    """Singleton archive policy — exact DICOMServerConfiguration pattern
    (pk forced to first row on save, CACHE_KEY, load() with 30 s cache).
    Always read via ArchiveConfiguration.load()."""

    enabled = models.BooleanField(default=False)
    archive_after_days = models.PositiveIntegerField(
        default=90,
        help_text='Archive studies older than this many days (from '
                  'study_date, falling back to created_at).',
    )
    delete_local_after_archive = models.BooleanField(
        default=True,
        help_text="True = delete the local study folder after a successful "
                  "archive (the folder is moved into the archive); "
                  "False = keep a local copy.",
    )
    archive_minute = models.CharField(max_length=20, default='0')
    archive_hour = models.CharField(max_length=20, default='2')
    archive_day_of_week = models.CharField(max_length=20, default='*')
    archive_day_of_month = models.CharField(max_length=20, default='*')
    archive_month_of_year = models.CharField(max_length=20, default='*')
    batch_limit = models.PositiveIntegerField(
        default=25, help_text='Maximum studies per scheduled run.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = 'dicom_archive_config'
    _CRON_FIELD_RE = re.compile(r'^[\d\-\,\*/]+$')

    def save(self, *args, **kwargs):
        if self.__class__.objects.count():
            self.pk = self.__class__.objects.first().pk
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def load(cls):
        config = cache.get(cls.CACHE_KEY)
        if config is None:
            config, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, config, 30)
        return config

    @property
    def crontab_tuple(self) -> tuple:
        return (
            self.archive_minute,
            self.archive_hour,
            self.archive_day_of_week,
            self.archive_day_of_month,
            self.archive_month_of_year,
        )

    def clean(self):
        super().clean()
        for name, value in [
            ('archive_minute', self.archive_minute),
            ('archive_hour', self.archive_hour),
            ('archive_day_of_week', self.archive_day_of_week),
            ('archive_day_of_month', self.archive_day_of_month),
            ('archive_month_of_year', self.archive_month_of_year),
        ]:
            if not self._CRON_FIELD_RE.match(value or ''):
                raise ValidationError({name: 'Invalid cron field value.'})

    def __str__(self):
        state = 'enabled' if self.enabled else 'disabled'
        return f"Archive config ({state}, >{self.archive_after_days}d)"

    class Meta:
        verbose_name = 'Archive Configuration'
        verbose_name_plural = 'Archive Configurations'
```

```python
# (continuation of dicom_archive/models.py — same file, append to end)

class ArchivedStudy(models.Model):
    """One archived study: location, state, and audit trail."""

    class Status(models.TextChoices):
        ARCHIVING = 'ARCHIVING', 'Archiving'
        ARCHIVED = 'ARCHIVED', 'Archived'
        DEARCHIVING = 'DEARCHIVING', 'De-archiving'
        DEARCHIVED = 'DEARCHIVED', 'De-archived'

    class Reason(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        MANUAL = 'MANUAL', 'Manual'

    study = models.OneToOneField(
        'client_app.DICOMStudy',
        on_delete=models.CASCADE,
        related_name='archive_record',
    )
    location = models.ForeignKey(
        'ArchiveLocation',
        on_delete=models.PROTECT,
        related_name='archived_studies',
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ARCHIVING,
    )
    reason = models.CharField(
        max_length=10, choices=Reason.choices, default=Reason.MANUAL,
    )
    local_path_before = models.CharField(
        max_length=500,
        help_text="study.folder_path (absolute) at archive time — "
                  "de-archive restores to exactly this path.",
    )
    archive_rel_path = models.CharField(
        max_length=500,
        help_text="'<patient_id>/<study_uid>' under the location's path.",
    )
    size_bytes = models.BigIntegerField(default=0)
    instance_count = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    dearchived_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True, default='')
    archived_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'Archived Study'
        verbose_name_plural = 'Archived Studies'

    def __str__(self):
        return f"{self.study.study_instance_uid} [{self.status}]"
```

- [ ] **Step 5: Replace the `dicom_archive/admin.py` stub with registrations**

```python
from django.contrib import admin
from unfold.admin import ModelAdmin

from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy


@admin.register(ArchiveLocation)
class ArchiveLocationAdmin(ModelAdmin):
    list_display = ['name', 'storage_type', 'path', 'is_default', 'is_active', 'updated_at']
    list_filter = ['storage_type', 'is_default', 'is_active']
    search_fields = ['name', 'path']


@admin.register(ArchiveConfiguration)
class ArchiveConfigurationAdmin(ModelAdmin):
    list_display = ['enabled', 'archive_after_days', 'delete_local_after_archive', 'batch_limit', 'updated_at']

    def has_add_permission(self, request):
        return not ArchiveConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ArchivedStudy)
class ArchivedStudyAdmin(ModelAdmin):
    list_display = ['study', 'location', 'status', 'reason', 'size_bytes', 'instance_count', 'archived_at', 'archived_by']
    list_filter = ['status', 'reason', 'location']
    search_fields = ['study__study_instance_uid']
    readonly_fields = [f.name for f in ArchivedStudy._meta.fields]

    def has_add_permission(self, request):
        return False
```

- [ ] **Step 6: Generate migrations (never hand-edit)**

Run: `./venv/bin/python manage.py makemigrations dicom_archive client_app`

Expected: two new migration files:
- `dicom_archive/migrations/0001_initial.py` — three `CreateModel`
  operations (`ArchiveLocation`, `ArchiveConfiguration`, `ArchivedStudy`).
- `client_app/migrations/0030_alter_taskrun_task_type.py` (number may vary —
  whatever `makemigrations` names it) — one `AlterField` on
  `taskrun.task_type` (choices-only change).

Verify the generated files, do NOT edit them:

```bash
grep -n "CreateModel\|ArchiveLocation\|ArchiveConfiguration\|ArchivedStudy" dicom_archive/migrations/0001_initial.py
ls client_app/migrations/ | tail -2
grep -n "AlterField" client_app/migrations/0030_alter_taskrun_task_type.py
```

If `makemigrations` produces anything unexpected (e.g. no `client_app`
migration, or a migration touching other fields), STOP and inspect — the
only expected changes are the three new models and the TaskRun choices.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: all tests PASS (test runner applies `0001_initial` + the
`client_app` choices migration to the test database).

- [ ] **Step 8: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/models.py dicom_archive/admin.py dicom_archive/migrations/0001_initial.py client_app/models.py client_app/migrations/0030_alter_taskrun_task_type.py dicom_archive/tests/test_models.py
git commit -m "feat(dicom_archive): ArchiveLocation/ArchiveConfiguration/ArchivedStudy models, TaskType additions"
```

---

### Task C: `dicom_archive/services/locations.py` (resolve / prepare / age / candidates)

**Files:**
- Create: `dicom_archive/services/locations.py`
- Test: `dicom_archive/tests/test_locations.py`

**Interfaces:**
- Consumes: `dicom_archive.models.ArchiveLocation` (incl.
  `StorageType`, `.path`), `ArchiveConfiguration` (`.archive_after_days`,
  `.load()`), `ArchivedStudy.Status` (Task B);
  `client_app.models.DICOMStudy`; `settings.MEDIA_ROOT`,
  `settings.TIME_ZONE`-aware `django.utils.timezone.localdate()`.
- Produces:
  - `resolve_location_path(location: ArchiveLocation) -> pathlib.Path` —
    LOCAL: `Path(location.path).expanduser()`, relative joined under
    `MEDIA_ROOT`; MOUNT: absolute required else
    `django.core.exceptions.ValidationError`; empty path → ValidationError.
  - `prepare_location(location: ArchiveLocation) -> pathlib.Path` — resolve,
    `mkdir(parents=True, exist_ok=True)`, write-permission probe via a temp
    file; raises `ValidationError` on failure.
  - `study_age_days(study) -> int | None` —
    `(timezone.localdate() - (study.study_date or study.created_at.date())).days`.
  - `candidate_studies(config: ArchiveConfiguration) ->
    django.db.models.QuerySet[client_app.models.DICOMStudy]` —
    `folder_path` not null, effective date (study_date else created_at) at
    least `config.archive_after_days` old, excluded when
    `archive_record__status` in (ARCHIVING, ARCHIVED, DEARCHIVING); ordered
    by `study_instance_uid`.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_locations.py`:

```python
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from client_app.models import DICOMStudy
from dicom_archive.models import (
    ArchiveConfiguration,
    ArchiveLocation,
    ArchivedStudy,
)
from dicom_archive.services.locations import (
    candidate_studies,
    prepare_location,
    resolve_location_path,
    study_age_days,
)
from dicom_archive.tests.utils import make_study, reset_archive_config


class LocationPathTestBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class ResolveLocationPathTests(LocationPathTestBase):
    def test_local_absolute_path_is_returned_unchanged(self):
        loc = ArchiveLocation.objects.create(
            name='abs', storage_type='LOCAL', path=str(self.tmp / 'abs'),
        )
        self.assertEqual(resolve_location_path(loc), self.tmp / 'abs')

    def test_local_relative_path_joins_media_root(self):
        loc = ArchiveLocation.objects.create(
            name='rel', storage_type='LOCAL', path='archives/stage1',
        )
        with override_settings(MEDIA_ROOT=str(self.tmp)):
            self.assertEqual(
                resolve_location_path(loc), self.tmp / 'archives' / 'stage1',
            )

    def test_mount_relative_path_raises(self):
        loc = ArchiveLocation.objects.create(
            name='nas-rel', storage_type='MOUNT', path='mnt/archive',
        )
        with self.assertRaises(ValidationError):
            resolve_location_path(loc)

    def test_mount_absolute_path_is_returned_unchanged(self):
        loc = ArchiveLocation.objects.create(
            name='nas-abs', storage_type='MOUNT', path=str(self.tmp / 'share'),
        )
        self.assertEqual(resolve_location_path(loc), self.tmp / 'share')

    def test_empty_path_raises(self):
        loc = ArchiveLocation.objects.create(name='empty', storage_type='LOCAL', path='')
        with self.assertRaises(ValidationError):
            resolve_location_path(loc)

    def test_model_clean_delegates_to_resolver(self):
        bad = ArchiveLocation(name='clean-mount', storage_type='MOUNT', path='rel/path')
        with self.assertRaises(ValidationError):
            bad.clean()
        ok = ArchiveLocation(name='clean-local', storage_type='LOCAL', path=str(self.tmp))
        ok.clean()  # no exception
```

```python
# (continuation of dicom_archive/tests/test_locations.py — same file, append)

class PrepareLocationTests(LocationPathTestBase):
    def test_creates_nested_directory_and_returns_path(self):
        loc = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL',
            path=str(self.tmp / 'arc' / 'root'),
        )
        base = prepare_location(loc)
        self.assertEqual(base, self.tmp / 'arc' / 'root')
        self.assertTrue(base.is_dir())

    def test_existing_directory_passes_write_probe(self):
        target = self.tmp / 'existing'
        target.mkdir()
        (target / 'old.txt').write_text('x')
        loc = ArchiveLocation.objects.create(
            name='existing', storage_type='LOCAL', path=str(target),
        )
        self.assertEqual(prepare_location(loc), target)
        self.assertTrue((target / 'old.txt').exists())


class StudyAgeDaysTests(TestCase):
    def test_age_from_study_date(self):
        patient, study, _ = make_study(
            study_date=date.today() - timedelta(days=120),
        )
        self.assertEqual(study_age_days(study), 120)

    def test_age_falls_back_to_created_at(self):
        patient, study, _ = make_study()  # study_date=None by default
        DICOMStudy.objects.filter(pk=study.pk).update(
            created_at=timezone.now() - timedelta(days=45),
        )
        study.refresh_from_db()
        self.assertEqual(study_age_days(study), 45)


class CandidateStudiesTests(LocationPathTestBase):
    def test_filters_by_age_folder_and_archive_state(self):
        reset_archive_config(archive_after_days=30)
        location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL', path=str(self.tmp / 'arc'),
        )

        _, old, _ = make_study(
            patient_id='PT1', study_uid='1.2.3.old', tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=120),
        )
        make_study(
            patient_id='PT2', study_uid='1.2.3.recent', tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=2),
        )
        _, undated, _ = make_study(
            patient_id='PT3', study_uid='1.2.3.undated', tmp_root=self.tmp / 'media',
        )
        DICOMStudy.objects.filter(pk=undated.pk).update(
            created_at=timezone.now() - timedelta(days=90),
        )
        _, no_folder, _ = make_study(
            patient_id='PT4', study_uid='1.2.3.nofolder', tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=120),
        )
        DICOMStudy.objects.filter(pk=no_folder.pk).update(folder_path=None)
        _, archived, _ = make_study(
            patient_id='PT5', study_uid='1.2.3.archived', tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=120),
        )
        ArchivedStudy.objects.create(
            study=archived, location=location,
            status=ArchivedStudy.Status.ARCHIVED,
            reason=ArchivedStudy.Reason.MANUAL,
            local_path_before='/x',
            archive_rel_path='PT5/1.2.3.archived',
        )

        config = ArchiveConfiguration.load()
        uids = list(
            candidate_studies(config)
            .values_list('study_instance_uid', flat=True)
        )
        self.assertEqual(uids, ['1.2.3.old', '1.2.3.undated'])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_locations -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'dicom_archive.services.locations'`.

- [ ] **Step 3: Write the minimal implementation**

Create `dicom_archive/services/locations.py`:

```python
"""Archive location path resolution and validation.

Storage backends are path-based only: LOCAL (any folder — absolute or
MEDIA_ROOT-relative) and MOUNT (mounted NAS/LAN share — must be absolute).
DICOMStudy.folder_path is always an absolute path; archive code never
re-joins MEDIA_ROOT when touching study folders.
"""
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from client_app.models import DICOMStudy
from dicom_archive.models import ArchiveConfiguration, ArchivedStudy, ArchiveLocation


def resolve_location_path(location: ArchiveLocation) -> Path:
    """Absolute Path for an ArchiveLocation.

    LOCAL: expanduser; a relative path is joined under MEDIA_ROOT.
    MOUNT: must already be absolute.
    Raises ValidationError on an empty path or a relative MOUNT path.
    """
    raw = (location.path or '').strip()
    if not raw:
        raise ValidationError(
            f"Archive location '{location.name}' has no path set."
        )
    resolved = Path(raw).expanduser()
    if location.storage_type == ArchiveLocation.StorageType.MOUNT:
        if not resolved.is_absolute():
            raise ValidationError({
                'path': (
                    f"Archive location '{location.name}' is a mounted share "
                    'and must use an absolute path.'
                ),
            })
        return resolved
    if not resolved.is_absolute():
        resolved = Path(settings.MEDIA_ROOT) / resolved
    return resolved
```

```python
# (continuation of dicom_archive/services/locations.py — same file, append)

def prepare_location(location: ArchiveLocation) -> Path:
    """Resolve the location, create it if needed, and prove it is writable.

    Raises ValidationError when the directory cannot be created or a
    probe file cannot be written into it.
    """
    base = resolve_location_path(location)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValidationError(
            f"Cannot create archive directory {base}: {exc}"
        ) from exc
    try:
        with tempfile.NamedTemporaryFile(dir=str(base), prefix='._archive_probe_'):
            pass
    except OSError as exc:
        raise ValidationError(
            f"Archive directory {base} is not writable: {exc}"
        ) from exc
    return base


def study_age_days(study) -> int | None:
    """Days since the study was performed (study_date) or, when the study
    has no date, since it was created (created_at)."""
    reference = study.study_date or study.created_at.date()
    return (timezone.localdate() - reference).days


def candidate_studies(config: ArchiveConfiguration) -> models.QuerySet:
    """Studies eligible for the scheduled archive sweep.

    A study is a candidate when: it still has a local folder
    (folder_path not null), its effective date (study_date, else
    created_at) is at least config.archive_after_days old, and it has no
    archive record in ARCHIVING / ARCHIVED / DEARCHIVING. A DEARCHIVED
    record keeps the study eligible again (its folder may have aged out
    again, or a local copy may have been re-created).
    """
    min_date = timezone.localdate() - timedelta(days=config.archive_after_days)
    return (
        DICOMStudy.objects
        .filter(folder_path__isnull=False)
        .filter(
            models.Q(study_date__isnull=False, study_date__lte=min_date)
            | models.Q(study_date__isnull=True, created_at__lte=min_date)
        )
        .exclude(
            archive_record__status__in=[
                ArchivedStudy.Status.ARCHIVING,
                ArchivedStudy.Status.ARCHIVED,
                ArchivedStudy.Status.DEARCHIVING,
            ]
        )
        .order_by('study_instance_uid')
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: all tests PASS, including the new `test_locations` suite.

- [ ] **Step 5: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/services/locations.py dicom_archive/tests/test_locations.py
git commit -m "feat(dicom_archive): location resolution/prepare, study age and candidate queries"
```

---

### Task D: `dicom_archive/services/archive.py` (archive_study / archive_studies)

**Files:**
- Create: `dicom_archive/services/archive.py`
- Test: `dicom_archive/tests/test_archive.py`

**Interfaces:**
- Consumes: `prepare_location` (Task C);
  `ArchiveConfiguration.load().delete_local_after_archive` (Task B);
  `ArchivedStudy` (Task B); `dicom_archive.tests.utils.make_study`,
  `reset_archive_config` (Task A); `study.folder_path` (absolute, set by
  `dicom_server.services.ingest`), `study.patient.patient_id`.
- Produces:
  - `MANIFEST_NAME = '_archive_manifest.json'`
  - `class ArchiveError(Exception)` — raised on any archive/de-archive
    failure.
  - `archive_study(study, location, user=None, reason='MANUAL')
    -> ArchivedStudy` — dest =
    `prepare_location(location) / sanitize(patient_id) / study_uid`;
    non-empty dest → ArchiveError; deletes the local folder (shutil.move) when
    `ArchiveConfiguration.load().delete_local_after_archive` else keeps a local copy (shutil.copytree);
    with the move policy the now-empty per-patient folder under
    processed_dicom is removed (never fatal; the processed_dicom root is
    never removed);
    writes the manifest `{study_instance_uid, patient_id, archived_at,
    file_count, size_bytes}` into dest; upserts
    `ArchivedStudy(study, location, status=ARCHIVED, reason,
    local_path_before, archive_rel_path, size_bytes, instance_count,
    archived_at=now, archived_by=user, error_log='')`.
  - `archive_studies(studies, location, user=None, reason='MANUAL')
    -> dict` — `{'archived': [uid, ...], 'failed': {uid: str(err)}}`,
    per-study `ArchiveError` isolation (never raises for per-study errors).

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_archive.py`:

```python
import json
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation, ArchivedStudy
from dicom_archive.services.archive import (
    MANIFEST_NAME,
    ArchiveError,
    archive_studies,
    archive_study,
)
from dicom_archive.tests.utils import make_study, reset_archive_config
```

```python
# (continuation of dicom_archive/tests/test_archive.py — same file, append)

class ArchiveTestBase(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL',
            path=str(self.tmp / 'archive'),
        )


class ArchiveStudyTests(ArchiveTestBase):
    def test_archive_moves_by_default(self):
        patient, study, src = make_study(
            patient_id='PT001', study_uid='1.2.3.4.5',
            tmp_root=self.tmp / 'media', n_files=3,
        )
        record = archive_study(study, self.location, reason='MANUAL')

        dest = self.tmp / 'archive' / 'PT001' / '1.2.3.4.5'
        self.assertFalse(src.exists())  # moved
        self.assertTrue(dest.is_dir())
        self.assertEqual(len(list(dest.glob('img_*.dcm'))), 3)

        manifest = json.loads((dest / MANIFEST_NAME).read_text())
        self.assertEqual(manifest['study_instance_uid'], '1.2.3.4.5')
        self.assertEqual(manifest['patient_id'], 'PT001')
        self.assertEqual(manifest['file_count'], 3)
        self.assertGreater(manifest['size_bytes'], 0)
        self.assertIn('archived_at', manifest)

        record.refresh_from_db()
        self.assertEqual(record.status, 'ARCHIVED')
        self.assertEqual(record.reason, 'MANUAL')
        self.assertEqual(record.local_path_before, str(src))
        self.assertEqual(record.archive_rel_path, 'PT001/1.2.3.4.5')
        self.assertEqual(record.instance_count, 3)
        self.assertGreater(record.size_bytes, 0)
        self.assertIsNotNone(record.archived_at)

    def test_archive_move_removes_empty_patient_folder_from_local(self):
        """With the default move policy, the per-patient folder under
        processed_dicom is removed once its last study is archived.
        The processed_dicom root itself stays."""
        patient, study, src = make_study(
            patient_id='PT030', study_uid='1.2.3.4.30',
            tmp_root=self.tmp / 'media',
        )
        patient_dir = src.parent
        processed_root = patient_dir.parent
        archive_study(study, self.location, reason='MANUAL')
        self.assertFalse(patient_dir.exists())
        self.assertTrue(processed_root.is_dir())

    def test_archive_move_keeps_patient_folder_with_other_studies(self):
        _, study_a, src_a = make_study(
            patient_id='PT031', study_uid='1.2.3.4.31',
            tmp_root=self.tmp / 'media',
        )
        _, study_b, src_b = make_study(
            patient_id='PT031', study_uid='1.2.3.4.32',
            tmp_root=self.tmp / 'media',
        )
        archive_study(study_a, self.location, reason='MANUAL')
        patient_dir = src_a.parent
        self.assertTrue(patient_dir.is_dir())  # still holds study .32
        self.assertEqual([p.name for p in patient_dir.iterdir()],
                         ['1.2.3.4.32'])

    def test_archive_copies_when_delete_disabled(self):
        reset_archive_config(delete_local_after_archive=False)
        patient, study, src = make_study(
            patient_id='PT002', study_uid='1.2.3.4.6',
            tmp_root=self.tmp / 'media',
        )
        archive_study(study, self.location)
        self.assertTrue(src.is_dir())  # copy leaves the source in place
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)
        # copy keeps the whole local layout, patient folder included
        self.assertTrue(src.parent.is_dir())
        dest = self.tmp / 'archive' / 'PT002' / '1.2.3.4.6'
        self.assertEqual(len(list(dest.glob('img_*.dcm'))), 3)

    def test_missing_local_folder_raises(self):
        patient, study, src = make_study(
            patient_id='PT003', study_uid='1.2.3.4.7',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(src)
        with self.assertRaises(ArchiveError):
            archive_study(study, self.location)
        self.assertFalse(
            ArchivedStudy.objects.filter(study=study).exists()
        )

    def test_non_empty_destination_raises(self):
        patient, study, src = make_study(
            patient_id='PT004', study_uid='1.2.3.4.8',
            tmp_root=self.tmp / 'media',
        )
        pre = self.tmp / 'archive' / 'PT004' / '1.2.3.4.8'
        pre.mkdir(parents=True)
        (pre / 'stray.dcm').write_text('stray')
        with self.assertRaises(ArchiveError):
            archive_study(study, self.location)
        self.assertTrue(src.is_dir())  # source untouched


class ArchiveStudiesBatchTests(ArchiveTestBase):
    def test_per_study_failure_isolation(self):
        make_study(
            patient_id='PT010', study_uid='1.2.3.4.10',
            tmp_root=self.tmp / 'media',
        )
        _, bad, bad_src = make_study(
            patient_id='PT011', study_uid='1.2.3.4.11',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(bad_src)

        from client_app.models import DICOMStudy
        studies = list(DICOMStudy.objects.filter(study_instance_uid__in=[
            '1.2.3.4.11', '1.2.3.4.10',
        ]))

        result = archive_studies(studies, self.location, reason='MANUAL')
        self.assertEqual(result['archived'], ['1.2.3.4.10'])
        self.assertIn('1.2.3.4.11', result['failed'])
        self.assertIn(
            'Local study folder missing', result['failed']['1.2.3.4.11'],
        )
        self.assertTrue((self.tmp / 'archive' / 'PT010' / '1.2.3.4.10').is_dir())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_archive -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'dicom_archive.services.archive'`.

- [ ] **Step 3: Write the minimal implementation**

Create `dicom_archive/services/archive.py`:

```python
"""File move/copy archiving of local DICOM study folders.

No DICOM network transfer — plain filesystem operations on the study
folders under MEDIA_ROOT/processed_dicom/<patient_id>/<study_uid>.
"""
import json
import logging
import re
import shutil
from pathlib import Path

from django.utils import timezone

from dicom_archive.models import ArchiveConfiguration, ArchivedStudy
from dicom_archive.services.locations import prepare_location

logger = logging.getLogger(__name__)

MANIFEST_NAME = '_archive_manifest.json'


class ArchiveError(Exception):
    """Raised when a study cannot be archived or de-archived."""


def _sanitize_segment(value: str) -> str:
    """Make a patient ID / UID safe for use as a single path segment."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', value or '') or 'unknown'


def _study_stats(folder: Path):
    """(file_count, size_bytes, instance_count) for a study folder.

    instance_count counts *.dcm files (case-insensitive); the manifest
    itself is excluded from file_count/size_bytes.
    """
    files = [
        p for p in folder.rglob('*') if p.is_file() and p.name != MANIFEST_NAME
    ]
    size_bytes = sum(p.stat().st_size for p in files)
    instance_count = len([p for p in files if p.suffix.lower() == '.dcm'])
    return len(files), size_bytes, instance_count


def archive_study(study, location, user=None, reason='MANUAL') -> ArchivedStudy:
    """Archive one local study folder into the given location.

    The delete-vs-keep policy is location-independent: it follows
    ArchiveConfiguration.delete_local_after_archive (True=move+delete local,
    False=copy+keep local). With the move policy the now-empty per-patient
    folder under processed_dicom is removed (never fatal; the
    processed_dicom root is never removed).
    Raises ArchiveError on any failure; per-study failure isolation is the
    caller's job (see archive_studies).
    """
    local = Path(study.folder_path) if study.folder_path else None
    if local is None or not local.is_dir():
        raise ArchiveError(
            f"Local study folder missing for "
            f"{study.study_instance_uid}: {study.folder_path!r}"
        )

    base = prepare_location(location)
    patient_segment = _sanitize_segment(study.patient.patient_id)
    dest = base / patient_segment / study.study_instance_uid
    if dest.exists() and any(dest.iterdir()):
        raise ArchiveError(f"Archive destination is not empty: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        config = ArchiveConfiguration.load()
        if config.delete_local_after_archive:
            shutil.move(str(local), str(dest))
        else:
            shutil.copytree(str(local), str(dest))
    except (OSError, shutil.Error) as exc:
        raise ArchiveError(
            f"Failed to copy study folder to {dest}: {exc}"
        ) from exc

    if config.delete_local_after_archive:
        # The local copy moved away: drop the now-empty per-patient folder
        # under processed_dicom (never fatal — cosmetic only; the
        # processed_dicom root itself is never removed).
        parent = local.parent
        try:
            if (parent.name != 'processed_dicom'
                    and parent.is_dir() and not any(parent.iterdir())):
                parent.rmdir()
        except OSError as exc:
            logger.warning(
                'Could not remove empty local patient folder %s: %s',
                parent, exc,
            )

    try:
        file_count, size_bytes, instance_count = _study_stats(dest)
        manifest = {
            'study_instance_uid': study.study_instance_uid,
            'patient_id': study.patient.patient_id,
            'archived_at': timezone.now().isoformat(),
            'file_count': file_count,
            'size_bytes': size_bytes,
        }
        (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    except OSError as exc:
        raise ArchiveError(
            f"Failed to write archive manifest in {dest}: {exc}"
        ) from exc

    record = ArchivedStudy.objects.filter(study=study).first()
    values = {
        'location': location,
        'status': ArchivedStudy.Status.ARCHIVED,
        'reason': reason,
        'local_path_before': str(local),
        'archive_rel_path': f"{patient_segment}/{study.study_instance_uid}",
        'size_bytes': size_bytes,
        'instance_count': instance_count,
        'archived_at': timezone.now(),
        'archived_by': user,
        'error_log': '',
    }
    if record:
        for field, value in values.items():
            setattr(record, field, value)
        record.save()
    else:
        record = ArchivedStudy.objects.create(study=study, **values)
    return record
```

```python
# (continuation of dicom_archive/services/archive.py — same file, append)

def archive_studies(studies, location, user=None, reason='MANUAL') -> dict:
    """Archive many studies with per-study failure isolation.

    Returns {'archived': [study_uid, ...], 'failed': {study_uid: error}}.
    One bad study never fails the rest of the batch.
    """
    archived = []
    failed = {}
    for study in studies:
        uid = study.study_instance_uid
        try:
            archive_study(study, location, user=user, reason=reason)
            archived.append(uid)
        except ArchiveError as exc:
            failed[uid] = str(exc)
            logger.error('Archive failed for %s: %s', uid, exc)
    return {'archived': archived, 'failed': failed}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: all tests PASS, including the new `test_archive` suite.

- [ ] **Step 5: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/services/archive.py dicom_archive/tests/test_archive.py
git commit -m "feat(dicom_archive): archive_study/archive_studies services with manifest"
```

---

### Task E: `dicom_archive/services/dearchive.py` (de-archive + ensure_studies_local)

**Files:**
- Create: `dicom_archive/services/dearchive.py`
- Test: `dicom_archive/tests/test_dearchive.py`

**Interfaces:**
- Consumes: `MANIFEST_NAME`, `ArchiveError` from
  `dicom_archive.services.archive` (Task D); `ArchiveLocation.resolved_path`
  (Task B); `ArchivedStudy` fields `archive_rel_path`,
  `local_path_before`, `status` (Task B); `archive_study` (Task D, used to
  build fixtures in tests).
- Produces:
  - `dearchival_required_for_studies(study_uids: list) -> list` — deduped,
    input-ordered uids whose `archive_record` status is `ARCHIVED`.
  - `dearchive_study(record: ArchivedStudy, user=None) -> ArchivedStudy` —
    src = `record.location.resolved_path / record.archive_rel_path` (missing
    → ArchiveError); dst = `Path(record.local_path_before)`; moves the
    folder back (merging without overwriting when dst is non-empty); removes
    `MANIFEST_NAME`; sets `status=DEARCHIVED`, `dearchived_at=now`, saves;
    leaves the record `ARCHIVED` on failure (retryable). After the study
    folder is moved out, the per-patient folder in the archive location is
    removed when empty (never fatal — cosmetic cleanup).
  - `dearchive_studies(study_uids, user=None) -> dict` —
    `{'dearchived': [uid, ...], 'failed': {uid: error}}`; uids with no
    ARCHIVED record are silently skipped; per-study isolation.
  - `ensure_studies_local(study_uids: list) -> dict` —
    `{uid: 'local' | 'dearchived' | 'failed'}` where 'local' means no
    ARCHIVED record exists.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_dearchive.py`:

```python
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation
from dicom_archive.services.archive import MANIFEST_NAME, archive_study
from dicom_archive.services.dearchive import (
    ArchiveError,
    dearchive_studies,
    dearchive_study,
    dearchival_required_for_studies,
    ensure_studies_local,
)
from dicom_archive.tests.utils import make_study


class DearchiveTestBase(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL',
            path=str(self.tmp / 'archive'),
        )

    def _archive_one(self, patient_id, study_uid):
        patient, study, src = make_study(
            patient_id=patient_id, study_uid=study_uid,
            tmp_root=self.tmp / 'media', n_files=3,
        )
        record = archive_study(study, self.location, reason='MANUAL')
        return record, patient, src
```

```python
# (continuation of dicom_archive/tests/test_dearchive.py — same file, append)

class DearchivalRequiredTests(DearchiveTestBase):
    def test_only_archived_records_require_dearchival(self):
        self._archive_one('PT001', '1.2.3.4.51')
        r_done, _, _ = self._archive_one('PT002', '1.2.3.4.52')
        dearchive_study(r_done)  # back to DEARCHIVED
        make_study(
            patient_id='PT003', study_uid='1.2.3.4.53',
            tmp_root=self.tmp / 'media',
        )  # no archive record at all

        required = dearchival_required_for_studies([
            '1.2.3.4.52', '1.2.3.4.51', '1.2.3.4.51',
            '1.2.3.4.53', '1.2.3.4.99',
        ])
        self.assertEqual(required, ['1.2.3.4.51'])


class DearchiveStudyTests(DearchiveTestBase):
    def test_dearchive_removes_empty_patient_folder_in_archive(self):
        """After the last study of a patient is de-archived, the empty
        per-patient folder in the archive location is removed."""
        record, patient, src = self._archive_one('PT013', '1.2.3.4.561')
        patient_dir = self.tmp / 'archive' / 'PT013'
        self.assertTrue(patient_dir.is_dir())
        dearchive_study(record)
        self.assertFalse(patient_dir.exists())

    def test_dearchive_keeps_patient_folder_with_other_studies(self):
        rec_a, patient, _ = self._archive_one('PT014', '1.2.3.4.562')
        rec_b, _, _ = self._archive_one('PT014', '1.2.3.4.563')
        dearchive_study(rec_a)
        patient_dir = self.tmp / 'archive' / 'PT014'
        self.assertTrue(patient_dir.is_dir())  # still holds study .563
        self.assertEqual(
            [p.name for p in patient_dir.iterdir()], ['1.2.3.4.563'])

    def test_dearchive_restores_files_and_updates_record(self):
        record, patient, src = self._archive_one('PT010', '1.2.3.4.54')
        result = dearchive_study(record)
        self.assertEqual(result.status, 'DEARCHIVED')
        self.assertIsNotNone(result.dearchived_at)
        self.assertTrue(src.is_dir())
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)
        self.assertFalse((src / MANIFEST_NAME).exists())
        self.assertFalse(
            (self.tmp / 'archive' / 'PT010' / '1.2.3.4.54').exists()
        )

    def test_dearchive_missing_archive_folder_raises(self):
        record, patient, src = self._archive_one('PT011', '1.2.3.4.55')
        shutil.rmtree(self.tmp / 'archive')
        with self.assertRaises(ArchiveError):
            dearchive_study(record)
        record.refresh_from_db()
        self.assertEqual(record.status, 'ARCHIVED')  # stays retryable

    def test_dearchive_merges_into_existing_local_folder(self):
        record, patient, src = self._archive_one('PT012', '1.2.3.4.56')
        src.mkdir(parents=True)  # patient re-ingested after archival
        (src / 'new_file.dcm').write_text('new')
        dearchive_study(record)
        self.assertTrue((src / 'new_file.dcm').exists())
        self.assertEqual(len(list(src.glob('img_*.dcm'))), 3)


class DearchiveStudiesBatchTests(DearchiveTestBase):
    def test_isolation_and_skips_non_archived(self):
        self._archive_one('PT020', '1.2.3.4.57')
        self._archive_one('PT021', '1.2.3.4.58')
        shutil.rmtree(self.tmp / 'archive' / 'PT021' / '1.2.3.4.58')
        make_study(
            patient_id='PT022', study_uid='1.2.3.4.59',
            tmp_root=self.tmp / 'media',
        )

        result = dearchive_studies([
            '1.2.3.4.57', '1.2.3.4.58', '1.2.3.4.59',
        ])
        self.assertEqual(result['dearchived'], ['1.2.3.4.57'])
        self.assertIn('1.2.3.4.58', result['failed'])
        self.assertNotIn('1.2.3.4.59', result['dearchived'])
        self.assertNotIn('1.2.3.4.59', result['failed'])


class EnsureStudiesLocalTests(DearchiveTestBase):
    def test_local_dearchived_and_failed_states(self):
        self._archive_one('PT030', '1.2.3.4.60')
        self._archive_one('PT031', '1.2.3.4.61')
        shutil.rmtree(self.tmp / 'archive' / 'PT031' / '1.2.3.4.61')
        make_study(
            patient_id='PT032', study_uid='1.2.3.4.62',
            tmp_root=self.tmp / 'media',
        )

        mapping = ensure_studies_local([
            '1.2.3.4.60', '1.2.3.4.61', '1.2.3.4.62',
        ])
        self.assertEqual(mapping, {
            '1.2.3.4.60': 'dearchived',
            '1.2.3.4.61': 'failed',
            '1.2.3.4.62': 'local',
        })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_dearchive -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'dicom_archive.services.dearchive'`.

- [ ] **Step 3: Write the minimal implementation**

Create `dicom_archive/services/dearchive.py`:

```python
"""De-archival (restore) of previously archived study folders."""
import logging
import shutil
from pathlib import Path

from django.utils import timezone

from dicom_archive.models import ArchivedStudy
from dicom_archive.services.archive import MANIFEST_NAME, ArchiveError

logger = logging.getLogger(__name__)


def dearchival_required_for_studies(study_uids: list) -> list:
    """Deduped, input-ordered uids whose archive record is currently
    ARCHIVED — i.e., the study lives in the archive, not locally."""
    seen = list(dict.fromkeys(study_uids))
    archived = set(
        ArchivedStudy.objects
        .filter(
            study__study_instance_uid__in=seen,
            status=ArchivedStudy.Status.ARCHIVED,
        )
        .values_list('study__study_instance_uid', flat=True)
    )
    return [uid for uid in seen if uid in archived]


def dearchive_study(record: ArchivedStudy, user=None) -> ArchivedStudy:
    """Move one archived study back to record.local_path_before.

    The archive manifest is dropped during the move. If the local folder
    already exists (e.g., the patient was re-ingested), incoming items are
    merged in without overwriting existing local files (colliding names get
    a numbered suffix). On any failure the record stays ARCHIVED so the
    de-archive can be retried.
    """
    src = record.location.resolved_path / record.archive_rel_path
    if not src.is_dir():
        raise ArchiveError(
            f"Archive folder missing for {record.study_id}: {src}"
        )
    dst = Path(record.local_path_before)

    try:
        dst.mkdir(parents=True, exist_ok=True)
        for item in sorted(src.iterdir()):
            if item.name == MANIFEST_NAME:
                item.unlink()
                continue
            target = dst / item.name
            if target.exists():
                for index in range(1, 1000):
                    candidate = f"{item.name}__archive_{index}"
                    if not (dst / candidate).exists():
                        target = dst / candidate
                        break
                else:
                    raise ArchiveError(
                        f"Cannot resolve name collision for "
                        f"{item.name} in {dst}"
                    )
            shutil.move(str(item), str(target))
        src.rmdir()
    except ArchiveError:
        raise
    except (OSError, shutil.Error) as exc:
        raise ArchiveError(
            f"Failed to de-archive {record.study_id}: {exc}"
        ) from exc

    # Tidy up: drop the per-patient folder in the archive location when the
    # de-archived study was its only occupant (never fatal — cosmetic only).
    parent = src.parent
    try:
        if (parent != record.location.resolved_path
                and parent.is_dir() and not any(parent.iterdir())):
            parent.rmdir()
    except OSError as exc:
        logger.warning(
            'Could not remove empty archive patient folder %s: %s',
            parent, exc,
        )

    record.status = ArchivedStudy.Status.DEARCHIVED
    record.dearchived_at = timezone.now()
    record.save(update_fields=['status', 'dearchived_at', 'updated_at'])
    return record


def dearchive_studies(study_uids, user=None) -> dict:
    """De-archive every requested uid that is actually ARCHIVED, with
    per-study failure isolation. Returns
    {'dearchived': [uid, ...], 'failed': {uid: error}}.
    Uids with no ARCHIVED record are silently skipped (already local)."""
    dearchived = []
    failed = {}
    records = {
        record.study_id: record
        for record in ArchivedStudy.objects
        .filter(
            study__study_instance_uid__in=list(study_uids),
            status=ArchivedStudy.Status.ARCHIVED,
        )
        .select_related('location', 'study')
    }
    for uid in study_uids:
        record = records.get(uid)
        if record is None:
            continue
        try:
            dearchive_study(record, user=user)
            dearchived.append(uid)
        except ArchiveError as exc:
            failed[uid] = str(exc)
            logger.error('De-archive failed for %s: %s', uid, exc)
    return {'dearchived': dearchived, 'failed': failed}


def ensure_studies_local(study_uids: list) -> dict:
    """Make sure each study's files are on local disk.

    Returns {uid: 'local' | 'dearchived' | 'failed'} — 'local' when the
    study has no ARCHIVED record, 'dearchived' when it was just restored,
    'failed' when the restore could not complete.
    """
    required = set(dearchival_required_for_studies(study_uids))
    outcome = dearchive_studies(sorted(required)) if required else {}
    failed = set(outcome.get('failed', {}))
    return {
        uid: (
            'failed' if uid in failed
            else 'dearchived' if uid in required
            else 'local'
        )
        for uid in dict.fromkeys(study_uids)
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: all tests PASS, including the new `test_dearchive` suite.

- [ ] **Step 5: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/services/dearchive.py dicom_archive/tests/test_dearchive.py
git commit -m "feat(dicom_archive): de-archive services and ensure_studies_local"
```

---

### Task F: `dicom_archive/tasks.py` (Celery tasks + TaskRun tracking)

**Files:**
- Create: `dicom_archive/tasks.py`
- Test: `dicom_archive/tests/test_tasks.py`

**Interfaces:**
- Consumes: `client_app.tasks._create_task_run / _update_task_run /
  _complete_task_run / _fail_task_run` (exact signatures in
  `client_app/tasks.py` lines 53–146);
  `celery_progress.backend.ProgressRecorder`;
  `TaskRun.TaskType.DICOM_ARCHIVE` / `DICOM_DEARCHIVE` (Task B);
  `archive_studies` (Task D), `dearchive_studies` (Task E),
  `candidate_studies` (Task C); `ArchiveConfiguration.load()` (Task B);
  `ArchiveLocation`, `ArchivedStudy.Reason.SCHEDULED` (Task B).
- Produces:
  - `@shared_task(bind=True) archive_studies_task(self, study_uids: list,
    location_id: int, user_id=None, reason='MANUAL') -> dict` —
    `TaskRun(task_name='archive_studies',
    task_type=TaskRun.TaskType.DICOM_ARCHIVE)`; returns
    `{'archived': [...], 'failed': {...}}`.
  - `@shared_task(bind=True) dearchive_studies_task(self, study_uids: list,
    user_id=None) -> dict` —
    `TaskRun(task_name='dearchive_studies',
    task_type=TaskRun.TaskType.DICOM_DEARCHIVE)`; returns
    `{'dearchived': [...], 'failed': {...}}`.
  - `@shared_task task_scheduled_archive(self, user_id=None) -> dict` —
    called by the beat PeriodicTask with `args=[None]` (hence the leading
    positional `self`); returns `{'status': 'disabled'}` when config
    disabled, `{'status': 'nothing_to_do'}` with no active location,
    `{'status': 'empty'}` with no on-disk candidates, else
    `{'status': 'dispatched', 'study_uids': [...], 'location_id': int}`
    after `archive_studies_task.delay(uids, location.pk, user_id=user_id,
    reason=ArchivedStudy.Reason.SCHEDULED)`.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_tasks.py`:

```python
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from client_app.models import TaskRun
from dicom_archive.models import ArchiveLocation
from dicom_archive.tasks import (
    archive_studies_task,
    dearchive_studies_task,
    task_scheduled_archive,
)
from dicom_archive.tests.utils import make_study, reset_archive_config


class TaskTestBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.location = ArchiveLocation.objects.create(
            name='primary', storage_type='LOCAL', is_default=True,
            path=str(self.tmp / 'archive'),
        )
```

```python
# (continuation of dicom_archive/tests/test_tasks.py — same file, append)

class ScheduledArchiveTaskTests(TaskTestBase):
    def test_disabled_config_dispatches_nothing(self):
        reset_archive_config(enabled=False)
        self.assertEqual(task_scheduled_archive(None), {'status': 'disabled'})
        self.assertFalse(TaskRun.objects.exists())

    def test_no_active_location(self):
        self.location.delete()
        reset_archive_config(enabled=True)
        self.assertEqual(
            task_scheduled_archive(None), {'status': 'nothing_to_do'},
        )

    def test_no_candidates(self):
        reset_archive_config(enabled=True, archive_after_days=30)
        make_study(
            patient_id='PT100', study_uid='1.2.3.4.70',
            tmp_root=self.tmp / 'media',
            study_date=date.today() - timedelta(days=2),
        )
        self.assertEqual(task_scheduled_archive(None), {'status': 'empty'})
        self.assertFalse(TaskRun.objects.exists())

    def test_dispatches_correct_uids_with_scheduled_reason(self):
        reset_archive_config(
            enabled=True, archive_after_days=30, batch_limit=2,
        )
        old = date.today() - timedelta(days=120)
        uids = []
        for i in range(3):
            _, study, _ = make_study(
                patient_id=f'PT1{i:02d}', study_uid=f'1.2.3.4.8{i}',
                tmp_root=self.tmp / 'media', study_date=old,
            )
            uids.append(study.study_instance_uid)

        with patch.object(archive_studies_task, 'delay') as mock_delay:
            result = task_scheduled_archive(None)

        self.assertEqual(result['status'], 'dispatched')
        self.assertEqual(result['study_uids'], uids[:2])
        self.assertEqual(result['location_id'], self.location.pk)
        mock_delay.assert_called_once()
        args, kwargs = mock_delay.call_args
        self.assertEqual(args[0], uids[:2])
        self.assertEqual(args[1], self.location.pk)
        self.assertIsNone(kwargs.get('user_id'))
        self.assertEqual(kwargs.get('reason'), 'SCHEDULED')


class ArchiveStudiesTaskTests(TaskTestBase):
    def test_archive_task_records_success_with_partial_failure(self):
        make_study(
            patient_id='PT200', study_uid='1.2.3.4.90',
            tmp_root=self.tmp / 'media',
        )
        _, bad, bad_src = make_study(
            patient_id='PT201', study_uid='1.2.3.4.91',
            tmp_root=self.tmp / 'media',
        )
        shutil.rmtree(bad_src)

        result = archive_studies_task.apply(
            args=[['1.2.3.4.91', '1.2.3.4.90'], self.location.pk],
            kwargs={'user_id': None, 'reason': 'MANUAL'},
            task_id='arch-1',
        )

        self.assertEqual(result.result['archived'], ['1.2.3.4.90'])
        self.assertIn('1.2.3.4.91', result.result['failed'])
        run = TaskRun.objects.get(task_id='arch-1')
        self.assertEqual(run.status, TaskRun.Status.SUCCESS)
        self.assertEqual(run.task_type, TaskRun.TaskType.DICOM_ARCHIVE)
        self.assertEqual(run.task_name, 'archive_studies')
        self.assertEqual(run.result_summary['archived'], ['1.2.3.4.90'])


class DearchiveStudiesTaskTests(TaskTestBase):
    def test_dearchive_task_records_success(self):
        make_study(
            patient_id='PT300', study_uid='1.2.3.4.92',
            tmp_root=self.tmp / 'media',
        )
        from dicom_archive.services.archive import archive_study
        from client_app.models import DICOMStudy
        study = DICOMStudy.objects.get(study_instance_uid='1.2.3.4.92')
        archive_study(study, self.location, reason='SCHEDULED')

        result = dearchive_studies_task.apply(
            args=[['1.2.3.4.92']], kwargs={'user_id': None},
            task_id='dearch-1',
        )

        self.assertEqual(result.result['dearchived'], ['1.2.3.4.92'])
        run = TaskRun.objects.get(task_id='dearch-1')
        self.assertEqual(run.status, TaskRun.Status.SUCCESS)
        self.assertEqual(run.task_type, TaskRun.TaskType.DICOM_DEARCHIVE)
        self.assertEqual(run.task_name, 'dearchive_studies')
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_tasks -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'dicom_archive.tasks'`.

- [ ] **Step 3: Write the minimal implementation**

Create `dicom_archive/tasks.py`:

```python
"""Celery tasks for archive / de-archive runs (tracked on client_app.TaskRun).

Per-study failures are captured in the result's 'failed' map; the TaskRun
is SUCCESS when the batch itself ran, mirroring the retrieval tasks in
dicom_server/tasks.py.
"""
import logging
from pathlib import Path

from celery import shared_task
from celery_progress.backend import ProgressRecorder
from django.contrib.auth import get_user_model

from client_app.models import DICOMStudy, TaskRun
from client_app.tasks import (
    _complete_task_run,
    _create_task_run,
    _fail_task_run,
    _update_task_run,
)
from dicom_archive.models import (
    ArchiveConfiguration,
    ArchiveLocation,
    ArchivedStudy,
)
from dicom_archive.services.archive import archive_studies
from dicom_archive.services.dearchive import dearchive_studies
from dicom_archive.services.locations import candidate_studies

logger = logging.getLogger(__name__)


def _user_for(user_id):
    if not user_id:
        return None
    return get_user_model().objects.filter(id=user_id).first()


@shared_task(bind=True)
def archive_studies_task(self, study_uids, location_id, user_id=None, reason='MANUAL') -> dict:
    """Archive a batch of local studies into one ArchiveLocation."""
    progress_recorder = ProgressRecorder(self)
    task_run = _create_task_run(
        task_name='archive_studies',
        task_type=TaskRun.TaskType.DICOM_ARCHIVE,
        user_id=user_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )
    try:
        location = ArchiveLocation.objects.get(pk=location_id)
        studies = list(
            DICOMStudy.objects.filter(study_instance_uid__in=study_uids)
        )
        _update_task_run(
            task_run, progress_recorder, 0, max(len(studies), 1),
            description='Archiving',
        )
        result = archive_studies(
            studies, location, user=_user_for(user_id), reason=reason,
        )
        _update_task_run(
            task_run, progress_recorder,
            max(len(studies), 1), max(len(studies), 1),
            description='Done',
        )
        _complete_task_run(task_run, result)
        return result
    except Exception as exc:
        logger.exception('Archive batch failed')
        _fail_task_run(task_run, exc)
        raise


@shared_task(bind=True)
def dearchive_studies_task(self, study_uids, user_id=None) -> dict:
    """Restore a batch of archived studies to their original local folders."""
    progress_recorder = ProgressRecorder(self)
    task_run = _create_task_run(
        task_name='dearchive_studies',
        task_type=TaskRun.TaskType.DICOM_DEARCHIVE,
        user_id=user_id,
        celery_task_id=self.request.id,
        task_args=self.request.args,
        task_kwargs=self.request.kwargs,
    )
    try:
        _update_task_run(
            task_run, progress_recorder, 0, max(len(study_uids), 1),
            description='De-archiving',
        )
        result = dearchive_studies(list(study_uids), user=_user_for(user_id))
        _update_task_run(
            task_run, progress_recorder,
            max(len(study_uids), 1), max(len(study_uids), 1),
            description='Done',
        )
        _complete_task_run(task_run, result)
        return result
    except Exception as exc:
        logger.exception('De-archive batch failed')
        _fail_task_run(task_run, exc)
        raise
```

```python
# (continuation of dicom_archive/tasks.py — same file, append)

@shared_task
def task_scheduled_archive(self, user_id=None) -> dict:
    """Celery Beat entry point for the periodic archive sweep.

    Dispatched by the django-celery-beat PeriodicTask with
    args=[None], hence the leading positional ``self`` parameter.
    Takes up to config.batch_limit oldest eligible studies whose folder
    still exists on disk and dispatches archive_studies_task against the
    default active location (else the first active location).
    """
    config = ArchiveConfiguration.load()
    if not config.enabled:
        return {'status': 'disabled'}

    location = ArchiveLocation.objects.filter(
        is_active=True, is_default=True,
    ).first()
    if location is None:
        location = ArchiveLocation.objects.filter(
            is_active=True,
        ).order_by('name').first()
    if location is None:
        return {'status': 'nothing_to_do'}

    candidates = [
        study
        for study in candidate_studies(config).order_by('study_instance_uid')
        if study.folder_path and Path(study.folder_path).is_dir()
    ][:config.batch_limit]
    if not candidates:
        return {'status': 'empty'}

    study_uids = [study.study_instance_uid for study in candidates]
    archive_studies_task.delay(
        study_uids, location.pk, user_id=user_id,
        reason=ArchivedStudy.Reason.SCHEDULED,
    )
    return {
        'status': 'dispatched',
        'study_uids': study_uids,
        'location_id': location.pk,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: all tests PASS, including the new `test_tasks` suite.

- [ ] **Step 5: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/tasks.py dicom_archive/tests/test_tasks.py
git commit -m "feat(dicom_archive): archive/de-archive Celery tasks and scheduled sweep entry point"
```

---

### Task G: schedule sync (`schedule_sync.py`) + `post_save` signal wiring

**Files:**
- Create: `dicom_archive/services/schedule_sync.py`
- Modify: `dicom_archive/signals.py` (replace Task A stub with the receiver)
- Test: `dicom_archive/tests/test_schedule_sync.py`

**Interfaces:**
- Consumes: `ArchiveConfiguration.load()` / `.enabled` / `.crontab_tuple` /
  the five `archive_*` cron fields (Task B);
  `django_celery_beat.models.CrontabSchedule`, `PeriodicTask`;
  `settings.TIME_ZONE` (mirrors `dicom_server/services/schedule_sync.py`).
- Produces:
  - `SCHEDULE_TASK = 'dicom_archive.tasks.task_scheduled_archive'`
  - `PERIODIC_TASK_NAME = 'dicom-archive-scheduled-sweep'`
  - `sync_archive_schedule(config=None) -> None` — when disabled:
    `PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).update(enabled=False)`
    and return; else `CrontabSchedule.objects.get_or_create(*cron fields,
    timezone=str(settings.TIME_ZONE))` +
    `PeriodicTask.objects.update_or_create(name=PERIODIC_TASK_NAME,
    defaults={'task': SCHEDULE_TASK, 'args': json.dumps([None]),
    'crontab': crontab, 'enabled': True, 'expire_seconds': 3600})`.
  - `dicom_archive.signals._sync_archive_schedule_on_save` — `post_save`
    receiver on `ArchiveConfiguration` calling `sync_archive_schedule(instance)`
    inside try/except-`logger.exception` (the instance is passed because the
    signal fires before `save()` clears the singleton cache — see Design
    notes, item 3).

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_schedule_sync.py`:

```python
import json

from django.test import TestCase
from django_celery_beat.models import PeriodicTask

from dicom_archive.models import ArchiveConfiguration
from dicom_archive.services.schedule_sync import (
    PERIODIC_TASK_NAME,
    SCHEDULE_TASK,
    sync_archive_schedule,
)
from dicom_archive.tests.utils import reset_archive_config


class SyncArchiveScheduleTests(TestCase):
    def test_enabled_creates_periodic_task(self):
        reset_archive_config(
            enabled=True, archive_minute='15', archive_hour='3',
        )
        sync_archive_schedule()
        pt = PeriodicTask.objects.get(name=PERIODIC_TASK_NAME)
        self.assertTrue(pt.enabled)
        self.assertEqual(pt.task, SCHEDULE_TASK)
        self.assertEqual(
            pt.task, 'dicom_archive.tasks.task_scheduled_archive',
        )
        self.assertEqual(pt.args, json.dumps([None]))
        self.assertEqual(pt.expire_seconds, 3600)
        self.assertEqual(pt.crontab.minute, '15')
        self.assertEqual(pt.crontab.hour, '3')
        self.assertEqual(pt.crontab.day_of_week, '*')
        self.assertEqual(pt.crontab.day_of_month, '*')
        self.assertEqual(pt.crontab.month_of_year, '*')

    def test_disabled_disables_periodic_task(self):
        reset_archive_config(enabled=True)
        sync_archive_schedule()
        reset_archive_config(enabled=False)
        sync_archive_schedule()
        self.assertFalse(
            PeriodicTask.objects.get(name=PERIODIC_TASK_NAME).enabled,
        )

    def test_disabled_without_existing_task_is_noop(self):
        reset_archive_config(enabled=False)
        sync_archive_schedule()
        self.assertFalse(
            PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).exists(),
        )


class ArchiveConfigurationSignalTests(TestCase):
    def test_post_save_signal_syncs_schedule(self):
        # The post_save receiver (dicom_archive.signals, wired in
        # DicomArchiveConfig.ready) must keep the PeriodicTask in sync
        # without an explicit sync_archive_schedule() call.
        config = ArchiveConfiguration.load()
        config.enabled = True
        config.archive_minute = '45'
        config.save()
        self.assertTrue(
            PeriodicTask.objects.filter(
                name=PERIODIC_TASK_NAME, enabled=True,
            ).exists(),
        )

    def test_post_save_signal_disables_when_turned_off(self):
        config = ArchiveConfiguration.load()
        config.enabled = True
        config.save()
        config.refresh_from_db()
        config.enabled = False
        config.save()
        self.assertFalse(
            PeriodicTask.objects.get(name=PERIODIC_TASK_NAME).enabled,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_schedule_sync -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'dicom_archive.services.schedule_sync'`.

- [ ] **Step 3: Write the minimal implementation**

Create `dicom_archive/services/schedule_sync.py`:

```python
"""Keep the django_celery_beat.PeriodicTask row in sync with the
ArchiveConfiguration schedule (mirrors dicom_server.services.schedule_sync)."""
import json
import logging

from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from dicom_archive.models import ArchiveConfiguration

logger = logging.getLogger(__name__)

SCHEDULE_TASK = 'dicom_archive.tasks.task_scheduled_archive'
PERIODIC_TASK_NAME = 'dicom-archive-scheduled-sweep'


def sync_archive_schedule(config=None) -> None:
    """Create/update/enable the PeriodicTask, or disable it.

    ``config`` may be passed explicitly (the post_save signal passes the
    just-saved instance, because load() could otherwise return the stale
    cached copy — the signal fires before save() deletes the cache key).
    """
    config = config or ArchiveConfiguration.load()

    if not config.enabled:
        PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).update(enabled=False)
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=config.archive_minute,
        hour=config.archive_hour,
        day_of_week=config.archive_day_of_week,
        day_of_month=config.archive_day_of_month,
        month_of_year=config.archive_month_of_year,
        timezone=str(settings.TIME_ZONE),
    )

    PeriodicTask.objects.update_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            'task': SCHEDULE_TASK,
            'args': json.dumps([None]),
            'crontab': crontab,
            'enabled': True,
            'expire_seconds': 3600,
        },
    )
```

Replace the entire contents of `dicom_archive/signals.py` (the Task A
stub) with:

```python
"""Signal receivers for dicom_archive (loaded via DicomArchiveConfig.ready)."""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from dicom_archive.models import ArchiveConfiguration
from dicom_archive.services.schedule_sync import sync_archive_schedule

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ArchiveConfiguration)
def _sync_archive_schedule_on_save(sender, instance, **kwargs):
    """Keep the beat schedule in sync on every configuration save.

    Never raises into the save path — a beat-sync failure must not break
    editing the archive configuration. The instance is passed so the sync
    sees the new values, not the (still) cached singleton."""
    try:
        sync_archive_schedule(instance)
    except Exception:
        logger.exception(
            'Failed to sync archive schedule for %s', instance,
        )
```

- [ ] **Step 4: Run the full app test suite to verify everything passes**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: ALL tests PASS across `test_app_scaffold`, `test_models`,
`test_locations`, `test_archive`, `test_dearchive`, `test_tasks`,
`test_schedule_sync`.

Also verify the app still boots cleanly (admin autodiscover + signals):

Run: `./venv/bin/python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/services/schedule_sync.py dicom_archive/signals.py dicom_archive/tests/test_schedule_sync.py
git commit -m "feat(dicom_archive): beat schedule sync and post_save signal wiring"
```

---

### Task H: On-disk cleanup when a study is deleted (CASCADE requirement)

**Files:**
- Modify: `dicom_archive/services/archive.py` (append `cleanup_study_files`)
- Modify: `dicom_archive/signals.py` (append `post_delete` receiver)
- Test: `dicom_archive/tests/test_cleanup.py`

**Interfaces:**
- Consumes: `ArchivedStudy` (Task B), `study.folder_path` (absolute),
  `ArchiveLocation.resolved_path` (Task B), existing imports in
  `archive.py` (`shutil`, `Path`, `logger`).
- Produces: `cleanup_study_files(study) -> dict` with keys
  `{'deleted_local': bool, 'deleted_archive': bool, 'errors': [str, ...]}` —
  **never raises**; `study_deleted_receiver(sender, instance, **kwargs)`
  connected to `post_delete` on `client_app.DICOMStudy`.

Requirement: when a `DICOMStudy` row is deleted — directly or via
`models.CASCADE` from its `Patient` — the study's DICOM files on disk are
deleted too: the local study folder **and** any archived copy.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_cleanup.py`:

```python
"""On-disk cleanup when a DICOMStudy (or its Patient) is deleted."""
import shutil
import tempfile
from pathlib import Path

from django.core.cache import cache
from django.test import TestCase

from dicom_archive.models import ArchiveLocation, ArchivedStudy
from dicom_archive.services.archive import archive_study
from dicom_archive.tests.utils import make_study, reset_archive_config


class CleanupTests(TestCase):
    def setUp(self):
        cache.clear()  # Django does not clear caches between tests
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_test_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        reset_archive_config(delete_local_after_archive=True)
        self.location = ArchiveLocation.objects.create(
            name='archive-test',
            storage_type=ArchiveLocation.StorageType.LOCAL,
            path=str(self.tmp / 'archive'),
            is_default=True,
        )

    def test_delete_study_removes_local_folder(self):
        patient, study, src = make_study(
            patient_id='PT100', study_uid='1.2.3.4.90')
        self.assertTrue(src.exists())
        study.delete()
        self.assertFalse(src.exists())

    def test_delete_archived_study_removes_archive_folder(self):
        patient, study, src = make_study(
            patient_id='PT101', study_uid='1.2.3.4.91')
        record = archive_study(study, self.location, reason='MANUAL')
        archive_dir = self.location.resolved_path / record.archive_rel_path
        self.assertTrue(archive_dir.exists())
        study.delete()
        self.assertFalse(archive_dir.exists())
        self.assertFalse(
            ArchivedStudy.objects.filter(study__patient=patient).exists())

    def test_delete_patient_cascades_to_all_study_folders(self):
        patient, study_a, src_a = make_study(
            patient_id='PT102', study_uid='1.2.3.4.92')
        _, study_b, src_b = make_study(
            patient_id='PT102', study_uid='1.2.3.4.93')
        patient.delete()
        self.assertFalse(src_a.exists())
        self.assertFalse(src_b.exists())
```

- [ ] **Step 2: Run to verify they fail**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_cleanup -v 2`
Expected: FAIL — folders still exist after `delete()` (no cleanup wired yet).

- [ ] **Step 3: Implement `cleanup_study_files` (append to `dicom_archive/services/archive.py`)**

```python
def cleanup_study_files(study) -> dict:
    """Delete on-disk DICOM files for a study whose row is being deleted.

    Removes the local study folder (``study.folder_path``) and, when an
    ``ArchivedStudy`` record exists, the archived copy
    (``location.resolved_path / archive_rel_path``). Never raises — a
    failing delete is logged and reported in ``errors`` so the signal
    handler can never abort the caller's deletion.
    """
    result = {'deleted_local': False, 'deleted_archive': False, 'errors': []}

    local = Path(getattr(study, 'folder_path') or '')
    if local and local.exists():
        try:
            shutil.rmtree(local)
            result['deleted_local'] = True
        except OSError as e:
            logger.warning(f"cleanup: could not remove local folder {local}: {e}")
            result['errors'].append(f'local: {e}')

    record = getattr(study, 'archive_record', None)
    if record is not None:
        archived = Path(record.location.resolved_path) / record.archive_rel_path
        if archived.exists():
            try:
                shutil.rmtree(archived)
                result['deleted_archive'] = True
            except OSError as e:
                logger.warning(
                    f"cleanup: could not remove archive folder {archived}: {e}")
                result['errors'].append(f'archive: {e}')

    return result
```

- [ ] **Step 4: Implement the `post_delete` receiver (append to `dicom_archive/signals.py`)**

```python
@receiver(post_delete)
def study_deleted_receiver(sender, instance, **kwargs):
    """Delete a study's DICOM files on disk whenever the study row is
    removed — directly or via cascade from Patient deletion. Per-study
    failures are logged, never raised."""
    if sender is not DICOMStudy:
        return
    try:
        cleanup_study_files(instance)
    except Exception:
        logger.exception(
            f"cleanup failed for study {getattr(instance, 'study_instance_uid', '?')}")
```

(Extend the module imports in `signals.py`: add `post_delete` to the
`django.db.models.signals` import and `from client_app.models import
DICOMStudy`; add `cleanup_study_files` to the `dicom_archive.services.archive`
import. `AppConfig.ready()` already imports this module since Task A.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/bin/python manage.py test dicom_archive.tests.test_cleanup -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full app suite**

Run: `./venv/bin/python manage.py test dicom_archive -v 2`
Expected: ALL tests PASS across `test_app_scaffold`, `test_models`,
`test_locations`, `test_archive`, `test_dearchive`, `test_tasks`,
`test_schedule_sync`, `test_cleanup`.

- [ ] **Step 7: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add dicom_archive/services/archive.py dicom_archive/signals.py dicom_archive/tests/test_cleanup.py
git commit -m "feat(dicom_archive): delete local and archived DICOM files when a study is deleted"
```

---

## Self-Review

Run this checklist after implementing all tasks (and before the final
approved batch of commits):

**1. Spec coverage** (contract: `2026-10-10-dicom-archive-00-overview.md`)

- [ ] Models: `ArchiveLocation` (StorageType, `clean`, `resolved_path`
      delegating to `services.locations`), `ArchiveConfiguration` (singleton
      `save`/`CACHE_KEY`/`load`, `crontab_tuple`, cron `clean`),
      `ArchivedStudy` (Status/Reason choices, `related_name='archive_record'`
      and `'archived_studies'`, all contract fields) — Task B. ✔ task: B
- [ ] `TaskRun.TaskType.DICOM_ARCHIVE` / `DICOM_DEARCHIVE` — Task B.
- [ ] `settings`: `'dicom_archive'` after `'dicom_server'`;
      nothing else — the de-archive timeout setting was superseded — Task A.
- [ ] Services: `resolve_location_path`, `prepare_location`,
      `study_age_days`, `candidate_studies` (Task C); `MANIFEST_NAME`,
      `ArchiveError`, `archive_study`, `archive_studies` (Task D);
      `dearchival_required_for_studies`, `dearchive_study`,
      `dearchive_studies`, `ensure_studies_local` (Task E);
      `sync_archive_schedule`, `SCHEDULE_TASK`, `PERIODIC_TASK_NAME`
      (Task G). ✔
- [ ] Tasks: `archive_studies_task` (task_name `'archive_studies'`,
      type DICOM_ARCHIVE), `dearchive_studies_task` (task_name
      `'dearchive_studies'`, type DICOM_DEARCHIVE), `task_scheduled_archive`
      (disabled → `{'status': 'disabled'}`, no candidates → `{'status':
      'empty'}`, default-else-first active location else
      `{'status': 'nothing_to_do'}`, dispatches with
      `reason=ArchivedStudy.Reason.SCHEDULED`) — Task F. ✔
- [ ] Signal hook: `post_save` on `ArchiveConfiguration` in
      `dicom_archive/signals.py`, wired in `AppConfig.ready()` (wired in
      Task A, receiver in Task G), try/except log around
      `sync_archive_schedule()` — Task G. ✔
- [ ] Beat defaults mirror `dicom_server`: `expire_seconds=3600`,
      `timezone=str(settings.TIME_ZONE)`, `args=json.dumps([None])` —
      Task G. ✔
- [ ] On-disk cleanup on study deletion: `cleanup_study_files` +
      `study_deleted_receiver` on `post_delete(DICOMStudy)`; direct-delete,
      archived-study-delete and Patient-cascade tests — Task H. ✔
- [ ] Migration command is exactly
      `./venv/bin/python manage.py makemigrations dicom_archive client_app`;
      no migration file was hand-edited; no existing migration was touched
      — Task B Step 6.
- [ ] Nothing outside the plan-01 file map was modified: only
      `dicom_archive/*`, `chavi_client/settings.py`,
      `client_app/models.py` (+ generated migrations). `chavi_client/urls.py`
      and `deidentification/*` belong to plans 03 and 02 respectively.

**2. Placeholder scan**

- [ ] `grep -n "TBD\|TODO\|appropriate error handling\|similar to Task" docs/superpowers/plans/2026-10-10-dicom-archive-01-core.md`
      returns nothing.
- [ ] Every `- [ ]` step that touches code contains a full code block; no
      step says only what to do without showing how.
- [ ] Both stub files from Task A (`admin.py`, `signals.py`) are replaced
      with real content by later tasks (B and G) — no file left as a stub.

**3. Type/name consistency**

- [ ] `ArchiveConfiguration.load()` / `reset_archive_config` /
      `crontab_tuple` are used with the same names in tasks C, D, F, G.
- [ ] `archive_studies(studies, location, user=None, reason='MANUAL')` is
      called by `archive_studies_task` with exactly those arguments;
      `dearchive_studies(study_uids, user=None)` likewise by
      `dearchive_studies_task`.
- [ ] `ArchiveError` is defined once (in `services/archive.py`) and
      imported — not redefined — by `services/dearchive.py`.
- [ ] `task_scheduled_archive` is referenced by `SCHEDULE_TASK` as
      `'dicom_archive.tasks.task_scheduled_archive'` (same module path as
      where it is defined).
- [ ] Fixture helper signatures (`make_study`, `reset_archive_config`)
      match their definitions in Task A everywhere they are called.

**4. Final gates**

- [ ] `./venv/bin/python manage.py test dicom_archive -v 2` — all green.
- [ ] `./venv/bin/python manage.py test` (full suite) — no regressions in
      `client_app`, `dicom_server`, `deidentification` (the
      `client_app` choices AlterField must not break existing TaskRun
      usages).
- [ ] `./venv/bin/python manage.py check` — 0 issues.
- [ ] Commits were executed only after explicit user approval (Global
      Constraints); if approval was not given, all work remains uncommitted.

**Execution handoff (for the orchestrator, not an action item):**
Plan complete and saved to
`docs/superpowers/plans/2026-10-10-dicom-archive-01-core.md`. Two execution
options: (1) Subagent-Driven — dispatch a fresh subagent per task with
review between tasks (REQUIRED SUB-SKILL:
superpowers:subagent-driven-development); (2) Inline Execution — execute
tasks in this session with batch checkpoints (REQUIRED SUB-SKILL:
superpowers:executing-plans).
