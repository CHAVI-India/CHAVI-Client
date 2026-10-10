# DICOM Archive — Implementation Plans (Overview & Shared Contract)

> **For agentic workers:** This directory contains FOUR plan files for the DICOM
> archival/de-archival feature. Execute in order: 01 → 02 → 03 (02 and 03 are
> independent of each other). This overview is the **binding contract**: every
> other plan must use the exact names/signatures defined here. Do not rename or
> re-shape them.

**Goal:** Archive local DICOM study folders (stored under
`MEDIA_ROOT/processed_dicom/<patient_id>/<study_uid>`) to a configurable
location (another local folder or a NAS/LAN drive via a mounted share), on a
schedule (studies older than a configured age) and on manual demand; restore
(de-archive) them automatically before deidentification and on manual demand.

**Architecture:** New Django app `dicom_archive` with three models
(`ArchiveLocation`, `ArchiveConfiguration` singleton, `ArchivedStudy`), pure
file-move/copy services (no DICOM network transfer — **remote DICOM storage
backends are explicitly OUT of scope**), Celery tasks for batched
archive/de-archive runs tracked on `client_app.TaskRun`, a django-celery-beat
`PeriodicTask` for the scheduled sweep (mirroring `dicom_server/services/schedule_sync.py`),
and a permission-scoped frontend (mirroring `dicom_server/views.py` patterns,
`templates/dicom_archive/*`, `{% component %}` library in `components/`).
Deidentification hooks into `deidentification/tasks.py` so archived studies are
restored before any deid job touches a patient's files.

**Tech Stack:** Django, Celery + django-celery-beat (DatabaseScheduler),
celery_progress, PyTorn/Tailwind via PlayCDN, django_components (`{% component %}`),
Django TestCase (no pytest), Postgres.

## Global Constraints (apply to every plan)

- All schema migrations are created with `python manage.py makemigrations` — never hand-edited.
- **No git commits until the user approves.** Plan tasks that say "commit" are
  to be executed as local commits by the executor ONLY after explicit user
  approval of the overall implementation.
- Never edit existing migration files.
- No remote-DICOM (C-MOVE/C-GET) storage backend. Storage backends are
  path-based only: `LOCAL` (any folder) and `MOUNT` (mounted NAS/LAN share).
- `DICOMStudy.folder_path` is an **absolute** POSIX path string
  (`dicom_server/services/ingest.py` sets `study.folder_path =
  str(study_dir.absolute())`). Archive code must not re-join `MEDIA_ROOT`.
- Per-study failure isolation everywhere: one bad study must not fail a batch.
- New app registered in `chavi_client/settings.py INSTALLED_APPS` after
  `'dicom_server'`.

## Verified codebase facts (as of commit f913ce6)

- `client_app.models.DICOMStudy`: PK `study_instance_uid` (CharField),
  `patient` FK, `study_date` (nullable DateField), `folder_path` (nullable
  absolute path), `created_at`.
- `client_app.models.TaskRun.TaskType`: TextChoices currently ending with
  `DEIDENTIFICATION`. Tasks use helpers `_create_task_run`, `_update_task_run`,
  `_complete_task_run`, `_fail_task_run` from `client_app.tasks`, plus
  `ProgressRecorder` (celery_progress) and `TaskRun.Status.*`.
- `chavi_client/settings.py`: `MEDIA_ROOT = os.path.join(BASE_DIR, 'media')`
  (line 328); `CELERY_BEAT_SCHEDULER =
  'django_celery_beat.schedulers:DatabaseScheduler'`; static
  `CELERY_BEAT_SCHEDULE` at line 905.
- `dicom_server.models.DICOMServerConfiguration`: singleton pattern
  (`save()` overrides pk to first row, `CACHE_KEY`, `load()` classmethod with
  30 s cache) — copy this pattern for `ArchiveConfiguration`.
- `dicom_server.services.schedule_sync.sync_node_schedule(node)`:
  `CrontabSchedule.objects.get_or_create(...)` +
  `PeriodicTask.objects.update_or_create(name=..., task=SCHEDULE_TASK,
  args=json.dumps([...]), crontab=..., enabled=..., expire_seconds=3600)`.
  Cron fields validated by `RemoteDICOMNode._CRON_FIELD_RE =
  re.compile(r'^[\d\-\,\*/]+$')` and `crontab_tuple` property.
- `dicom_server.views.DicomPermissionRequiredMixin(LoginRequiredMixin,
  PermissionRequiredMixin)` at `dicom_server/views.py:44`; every view sets
  `permission_required = '<app>.<perm>'`.
- `deidentification.tasks.deidentify_dicom_studies_bulk_task(self, study_ids,
  user_id=None)` is the single dispatcher for ALL deid entry points
  (`BulkDeidentifyView`, `TriggerDeidentificationView`). It creates the parent
  `TaskRun`, then dispatches serial links
  `deidentify_dicom_study_task(self, run_id, index, user_id=None)`; each link
  calls `deidentification.services.dicom_deidentification_flow.deidentify_study`
  which reads `study.folder_path` (raises `FileNotFoundError` if missing).
  Chain helpers: `_deid_run_study_ids(parent_run)`,
  `_deid_record_result(run_id, index, entry)`,
  `_deid_dispatch_next(run_id, index, total, user_id)`.
- Nav: `templates/base.html` lines ~35-53 define `{% url ... as nav_* %}`
  vars; desktop dropdown and mobile menu both gate the "DATA IMPORT" section on
  `perms.data_import.view_fileimportsession or
  perms.client_app.add_bulkdicomuploadsession or
  perms.client_app.view_bulkdicomuploadsession or
  perms.dicom_server.view_remotedicomnode`.
- UI: `{% component "button"/"card"/"nav_link" %}` from `components/`
  (django_components, templates in `components/templates/ui/`); app templates
  extend `base.html`; existing examples: `templates/client_app/bulk_dicom_upload.html`,
  `dicom_server` templates.
- Tests: Django `TestCase` under `<app>/tests/`; fixture helper patterns in
  `dicom_server/tests/utils.py`; archive/de-archive tests can use plain text
  files named `*.dcm` (file ops only, no pydicom parsing needed).

## Shared interface contract (BINDING)

### `client_app.models.TaskRun.TaskType` additions (owned by plan 01)

```python
DICOM_ARCHIVE = 'DICOM_ARCHIVE', 'DICOM Archive'
DICOM_DEARCHIVE = 'DICOM_DEARCHIVE', 'DICOM De-archive'
```

### `chavi_client/settings.py` additions (owned by plan 01)

```python
'Dicom_archive',  # INSTALLED_APPS, after 'dicom_server'
```

### Models (plan 01, `dicom_archive/models.py`)

```python
class ArchiveLocation(models.Model):
    class StorageType(models.TextChoices):
        LOCAL = 'LOCAL', 'Local folder'
        MOUNT = 'MOUNT', 'Mounted share (NAS/LAN)'

    name = models.CharField(max_length=100, unique=True)
    storage_type = models.CharField(max_length=10, choices=StorageType.choices, default=StorageType.LOCAL)
    path = models.CharField(max_length=500)          # LOCAL: abs or MEDIA_ROOT-relative; MOUNT: must be absolute
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self): ...                             # MOUNT ⇒ absolute path; resolves to absolute path
    @property
    def resolved_path(self) -> "pathlib.Path": ...   # delegates to services.locations.resolve_location_path
    class Meta: ordering = ['name']


class ArchiveConfiguration(models.Model):
    """Singleton — exact DICOMServerConfiguration pattern (pk forced to first
    row on save, CACHE_KEY, load() classmethod with cache.delete on save)."""
    enabled = models.BooleanField(default=False)
    archive_after_days = models.PositiveIntegerField(default=90)
    delete_local_after_archive = models.BooleanField(default=True)  # True=delete local files after archiving; False=keep local copy
    archive_minute = models.CharField(max_length=20, default='0')
    archive_hour = models.CharField(max_length=20, default='2')
    archive_day_of_week = models.CharField(max_length=20, default='*')
    archive_day_of_month = models.CharField(max_length=20, default='*')
    archive_month_of_year = models.CharField(max_length=20, default='*')
    batch_limit = models.PositiveIntegerField(default=25)   # max studies per scheduled run
    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = 'dicom_archive_config'
    def save(self, *args, **kwargs): ...              # singleton + cache.delete (mirror DICOMServerConfiguration)
    @classmethod
    def load(cls): ...                                # cache.get / get_or_create(pk=1) / cache.set(..., 30)
    @property
    def crontab_tuple(self) -> tuple: ...             # (minute, hour, dow, dom, moy)
    def clean(self): ...                              # cron-field validation, mirror RemoteDICOMNode._CRON_FIELD_RE


class ArchivedStudy(models.Model):
    class Status(models.TextChoices):
        ARCHIVING = 'ARCHIVING', 'Archiving'
        ARCHIVED = 'ARCHIVED', 'Archived'
        DEARCHIVING = 'DEARCHIVING', 'De-archiving'
        DEARCHIVED = 'DEARCHIVED', 'De-archived'
    class Reason(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        MANUAL = 'MANUAL', 'Manual'

    study = models.OneToOneField('client_app.DICOMStudy', on_delete=models.CASCADE, related_name='archive_record')
    location = models.ForeignKey('ArchiveLocation', on_delete=models.PROTECT, related_name='archived_studies')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ARCHIVING)
    reason = models.CharField(max_length=10, choices=Reason.choices, default=Reason.MANUAL)
    local_path_before = models.CharField(max_length=500)     # study.folder_path at archive time (absolute)
    archive_rel_path = models.CharField(max_length=500)      # '<patient_id>/<study_uid>' under location.path
    size_bytes = models.BigIntegerField(default=0)   # total bytes of ALL files in the study folder (recursive walk, manifest excluded)
    instance_count = models.PositiveIntegerField(default=0)
    archived_at = models.DateTimeField(null=True, blank=True)
    dearchived_at = models.DateTimeField(null=True, blank=True)
    error_log = models.TextField(blank=True, default='')
    archived_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ['-id']
```

**On-disk cleanup on study deletion:** when a `DICOMStudy` row is deleted —
directly, or via `models.CASCADE` from its `Patient` — the study's DICOM files
on disk must also be deleted: the local study folder (`folder_path`) **and**
the archived copy. Implemented in plan 01 (Task H): `post_delete` signal on
`DICOMStudy` → `dicom_archive.services.archive.cleanup_study_files(study)`
(never raises — failures are logged).

**Re-archival:** a `DEARCHIVED` record does NOT block archiving again. Once a
de-archived study is older than `archive_after_days` it becomes a candidate
again (scheduled or manual); the existing `ArchivedStudy` row is updated in
place (upsert) with fresh `archived_at`/`location`. No archive history is kept
(YAGNI).

### Services (plan 01, `dicom_archive/services/`)

```python
# locations.py
def resolve_location_path(location: ArchiveLocation) -> Path
    # LOCAL: Path(location.path).expanduser(); if relative ⇒ (Path(settings.MEDIA_ROOT) / it)
    # MOUNT: must be absolute else django.core.exceptions.ValidationError
def prepare_location(location: ArchiveLocation) -> Path
    # resolve, mkdir(parents=True, exist_ok=True), write-permission probe (tempfile);
    # raises ValidationError on failure
def study_age_days(study) -> int | None
    # reference = study.study_date or study.created_at.date(); (today - reference).days
def candidate_studies(config: ArchiveConfiguration) -> models.QuerySet
    # DICOMStudy.objects where folder_path IS NOT NULL, age >= config.archive_after_days,
    # NOT (archive_record__status IN ('ARCHIVING','ARCHIVED','DEARCHIVING'))
    # (age computed with Coalesce of study_date / created_at in the queryset)

# archive.py
MANIFEST_NAME = '_archive_manifest.json'
class ArchiveError(Exception): ...
def archive_study(study, location, user=None, reason='MANUAL') -> ArchivedStudy
    # raises ArchiveError on any failure (missing local folder, non-empty dest, move/copy error)
    # dest = prepare_location(location) / sanitize(patient_id) / study.study_instance_uid
    # deletes local files after archiving when ArchiveConfiguration.load().delete_local_after_archive
    #   (shutil.move), else keeps a local copy (shutil.copytree)
    # writes MANIFEST_NAME into dest: {study_instance_uid, patient_id, archived_at, file_count, size_bytes}
    # (size_bytes = sum of st_size over every file in the study folder — studies
    # have multiple files; the manifest itself is excluded)
    # upserts ArchivedStudy(study, location, status=ARCHIVED, reason, local_path_before,
    #   archive_rel_path, size_bytes, instance_count, archived_at=now, archived_by=user)
def archive_studies(studies, location, user=None, reason='MANUAL') -> dict
    # per-study try/except ArchiveError; returns {'archived': [uid, ...], 'failed': {uid: str(err)}}

# dearchive.py
def dearchival_required_for_studies(study_uids: list[str]) -> list[str]
    # uids that have an archive_record with status == ARCHIVED
def dearchive_study(record: ArchivedStudy, user=None) -> ArchivedStudy
    # src = record.location.resolved_path / record.archive_rel_path (must exist)
    # dst = Path(record.local_path_before) (mkdir parents); shutil.move (merge if dst non-empty)
    # removes MANIFEST_NAME from dst after move; sets status=DEARCHIVED, dearchived_at=now
    # raises ArchiveError on failure
def dearchive_studies(study_uids, user=None) -> dict
    # {'dearchived': [uid, ...], 'failed': {uid: str(err)}}; per-study isolation
def ensure_studies_local(study_uids: list[str]) -> dict
    # {'<uid>': 'local' | 'dearchived' | 'failed'} — 'local' when no ARCHIVED record
```

### Celery tasks (plan 01, `dicom_archive/tasks.py`)

```python
@shared_task(bind=True)
def archive_studies_task(self, study_uids: list, location_id: int, user_id=None, reason='MANUAL') -> dict
    # TaskRun(task_name='archive_studies', task_type=TaskRun.TaskType.DICOM_ARCHIVE)
    # calls services.archive.archive_studies; _complete_task_run / _fail_task_run;
    # returns {'archived': [...], 'failed': {...}}

@shared_task(bind=True)
def dearchive_studies_task(self, study_uids: list, user_id=None) -> dict
    # TaskRun(task_name='dearchive_studies', task_type=TaskRun.TaskType.DICOM_DEARCHIVE)
    # returns {'dearchived': [...], 'failed': {...}}

@shared_task
def task_scheduled_archive(self, user_id=None) -> dict
    # config = ArchiveConfiguration.load(); if not config.enabled: return {'status': 'disabled'}
    # candidates = candidate_studies(config) filtered to studies whose folder exists on disk
    # takes first config.batch_limit; if none → {'status': 'empty'}
    # else archive_studies_task.delay(uids, location.pk, user_id=user_id, reason='SCHEDULED')
    # (location = default active location, else first active; no location ⇒ 'nothing_to_do')
```

### Beat scheduling (plan 01, `dicom_archive/services/schedule_sync.py`)

```python
SCHEDULE_TASK = 'dicom_archive.tasks.task_scheduled_archive'
PERIODIC_TASK_NAME = 'dicom-archive-scheduled-sweep'
def sync_archive_schedule() -> None
    # config = ArchiveConfiguration.load()
    # if not config.enabled: PeriodicTask.objects.filter(name=...).update(enabled=False); return
    # CrontabSchedule.objects.get_or_create(*config.crontab_tuple, timezone=str(settings.TIME_ZONE))
    # PeriodicTask.objects.update_or_create(name=PERIODIC_TASK_NAME, defaults={
    #   'task': SCHEDULE_TASK, 'args': json.dumps([None]), 'crontab': crontab,
    #   'enabled': True, 'expire_seconds': 3600})
```

Hook: `post_save` signal on `ArchiveConfiguration` (in `dicom_archive/signals.py`,
wired in `AppConfig.ready()`) calls `sync_archive_schedule()` inside try/except
log — mirroring how `dicom_server` keeps schedules in sync.

### Deidentification hooks (plan 02)

- **Dispatcher hook** — in `deidentify_dicom_studies_bulk_task`, after the
  study roster is known and the parent `TaskRun` created, before dispatching
  the first link:
  ```python
  from dicom_archive.services.dearchive import dearchival_required_for_studies
  required = dearchival_required_for_studies(list(study_ids))
  if required:
      # in-process call — celery forbids result.get() inside a task
      result = dearchive_studies(required)
      failed = (result or {}).get('failed') or {}
      if failed:
          _fail_task_run(task_run, f"De-archival failed for {len(failed)} of {len(required)} study(s): ...")
          return
  ```
  This guarantees the patient-level requirement: any archived study of a
  deidentified patient is restored before the serial deid chain starts.
- **Per-study safety net** — in `deidentify_dicom_study_task`, after the study
  is loaded and before `deidentify_study(...)` is called:
  ```python
  from dicom_archive.services.dearchive import ensure_studies_local
  state = ensure_studies_local([study_id]).get(study_id)
  if state == 'failed':
      # record failure entry on parent run (_deid_record_result) + fail child run,
      # then _deid_dispatch_next — chain advances (per-study failure isolation)
  ```
- No changes to `deidentification` models or permissions; hooks live only in
  `deidentification/tasks.py`.

### Frontend (plan 03, app_name = `'dicom_archive'`)

`dicom_archive/urls.py` (all views gate via
`ArchivePermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin)`
in `dicom_archive/views.py`):

| Path | View (class name) | permission_required | url name |
|---|---|---|---|
| `''` | `ArchiveDashboardView` (TemplateView) | `dicom_archive.view_archiveconfiguration` | `dashboard` |
| `config/` | `ArchiveConfigUpdateView` (UpdateView) | `dicom_archive.change_archiveconfiguration` | `config_edit` |
| `locations/` | `ArchiveLocationListView` (ListView) | `dicom_archive.view_archivelocation` | `location_list` |
| `locations/add/` | `ArchiveLocationCreateView` (CreateView) | `dicom_archive.add_archivelocation` | `location_create` |
| `locations/<int:pk>/edit/` | `ArchiveLocationUpdateView` | `dicom_archive.change_archivelocation` | `location_update` |
| `locations/<int:pk>/delete/` | `ArchiveLocationDeleteView` | `dicom_archive.delete_archivelocation` | `location_delete` |
| `browse/` | `LocalStudyBrowserView` (ListView: local studies + archive status, checkboxes) | `dicom_archive.view_archivedstudy` | `browse` |
| `archived/` | `ArchivedStudyListView` (ListView) | `dicom_archive.view_archivedstudy` | `archived_list` |
| `archive/` | `ManualArchiveView` (POST JSON `{study_uids, location_id}` → `archive_studies_task.delay`) | `dicom_archive.add_archivedstudy` | `archive_trigger` |
| `dearchive/` | `ManualDearchiveView` (POST JSON `{study_uids}` → `dearchive_studies_task.delay`) | `dicom_archive.add_archivedstudy` | `dearchive_trigger` |
| `task-status/<task_run_id>/` | `TaskStatusView` (GET JSON, reads `client_app.TaskRun`) | `dicom_archive.view_archivedstudy` | `task_status` |

- Templates: `templates/dicom_archive/{dashboard,config_edit,location_form,location_list,archived_list,browse}.html`,
  extend `base.html`, use `{% component %}` (button/card/etc.) per `components/ui.py`.
- Nav (plan 03, `templates/base.html`): add
  `{% url 'dicom_archive:dashboard' as nav_archive %}` and a
  `nav_link`/`nav_mobile_item` "DICOM Archive" entry inside the existing
  **DATA IMPORT** section (desktop dropdown + mobile menu), adding
  `perms.dicom_archive.view_archiveconfiguration` to the section's gate
  condition in both places.
- Trigger views return JSON `{'task_id': ..., 'redirect_url':
  reverse('client_app:taskrun_list'), 'message': ...}` and the template polls
  `task_status` (or links to the task run list) — mirror
  `deidentification.views.BulkDeidentifyView` response shape.
- Permission grants are plain Django model perms (auto-created by the plan 01
  migration); plan 03 documents which user roles get which perms. No
  custom permissions or RBAC framework changes. The full archive permission
  set was later wired into the existing **DICOM Administrator** role group
  (no new group) by `client_app/migrations/0031_dicom_administrator_archive_permissions.py`.

## Deployment (Docker)

Containers run with `BASE_DIR=/app`, so `MEDIA_ROOT=/app/media`; in
`docker_install/example_docker-compose.yml` `./media` (relative to the compose
project dir on the Docker host) is bind-mounted to `/app/media` in every app
container. A study's `folder_path` is therefore
`/app/media/processed_dicom/<patient_id>/<study_uid>` inside the container.
**`ArchiveLocation.path` is a container-internal path**, specified per scenario:

- `LOCAL` relative path → under `/app/media` (host `./media`) — no compose
  change; archive shares the disk with the source data.
- `LOCAL` absolute or `MOUNT` (NAS/LAN) → the path must be bind-mounted into
  **`chaviclient-celery-worker`** (archive/de-archive/deid all run there) and
  **`chaviclient-django`** (the location form's `prepare_location` write-probe
  runs in the web container — without the mount, location creation fails
  validation). Example: host-mounted NAS →
  `- /mnt/nas/chavi-archive:/archive/dicom`, then location path
  `/archive/dicom` (MOUNT). Windows/UNC: `- //NAS_HOST/share:/archive/dicom`.
  `chaviclient-celery-beat` (dispatch only) and `chaviclient-dicom` (SCP
  ingest) need no mount.

Plan 03 (Task 7) ships `docs/dicom_archive_docker_deployment.md` with the
exact compose snippets and verification steps.

## File map & plan ownership

| Plan file | Creates / modifies |
|---|---|
| `2026-10-10-dicom-archive-01-core.md` | CREATE `dicom_archive/{__init__,apps,models,admin,signals,tasks,urls}.py`, `dicom_archive/services/{__init__,locations,archive,dearchive,schedule_sync}.py`, `dicom_archive/migrations/0001_initial.py` (via makemigrations), `dicom_archive/tests/*`. MODIFY `chavi_client/settings.py` (INSTALLED_APPS + timeout setting), `client_app/models.py` (TaskRun.TaskType). |
| `2026-10-10-dicom-archive-02-deid.md` | MODIFY `deidentification/tasks.py` (dispatcher hook + per-study guard). CREATE `deidentification/test_archive_hooks.py`. |
| `2026-10-10-dicom-archive-03-ui.md` | CREATE `dicom_archive/views.py` (mixin + views), `dicom_archive/forms.py`, `templates/dicom_archive/*.html`, `docs/dicom_archive_docker_deployment.md`. MODIFY `dicom_archive/urls.py` (stub from 01), `chavi_client/urls.py` (root `include`), `templates/base.html` (nav). |

Note: plan 01 creates `dicom_archive/urls.py` as an empty stub (or the full
URLConf if it prefers — then plan 03 only edits views/forms/templates and
documents permission grants).

## Open items deliberately excluded (YAGNI — flag to user if wanted)

- Remote-DICOM (C-MOVE) archival backend — user excluded.
- Verification/repair scan of archive contents (manifest audit task).
- Archiving `Unprocessed_DICOM` (only `DICOMStudy.folder_path` studies are in scope).
- Admin (django-unfold) registration: out of scope; frontend + model perms suffice.
