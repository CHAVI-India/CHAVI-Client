# DICOM Archive — Frontend (Permission-Scoped Views + Templates + Nav) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the permission-scoped Django frontend for the DICOM archive: a dashboard, config + location CRUD, local-study browsing with manual archive/de-archive triggers, task-status polling, and DATA IMPORT nav integration — all harmonized with the existing CHAVI Client UI.

**Architecture:** New views in `dicom_archive/views.py` mirror `dicom_server/views.py` (a shared `ArchivePermissionRequiredMixin` gating every view on plain Django model perms); JSON trigger views mirror `deidentification.views.BulkDeidentifyView` (dispatch Celery task → `{task_id, redirect_url, message}`) and the app polls `TaskStatusView` over `client_app.TaskRun`. Templates live in `templates/dicom_archive/`, extend `base.html`, and use the `{% component %}` library in `components/` (verified component names/attrs: `button`, `card` (title/accent kwargs, header/body/footer/actions slots), `badge`, `table`, `stat_card`, `page_header`, `info_box`, `empty_state`, `pagination`, `icon_button`, `nav_dropdown(_item)`, `nav_mobile_item`, `form_field` — slots close with `{% endfill %}`).

**Tech Stack:** Django (Django TestCase — no pytest), django_components (`{% component %}`), django-crispy-forms (`{{ form|crispy }}`), Tailwind via PlayCDN, vanilla JS `fetch` + `setInterval` polling (3 s cadence, pattern from `templates/dicom_server/batch_select.html` and `templates/client_app/task_progress.html`).

**Spec:** `docs/superpowers/plans/2026-10-10-dicom-archive-00-overview.md` (binding contract — exact model names/fields, `dicom_archive.urls` table with paths/view classes/permission_required/url names/app_name, service + task signatures this plan consumes).

## Global Constraints

- **No git commits until the user approves.** Every "Commit" step in this plan is executed ONLY after explicit user approval of the overall implementation (overview global constraint). Each commit step below says so again.
- This plan runs AFTER plan 01 (models, services, tasks, app skeleton incl. a stub `dicom_archive/urls.py`, `dicom_archive/tests/`) — never recreate or edit anything plan 01 owns; never hand-edit migration files.
- `app_name = 'dicom_archive'`; use the contract's exact view class names, url names, and `permission_required` strings. Do not rename or re-shape them.
- Trigger responses are JSON `{'task_id': ..., 'redirect_url': reverse('client_app:taskrun_list'), 'message': ...}` (BulkDeidentifyView shape).
- `DICOMStudy.folder_path` is an absolute POSIX path — archive UI code must not re-join `MEDIA_ROOT`.
- Storage backends are path-based only (`LOCAL`, `MOUNT`) — no remote-DICOM options anywhere in forms/templates.
- Per-study failure isolation lives in plan-01 tasks; views never catch task internals — dispatch failures are 500 JSON `{'error': ...}`.
- Templates extend `base.html` and use `{% component %}` (component tags are in TEMPLATES builtins — do NOT add `{% load component_tags %}`); form templates also use `{% load crispy_forms_tags %}`.
- Run tests with `python manage.py test <test label> -v 2` (Django `TestCase`, Postgres).

## Design notes

Decisions for spots where the overview contract is silent (recorded here, used by every task):

1. **TaskStatusView id resolution.** Trigger views return `task_id` = the Celery task id (exactly what `BulkDeidentifyView` returns: `result.id`). The `TaskRun` row is only created when the task *starts*, so `TaskStatusView` resolves the URL segment as: `TaskRun.objects.filter(pk=task_run_id).first()` inside a `try/except ValueError` (the pk is an AutoField — a non-numeric id like a celery task id raises `ValueError` at query-prep time), else `TaskRun.objects.filter(task_id=task_run_id).first()`, else 404. JS polls with the returned `task_id` and tolerates 404s until the row exists (keeps polling).
2. **ArchiveLocationDeleteView is POST-only.** The contract's template set (`dashboard, config_edit, location_form, location_list, archived_list, browse`) has no delete-confirm page, so the view is a plain `View`: GET → redirect to `location_list`; POST → guard + delete + flash + redirect. Confirmation happens client-side via `onsubmit="return confirm(...)"` on the list row's inline form. The `PROTECT` FK from `ArchivedStudy.location` is guarded with an explicit error flash instead of letting `ProtectedError` propagate.
3. **Cron validation lives in the model `clean()`** (plan 01). `ArchiveConfigurationForm` does not duplicate the regex — `ModelForm._post_clean` runs the instance `full_clean()`, so bad cron fields surface as field errors.
4. **Location path validation.** `ArchiveLocationForm.clean()` calls `services.locations.prepare_location()` on a *transient* `ArchiveLocation(storage_type=..., path=...)` (never `save()`d) so the path is proven resolvable + writable before persisting; failures become `path` field errors.
5. **Nav placement/icon.** The "DICOM Archive" entry goes inside the existing **DATA IMPORT** section (desktop dropdown + mobile menu), gated on `perms.dicom_archive.view_archiveconfiguration`, which is also OR'd into that section's existing gate in both places. The desktop dropdown's `active_on` gains the `dicom_archive` namespace. Icon: `fa-box-archive` is reserved for the nav items; page headers use other icons (e.g. `fa-warehouse`) so nav tests can assert the nav string uniquely.
6. **Root URL include.** Plan 01's file map does not mention the `chavi_client/urls.py` include, so Task 1 adds `path('dicom-archive/', include('dicom_archive.urls'))` — skip that one edit if plan 01 already added it.
7. **Test/render split.** Templates are created in Task 4, so Tasks 1–3 assert only non-render behavior (302/403 gating, form validity, POST redirects, JSON). All 200-render assertions live in `test_templates.py` (Task 4) and `test_nav.py` (Task 5).
8. **Polling.** Trigger pages poll every 3000 ms (same cadence as `batch_select.html`) until status is in `SUCCESS, FAILURE, STALLED, CANCELLED`, then stop and show the result plus the `redirect_url` ("View task runs") link.
9. `dicom_archive/PERMISSIONS.md` (Task 6) is the permission-grant documentation deliverable the overview assigns to plan 03.
10. **Component `extra_class` isolation (root-cause fix in `components/ui.py`).** A component's template renders `{{ extra_class }}`, but `KwargComponent.get_template_data` never defaulted it — so a *nested* component (e.g. the status badge inside the dashboard's Recent-archived table) fell back to the *outer* component's `extra_class` via template context and picked up the card's `mb-8`, shifting the badge out of alignment with the row's text. Fix: `data.setdefault("extra_class", None)` in `KwargComponent.get_template_data` and in the three overrides that build their data without calling super (`pagination`, `stepper`, `file_type_badge`). Regression tests: `TestComponentExtraClassIsolation` (component-level render + dashboard badge/table-wrapper class check).
11. **Location "Test" probe (iterative addition, post-plan).** `services.locations.test_location()` probes a location in three visible steps — *Reachable* (directory exists / is created, `created` flag reported), *Writable* (`os.access` W_OK), *Write test* (writes the small **persistent** file `chavi_archive_write_test.txt` — hostname, pid, UTC timestamp, storage type, resolved path, unique token — then reads it back to verify). The file is intentionally NOT deleted: the user opens it on the share to confirm writes really land there. `LocationTestView` (POST JSON `{location_id}` or unsaved `{storage_type, path}`, permission `view_archivelocation`, url `dicom_archive:location_test`) powers a 🔌 button per row on the locations list and a **Test path** button on the add/edit form; both render a check-by-check result box with the verification file's path.

---

### Task 1: Permission mixin + dashboard/browse/archived views + URLConf skeleton

**Files:**
- Create: `dicom_archive/views.py`
- Modify: `dicom_archive/urls.py` (stub created by plan 01 → full URLConf, first of three cumulative rewrites)
- Modify: `chavi_client/urls.py` (root include, after the `dicom-server/` line — skip if plan 01 added it)
- Test: `dicom_archive/tests/test_views.py`

**Interfaces:**
- Consumes (plan 01): `dicom_archive.models.ArchiveConfiguration.load()` classmethod; `ArchiveConfiguration` fields `enabled, archive_after_days, delete_local_after_archive, archive_minute, archive_hour, archive_day_of_week, archive_day_of_month, archive_month_of_year, batch_limit`; `ArchiveLocation` (fields `name, storage_type, path, is_default, is_active`, `StorageType.LOCAL/'LOCAL'`); `ArchivedStudy` (fields `study, location, status, reason, size_bytes, instance_count, archived_at, archived_by`; `Status.ARCHIVING/ARCHIVED/DEARCHIVING/DEARCHIVED`; related_name `archive_record` on `study`); `client_app.models.DICOMStudy` (PK `study_instance_uid`, `patient` FK, `study_date`, `folder_path`, `created_at`).
- Produces: `ArchivePermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin)` with `handle_no_permission` (anon → login redirect, else 403); `ArchiveDashboardView` context keys `config, default_location, status_counts, total_records, in_flight_count, recent_archived`; `LocalStudyBrowserView` (context `studies, page_obj, locations, query_string`, `paginate_by=25`, `?q=` filter); `ArchivedStudyListView` (context `records, page_obj, status_choices, locations, query_string`, `?status=`/`?location_id=` filters). Url names `dashboard`, `browse`, `archived_list`.

- [ ] **Step 1: Write the failing test**

Create `dicom_archive/tests/test_views.py`:

```python
"""Frontend tests for dicom_archive (plan 03).

Task 1: permission gating. Task 2: location CRUD + config update.
Task 3: manual trigger + task-status JSON views.
"""
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from client_app.models import DICOMStudy, Patient, SiteConfiguration
from dicom_archive.models import ArchiveLocation, ArchivedStudy


class ArchiveViewTestCase(TestCase):
    """Shared fixtures for every plan-03 test class."""

    def setUp(self):
        # The ArchiveConfiguration singleton caches its instance for 30 s;
        # the test DB rolls back between tests, so a stale cached row would
        # point at a deleted pk. Clear the cache on every test.
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        SiteConfiguration.objects.create(
            chavi_center_id='TEST', center_name='Test Hospital')
        # Archive administrator: every dicom_archive model permission.
        cls.admin = User.objects.create_user(
            'archive-admin', password='pw', is_staff=True)
        cls.admin.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=[
                'view_archiveconfiguration', 'change_archiveconfiguration',
                'view_archivelocation', 'add_archivelocation',
                'change_archivelocation', 'delete_archivelocation',
                'view_archivedstudy', 'add_archivedstudy',
            ],
        ))
        # Viewer: can browse archives, cannot configure or trigger.
        cls.viewer = User.objects.create_user('archive-viewer', password='pw')
        cls.viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=['view_archivedstudy'],
        ))
        cls.plain = User.objects.create_user('archive-plain', password='pw')

        cls.patient = Patient.objects.create(
            patient_id='MR/25/000001', gender='Female')
        cls.study = DICOMStudy.objects.create(
            patient=cls.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.9',
            study_date='2025-01-15',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.9',
        )
        cls.location = ArchiveLocation.objects.create(
            name='NAS archive',
            storage_type=ArchiveLocation.StorageType.LOCAL,
            path='archive/studies',
            is_default=True,
        )
        cls.record = ArchivedStudy.objects.create(
            study=cls.study,
            location=cls.location,
            status=ArchivedStudy.Status.ARCHIVED,
            local_path_before=cls.study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.9',
            size_bytes=123,
            instance_count=4,
        )


class TestPermissionGating(ArchiveViewTestCase):
    GATED_URLS = ['dashboard', 'browse', 'archived_list']

    def test_anonymous_redirected_to_login(self):
        for name in self.GATED_URLS:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn('/accounts/login/', resp.url, name)

    def test_plain_user_denied_everywhere(self):
        self.client.force_login(self.plain)
        for name in self.GATED_URLS:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_viewer_denied_dashboard(self):
        # viewer has only view_archivedstudy; dashboard needs
        # view_archiveconfiguration. 403 needs no template render.
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test dicom_archive.tests.test_views -v 2`
Expected: FAIL — `django.urls.exceptions.NoReverseMatch` for `dicom_archive:dashboard` (plan 01's `urls.py` stub has no patterns yet).

- [ ] **Step 3: Write the views module**

Create `dicom_archive/views.py`:

```python
"""Permission-scoped frontend views for the DICOM archive (plan 03).

Mirrors dicom_server/views.py: every view gates through
ArchivePermissionRequiredMixin on plain Django model permissions.
"""
import logging

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.urls import reverse_lazy
from django.views.generic import ListView, TemplateView

from client_app.models import DICOMStudy
from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy

logger = logging.getLogger(__name__)


class ArchivePermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Anonymous -> login redirect; authenticated without the permission -> 403.

    Mirrors dicom_server.views.DicomPermissionRequiredMixin.
    """
    raise_exception = True

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name(),
        )


class ArchiveDashboardView(ArchivePermissionRequiredMixin, TemplateView):
    """Landing page: configuration status, default location, per-status
    counts, recent archived studies."""
    template_name = 'dicom_archive/dashboard.html'
    permission_required = 'dicom_archive.view_archiveconfiguration'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['config'] = ArchiveConfiguration.load()
        context['default_location'] = ArchiveLocation.objects.filter(
            is_active=True, is_default=True,
        ).order_by('-updated_at').first()
        counts = dict(ArchivedStudy.objects.values_list('status')
                      .annotate(count=Count('id'))
                      .values_list('status', 'count'))
        context['status_counts'] = counts
        context['total_records'] = sum(counts.values())
        context['in_flight_count'] = (
            counts.get(ArchivedStudy.Status.ARCHIVING, 0)
            + counts.get(ArchivedStudy.Status.DEARCHIVING, 0)
        )
        context['recent_archived'] = ArchivedStudy.objects.select_related(
            'study__patient', 'location', 'archived_by',
        )[:10]
        return context


class LocalStudyBrowserView(ArchivePermissionRequiredMixin, ListView):
    """Local DICOM studies (folder_path set) with their archive status
    (archive_record) and checkbox selection; ?q= filters patient ID or
    study UID."""
    model = DICOMStudy
    template_name = 'dicom_archive/browse.html'
    context_object_name = 'studies'
    permission_required = 'dicom_archive.view_archivedstudy'
    paginate_by = 25

    def get_queryset(self):
        qs = (
            DICOMStudy.objects.filter(folder_path__isnull=False)
            .select_related('patient', 'archive_record__location')
            .order_by('-created_at')
        )
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(patient__patient_id__icontains=q)
                | Q(study_instance_uid__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['locations'] = ArchiveLocation.objects.filter(is_active=True)
        context['query_string'] = self.request.GET.urlencode()
        return context


class ArchivedStudyListView(ArchivePermissionRequiredMixin, ListView):
    """Studies currently in an archive location, filterable by ?status=
    and ?location_id;. With no explicit ?status= the list defaults to
    ARCHIVED only (de-archived studies live locally again); picking
    "All statuses" (?status=) or a concrete status shows those records.
    Rows with status ARCHIVED carry a de-archive checkbox."""
    model = ArchivedStudy
    template_name = 'dicom_archive/archived_list.html'
    context_object_name = 'records'
    permission_required = 'dicom_archive.view_archivedstudy'
    paginate_by = 25

    def get_queryset(self):
        qs = ArchivedStudy.objects.select_related(
            'study__patient', 'location', 'archived_by',
        )
        if 'status' in self.request.GET:
            status = self.request.GET['status']
            if status in ArchivedStudy.Status.values:
                qs = qs.filter(status=status)
        else:
            qs = qs.filter(status=ArchivedStudy.Status.ARCHIVED)
        location_id = self.request.GET.get('location_id')
        if location_id:
            qs = qs.filter(location_id=location_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = ArchivedStudy.Status.choices
        context['locations'] = ArchiveLocation.objects.all()
        context['active_status'] = (
            self.request.GET['status']
            if 'status' in self.request.GET
            else ArchivedStudy.Status.ARCHIVED
        )
        context['query_string'] = self.request.GET.urlencode()
        return context
```

- [ ] **Step 4: Wire the URLs**

Replace the contents of `dicom_archive/urls.py` (plan 01 stub) with:

```python
from django.urls import path

from dicom_archive import views

app_name = 'dicom_archive'

urlpatterns = [
    path('', views.ArchiveDashboardView.as_view(), name='dashboard'),
    path('browse/', views.LocalStudyBrowserView.as_view(), name='browse'),
    path('archived/', views.ArchivedStudyListView.as_view(), name='archived_list'),
]
```

In `chavi_client/urls.py`, add the root include after the `# DICOM server URLs` block (skip if plan 01 already added it):

```python
    # DICOM server URLs
    path('dicom-server/', include('dicom_server.urls')),
    # DICOM archive URLs
    path('dicom-archive/', include('dicom_archive.urls')),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test dicom_archive.tests.test_views -v 2`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit** — executes ONLY after explicit user approval

```bash
git add dicom_archive/views.py dicom_archive/urls.py chavi_client/urls.py dicom_archive/tests/test_views.py
git commit -m "feat(dicom-archive): permission-gated dashboard/browse/archived views"
```

---

### Task 2: Config + location CRUD (forms, views, URLs)

**Files:**
- Create: `dicom_archive/forms.py`
- Modify: `dicom_archive/views.py` (append config + location views; extend imports)
- Modify: `dicom_archive/urls.py` (second cumulative rewrite — all 6 CRUD/config routes)
- Test: `dicom_archive/tests/test_forms.py`; `dicom_archive/tests/test_views.py` (append `TestLocationCrud`)

**Interfaces:**
- Consumes: Task 1's `ArchivePermissionRequiredMixin`; plan-01 `ArchiveConfiguration` (singleton, `clean()` validates cron fields with `^[\d\-\,\*/]+$` — same pattern as `RemoteDICOMNode._CRON_FIELD_RE`) and `ArchiveLocation` (fields `name, storage_type, path, is_default, is_active`); plan-01 `dicom_archive.services.locations.prepare_location(location) -> pathlib.Path` (resolves, `mkdir(parents=True, exist_ok=True)`, write-permission probe; raises `django.core.exceptions.ValidationError` on failure — MOUNT paths must be absolute).
- Produces: `ArchiveConfigurationForm` (ModelForm over `enabled, archive_after_days, delete_local_after_archive, archive_minute, archive_hour, archive_day_of_week, archive_day_of_month, archive_month_of_year, batch_limit`); `ArchiveLocationForm` (ModelForm over `name, storage_type, path, is_default, is_active`; `clean()` runs `prepare_location` on a transient instance, mapping its `ValidationError` to a `path` field error); views `ArchiveConfigUpdateView` (UpdateView, `success_url` → `dicom_archive:dashboard`), `ArchiveLocationListView` (ListView, rows annotated `study_count`), `ArchiveLocationCreateView` / `ArchiveLocationUpdateView` (success → `dicom_archive:location_list` + success flash), `ArchiveLocationDeleteView` (POST-only plain `View`, design note 2: refusal flash when the location still holds `ArchivedStudy` rows). Url names `config_edit, location_list, location_create, location_update, location_delete`.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_forms.py`:

```python
"""Form validation for archive config + locations (plan 03, Task 2)."""
import tempfile
from pathlib import Path

from django.test import TestCase

from dicom_archive.forms import ArchiveConfigurationForm, ArchiveLocationForm


class TestArchiveConfigurationForm(TestCase):
    VALID = {
        'enabled': 'on',
        'archive_after_days': '30',
        'archive_minute': '0',
        'archive_hour': '2',
        'archive_day_of_week': '*',
        'archive_day_of_month': '*',
        'archive_month_of_year': '*',
        'batch_limit': '25',
    }

    def test_valid_data(self):
        form = ArchiveConfigurationForm(data=self.VALID)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['archive_after_days'], 30)

    def test_rejects_bad_cron_minute(self):
        # Model clean() (plan 01) rejects anything outside ^[\d\-,*/]+$ —
        # ModelForm._post_clean surfaces it as a field error.
        form = ArchiveConfigurationForm(data=dict(self.VALID, archive_minute='every'))
        self.assertFalse(form.is_valid())
        self.assertIn('archive_minute', form.errors)

    def test_rejects_bad_day_of_month(self):
        form = ArchiveConfigurationForm(
            data=dict(self.VALID, archive_day_of_month='1st'))
        self.assertFalse(form.is_valid())
        self.assertIn('archive_day_of_month', form.errors)


class TestArchiveLocationForm(TestCase):
    def test_valid_local_path_in_writable_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            form = ArchiveLocationForm(data={
                'name': 'Test drive',
                'storage_type': 'LOCAL',
                'path': str(Path(tmp) / 'archive'),
                'is_active': 'on',
            })
            self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_unwritable_path(self):
        form = ArchiveLocationForm(data={
            'name': 'Bad drive',
            'storage_type': 'LOCAL',
            'path': '/nonexistent-no-permission/archive',
            'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('path', form.errors)

    def test_rejects_relative_mount_path(self):
        form = ArchiveLocationForm(data={
            'name': 'Bad mount',
            'storage_type': 'MOUNT',
            'path': 'relative/share',
            'is_active': 'on',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('path', form.errors)
```

In `dicom_archive/tests/test_views.py`: add `import tempfile` to the top-level imports (import block becomes `from unittest import mock` / `import tempfile` / `from django.contrib.auth.models import ...`), and append this class at the end of the file:

```python
class TestLocationCrud(ArchiveViewTestCase):
    def test_anonymous_redirected_on_location_pages(self):
        for name in ['location_list', 'location_create']:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 302, name)

    def test_plain_user_denied_location_pages(self):
        self.client.force_login(self.plain)
        for name in ['location_list', 'location_create']:
            resp = self.client.get(reverse(f'dicom_archive:{name}'))
            self.assertEqual(resp.status_code, 403, name)

    def test_viewer_denied_location_create_and_delete(self):
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.get(
                reverse('dicom_archive:location_create')).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse('dicom_archive:location_delete',
                        args=[self.location.pk])).status_code, 403)

    def test_create_location(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            resp = self.client.post(
                reverse('dicom_archive:location_create'),
                {'name': 'Backup NAS', 'storage_type': 'MOUNT',
                 'path': tmp, 'is_active': 'on'})
        self.assertEqual(resp.status_code, 302, resp.content)
        self.assertEqual(resp.url, reverse('dicom_archive:location_list'))
        loc = ArchiveLocation.objects.get(name='Backup NAS')
        self.assertTrue(loc.is_active)
        self.assertEqual(loc.storage_type, 'MOUNT')

    def test_update_location(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as tmp:
            resp = self.client.post(
                reverse('dicom_archive:location_update',
                        args=[self.location.pk]),
                {'name': 'NAS archive', 'storage_type': 'LOCAL',
                 'path': tmp, 'is_default': 'on', 'is_active': 'on'})
        self.assertEqual(resp.status_code, 302, resp.content)
        self.location.refresh_from_db()
        self.assertEqual(self.location.path, tmp)
        self.assertTrue(self.location.is_default)

    def test_delete_location_without_records(self):
        self.client.force_login(self.admin)
        empty = ArchiveLocation.objects.create(
            name='Empty', storage_type=ArchiveLocation.StorageType.LOCAL,
            path='archive/empty')
        resp = self.client.post(
            reverse('dicom_archive:location_delete', args=[empty.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ArchiveLocation.objects.filter(pk=empty.pk).exists())

    def test_delete_location_with_records_refused(self):
        # fixture self.location holds self.record (ARCHIVED)
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:location_delete', args=[self.location.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ArchiveLocation.objects.filter(pk=self.location.pk).exists())

    def test_config_update_rejects_bad_cron_and_keeps_old_value(self):
        self.client.force_login(self.admin)
        config = ArchiveConfiguration.load()
        original_minute = config.archive_minute
        resp = self.client.post(
            reverse('dicom_archive:config_edit'),
            {'enabled': 'on', 'archive_after_days': '30',
             'archive_minute': 'soon', 'archive_hour': '2',
             'archive_day_of_week': '*', 'archive_day_of_month': '*',
             'archive_month_of_year': '*', 'batch_limit': '25'})
        # form re-renders with the error; nothing is saved
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'archive_minute')
        config.refresh_from_db()
        self.assertEqual(config.archive_minute, original_minute)
```

(Import `ArchiveConfiguration` alongside the existing model imports at the top of `test_views.py`: `from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_archive.tests.test_forms dicom_archive.tests.test_views.TestLocationCrud -v 2`
Expected: FAIL — `ImportError: cannot import name 'ArchiveConfigurationForm' from 'dicom_archive.forms'` and `NoReverseMatch` for `dicom_archive:config_edit` / `location_*`.

- [ ] **Step 3: Write the forms module**

Create `dicom_archive/forms.py`:

```python
"""Forms for the DICOM archive frontend (plan 03)."""
from django import forms
from django.core.exceptions import ValidationError

from dicom_archive.models import ArchiveConfiguration, ArchiveLocation
from dicom_archive.services.locations import prepare_location


class ArchiveConfigurationForm(forms.ModelForm):
    """Singleton archive config. Cron-field validation lives in the model's
    clean() (plan 01) — ModelForm._post_clean runs the instance full_clean(),
    so bad cron fields surface as field errors without duplicating the
    regex here."""

    class Meta:
        model = ArchiveConfiguration
        fields = [
            'enabled', 'archive_after_days', 'delete_local_after_archive',
            'archive_minute', 'archive_hour',
            'archive_day_of_week', 'archive_day_of_month',
            'archive_month_of_year', 'batch_limit',
        ]


class ArchiveLocationForm(forms.ModelForm):
    """Location CRUD. clean() proves the path is resolvable AND writable via
    services.locations.prepare_location on a transient (never saved)
    instance, mapping its ValidationError to the path field."""

    class Meta:
        model = ArchiveLocation
        fields = ['name', 'storage_type', 'path', 'is_default', 'is_active']

    def clean(self):
        cleaned = super().clean()
        storage_type = cleaned.get('storage_type')
        path = (cleaned.get('path') or '').strip()
        if storage_type and path:
            try:
                prepare_location(ArchiveLocation(
                    storage_type=storage_type, path=path,
                ))
            except ValidationError as exc:
                self.add_error('path', exc.messages[0])
        return cleaned
```

- [ ] **Step 4: Add the config + location views**

In `dicom_archive/views.py`, extend the import block (top of file) to:

```python
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView
```

(from `client_app.models` import only `DICOMStudy` as before; from `dicom_archive.forms` import `ArchiveConfigurationForm, ArchiveLocationForm`; models import stays `from dicom_archive.models import ArchiveConfiguration, ArchiveLocation, ArchivedStudy`.)

Append after `ArchivedStudyListView`:

```python
# --- Configuration (archive config permission) ---

class ArchiveConfigUpdateView(ArchivePermissionRequiredMixin, UpdateView):
    model = ArchiveConfiguration
    form_class = ArchiveConfigurationForm
    template_name = 'dicom_archive/config_edit.html'
    permission_required = 'dicom_archive.change_archiveconfiguration'
    success_url = reverse_lazy('dicom_archive:dashboard')

    def get_object(self, queryset=None):
        return ArchiveConfiguration.load()

    def form_valid(self, form):
        messages.success(self.request, 'DICOM archive configuration saved.')
        return super().form_valid(form)


# --- Locations (location permissions) ---

class ArchiveLocationListView(ArchivePermissionRequiredMixin, ListView):
    model = ArchiveLocation
    template_name = 'dicom_archive/location_list.html'
    context_object_name = 'locations'
    permission_required = 'dicom_archive.view_archivelocation'

    def get_queryset(self):
        return ArchiveLocation.objects.annotate(
            study_count=Count('archived_studies'),
        ).order_by('name')


class ArchiveLocationCreateView(ArchivePermissionRequiredMixin, CreateView):
    model = ArchiveLocation
    form_class = ArchiveLocationForm
    template_name = 'dicom_archive/location_form.html'
    permission_required = 'dicom_archive.add_archivelocation'
    success_url = reverse_lazy('dicom_archive:location_list')

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Archive location "{form.instance.name}" created.')
        return super().form_valid(form)


class ArchiveLocationUpdateView(ArchivePermissionRequiredMixin, UpdateView):
    model = ArchiveLocation
    form_class = ArchiveLocationForm
    template_name = 'dicom_archive/location_form.html'
    permission_required = 'dicom_archive.change_archivelocation'
    success_url = reverse_lazy('dicom_archive:location_list')

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Archive location "{form.instance.name}" updated.')
        return super().form_valid(form)


class ArchiveLocationDeleteView(ArchivePermissionRequiredMixin, View):
    """POST-only delete (the list page confirms client-side; the contract's
    template set has no delete-confirm page). A location that still holds
    ArchivedStudy rows is refused with a flash instead of a PROTECT error."""
    permission_required = 'dicom_archive.delete_archivelocation'

    def get(self, request, pk):
        return redirect('dicom_archive:location_list')

    def post(self, request, pk):
        location = get_object_or_404(ArchiveLocation, pk=pk)
        if ArchivedStudy.objects.filter(location=location).exists():
            messages.error(request, (
                f'"{location.name}" still holds archived studies and cannot '
                'be deleted. De-archive or move them first.'
            ))
        else:
            name = location.name
            location.delete()
            messages.success(
                request, f'Archive location "{name}" deleted.')
        return redirect('dicom_archive:location_list')
```

- [ ] **Step 5: Update the URLConf**

Replace `dicom_archive/urls.py` urlpatterns (header/imports unchanged) with:

```python
urlpatterns = [
    path('', views.ArchiveDashboardView.as_view(), name='dashboard'),
    path('config/', views.ArchiveConfigUpdateView.as_view(), name='config_edit'),
    path('locations/', views.ArchiveLocationListView.as_view(), name='location_list'),
    path('locations/add/', views.ArchiveLocationCreateView.as_view(), name='location_create'),
    path('locations/<int:pk>/edit/', views.ArchiveLocationUpdateView.as_view(), name='location_update'),
    path('locations/<int:pk>/delete/', views.ArchiveLocationDeleteView.as_view(), name='location_delete'),
    path('browse/', views.LocalStudyBrowserView.as_view(), name='browse'),
    path('archived/', views.ArchivedStudyListView.as_view(), name='archived_list'),
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test dicom_archive.tests.test_forms dicom_archive.tests.test_views -v 2`
Expected: PASS (6 form tests + 3 gating tests + 8 CRUD tests).

- [ ] **Step 7: Commit** — executes ONLY after explicit user approval

```bash
git add dicom_archive/forms.py dicom_archive/views.py dicom_archive/urls.py \
        dicom_archive/tests/test_forms.py dicom_archive/tests/test_views.py
git commit -m "feat(dicom-archive): config + location CRUD with writable-path validation"
```

---

### Task 3: Manual archive/de-archive triggers + task-status poll endpoint

**Files:**
- Modify: `dicom_archive/views.py` (append `_json_payload` + 3 JSON views; extend imports)
- Modify: `dicom_archive/urls.py` (third and final cumulative rewrite — full contract table)
- Test: `dicom_archive/tests/test_views.py` (append `TestManualTriggers`, `TestTaskStatusView`)

**Interfaces:**
- Consumes: Task 1's `ArchivePermissionRequiredMixin`; plan-01 tasks `archive_studies_task.delay(study_uids, location_id, user_id=None, reason='MANUAL')` and `dearchive_studies_task.delay(study_uids, user_id=None)` (both `bind=True` shared tasks creating `TaskRun` rows with `TaskType.DICOM_ARCHIVE` / `DICOM_DEARCHIVE`); `client_app.models.TaskRun` (fields `task_id` unique Celery id, `task_name`, `task_type`, `status` — `Status.PENDING/STARTED/PROGRESS/SUCCESS/FAILURE/STALLED/CANCELLED`, `progress_current`, `progress_total`, `progress_description`, `result_summary`, `error_log`, `completed_at`, property `progress_percent`); `reverse('client_app:taskrun_list')` (existing, `/tasks/`).
- Produces: `ManualArchiveView.post` — accepts JSON `{'study_uids': [str, ...], 'location_id': int}`; 400 JSON `{'error': ...}` on: invalid JSON body, empty/non-list `study_uids`, inactive/unknown `location_id`, unknown or non-local study UIDs; dispatch failure → 500 JSON `{'error': 'Could not dispatch archive task'}`; success → 200 JSON `{'task_id': <celery id>, 'redirect_url': reverse('client_app:taskrun_list'), 'message': 'Archiving N study(s) to "<location.name>" in the background.'}` with `reason='MANUAL'`. `ManualDearchiveView.post` — JSON `{'study_uids': [...]}`; 400 unless every UID has an `ArchivedStudy` with `status == 'ARCHIVED'`; success message `'De-archiving N study(s) in the background.'` (same response shape). `TaskStatusView.get(request, task_run_id)` — 404 JSON `{'error': 'task run not found'}` until the TaskRun row exists; else 200 JSON `{'task_run_id', 'task_id', 'task_name', 'task_type', 'status', 'progress_current', 'progress_total', 'progress_percent', 'progress_description', 'result_summary', 'error_log', 'completed_at' (ISO or null)}`. Url names `archive_trigger`, `dearchive_trigger`, `task_status`.

- [ ] **Step 1: Write the failing tests**

Append to `dicom_archive/tests/test_views.py` (add `import json`, `import tempfile` — already present — `from types import SimpleNamespace`, `from client_app.models import TaskRun` to the import block; full top-of-file import block after this task:

```python
import json
import re
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from client_app.models import DICOMStudy, Patient, SiteConfiguration, TaskRun
from dicom_archive.models import (
    ArchiveConfiguration, ArchiveLocation, ArchivedStudy,
)
```

):

```python
class TestManualTriggers(ArchiveViewTestCase):
    def test_archive_trigger_requires_login_and_perm(self):
        url = reverse('dicom_archive:archive_trigger')
        resp = self.client.post(
            url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 302)  # anon -> login
        self.client.force_login(self.viewer)     # lacks add_archivedstudy
        resp = self.client.post(
            url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    @mock.patch('dicom_archive.views.archive_studies_task')
    def test_archive_trigger_dispatches_and_reports(self, mock_task):
        mock_task.delay.return_value = SimpleNamespace(id='celery-archive-1')
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({
                'study_uids': [self.study.study_instance_uid],
                'location_id': self.location.pk,
            }),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['task_id'], 'celery-archive-1')
        self.assertEqual(body['redirect_url'],
                         reverse('client_app:taskrun_list'))
        self.assertIn('Archiving 1 study', body['message'])
        mock_task.delay.assert_called_once_with(
            [self.study.study_instance_uid], self.location.pk,
            user_id=self.admin.pk, reason='MANUAL')

    def test_archive_trigger_rejects_unknown_uid(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': ['1.9.9.9'],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('unknown or non-local', resp.json()['error'])

    def test_archive_trigger_rejects_inactive_location(self):
        self.client.force_login(self.admin)
        ArchiveLocation.objects.filter(pk=self.location.pk).update(
            is_active=False)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': [self.study.study_instance_uid],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('active archive location', resp.json()['error'])

    def test_archive_trigger_rejects_empty_and_bad_json(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({'study_uids': [],
                             'location_id': self.location.pk}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('non-empty list', resp.json()['error'])
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data='{not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'Invalid JSON body')

    def test_archive_trigger_dispatch_failure_is_500(self):
        with mock.patch(
                'dicom_archive.views.archive_studies_task') as mock_task:
            mock_task.delay.side_effect = RuntimeError('broker down')
            self.client.force_login(self.admin)
            resp = self.client.post(
                reverse('dicom_archive:archive_trigger'),
                data=json.dumps({'study_uids': [
                    self.study.study_instance_uid],
                    'location_id': self.location.pk}),
                content_type='application/json')
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()['error'],
                         'Could not dispatch archive task')

    @mock.patch('dicom_archive.views.dearchive_studies_task')
    def test_dearchive_trigger_dispatches(self, mock_task):
        mock_task.delay.return_value = SimpleNamespace(id='celery-dearch-1')
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:dearchive_trigger'),
            data=json.dumps(
                {'study_uids': [self.study.study_instance_uid]}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['task_id'], 'celery-dearch-1')
        self.assertEqual(body['redirect_url'],
                         reverse('client_app:taskrun_list'))
        self.assertIn('De-archiving 1 study', body['message'])
        mock_task.delay.assert_called_once_with(
            [self.study.study_instance_uid], user_id=self.admin.pk)

    def test_dearchive_trigger_rejects_non_archived_study(self):
        second = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.10',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.10',
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('dicom_archive:dearchive_trigger'),
            data=json.dumps(
                {'study_uids': [second.study_instance_uid]}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no archived study found', resp.json()['error'])

    def test_browse_page_carries_csrf_token_and_dispatch_passes_csrf(self):
        """Regression (production bug): the trigger JS reads the CSRF
        token from ``input[name=csrfmiddlewaretoken]``. The browse page
        only renders GET filter forms, so without an explicit
        ``{% csrf_token %}`` the real browser POST gets a 403 HTML page
        and the JS dies in JSON.parse. Django's test client does not
        enforce CSRF, so this test switches it on to prove the token on
        the page actually authorizes the dispatch."""
        self.client.force_login(self.admin)
        page = self.client.get(reverse('dicom_archive:browse'))
        match = re.search(
            rb'name="csrfmiddlewaretoken" value="([^"]+)"',
            page.content)
        self.assertIsNotNone(
            match, 'browse page has no CSRF token input')
        self.client.enforce_csrf_checks = True
        resp = self.client.post(
            reverse('dicom_archive:archive_trigger'),
            data=json.dumps({
                'study_uids': [self.study.study_instance_uid],
                'location_id': self.location.pk,
            }),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=match.group(1).decode())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('task_id', resp.json())


class TestTaskStatusView(ArchiveViewTestCase):
    def test_unknown_task_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=['nope']))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'task run not found')

    def test_status_by_celery_task_id(self):
        run = TaskRun.objects.create(
            task_id='celery-archive-1',
            task_name='archive_studies',
            task_type='DICOM_ARCHIVE',
            status=TaskRun.Status.PROGRESS,
            progress_current=3, progress_total=10,
            progress_description='3 of 10',
        )
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=[run.task_id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['task_run_id'], run.pk)
        self.assertEqual(body['status'], 'PROGRESS')
        self.assertEqual(body['progress_current'], 3)
        self.assertEqual(body['progress_percent'], 30)
        self.assertIsNone(body['completed_at'])

    def test_status_by_taskrun_pk(self):
        run = TaskRun.objects.create(
            task_id='celery-archive-2',
            task_name='dearchive_studies',
            task_type='DICOM_DEARCHIVE',
            status=TaskRun.Status.SUCCESS,
        )
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=[str(run.pk)]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['task_id'], 'celery-archive-2')

    def test_status_requires_perm(self):
        self.client.force_login(self.plain)
        resp = self.client.get(
            reverse('dicom_archive:task_status', args=['x']))
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_archive.tests.test_views.TestManualTriggers dicom_archive.tests.test_views.TestTaskStatusView -v 2`
Expected: FAIL — `NoReverseMatch` for `dicom_archive:archive_trigger` / `dearchive_trigger` / `task_status`.

- [ ] **Step 3: Implement the trigger + status views**

In `dicom_archive/views.py`, add to the top import block: `import json` and `from django.http import JsonResponse`, `from django.urls import reverse`, and extend the client_app import to `from client_app.models import DICOMStudy, TaskRun`; add `from dicom_archive.tasks import archive_studies_task, dearchive_studies_task`.

Append after `ArchiveLocationDeleteView`:

```python
# --- Manual triggers (JSON dispatch, BulkDeidentifyView response shape) ---

def _json_payload(request):
    """(payload, error_response) — same helper shape as dicom_server.views."""
    try:
        return json.loads(request.body or '{}'), None
    except json.JSONDecodeError:
        return None, JsonResponse({'error': 'Invalid JSON body'}, status=400)


class ManualArchiveView(ArchivePermissionRequiredMixin, View):
    """POST JSON {study_uids: [...], location_id: int} ->
    archive_studies_task.delay; response {task_id, redirect_url, message}."""
    permission_required = 'dicom_archive.add_archivedstudy'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        study_uids = payload.get('study_uids')
        if not isinstance(study_uids, list) or not study_uids:
            return JsonResponse(
                {'error': 'study_uids must be a non-empty list'}, status=400)
        location = ArchiveLocation.objects.filter(
            pk=payload.get('location_id'), is_active=True,
        ).first()
        if location is None:
            return JsonResponse(
                {'error': 'location_id must reference an active '
                          'archive location'},
                status=400,
            )
        known = set(DICOMStudy.objects.filter(
            study_instance_uid__in=study_uids, folder_path__isnull=False,
        ).values_list('study_instance_uid', flat=True))
        unknown = [u for u in study_uids if u not in known]
        if unknown:
            return JsonResponse(
                {'error': 'unknown or non-local study UID(s): '
                           + ', '.join(unknown[:5])},
                status=400,
            )
        try:
            result = archive_studies_task.delay(
                study_uids, location.pk,
                user_id=request.user.pk, reason='MANUAL',
            )
        except Exception:
            logger.exception('Failed to dispatch archive_studies_task')
            return JsonResponse(
                {'error': 'Could not dispatch archive task'}, status=500)
        return JsonResponse({
            'task_id': result.id,
            'redirect_url': reverse('client_app:taskrun_list'),
            'message': f'Archiving {len(study_uids)} study(s) to '
                       f'"{location.name}" in the background.',
        })


class ManualDearchiveView(ArchivePermissionRequiredMixin, View):
    """POST JSON {study_uids: [...]} -> dearchive_studies_task.delay;
    every UID must have an ArchivedStudy in status ARCHIVED."""
    permission_required = 'dicom_archive.add_archivedstudy'

    def post(self, request):
        payload, error = _json_payload(request)
        if error:
            return error
        study_uids = payload.get('study_uids')
        if not isinstance(study_uids, list) or not study_uids:
            return JsonResponse(
                {'error': 'study_uids must be a non-empty list'}, status=400)
        archived = set(ArchivedStudy.objects.filter(
            study__study_instance_uid__in=study_uids,
            status=ArchivedStudy.Status.ARCHIVED,
        ).values_list('study__study_instance_uid', flat=True))
        unknown = [u for u in study_uids if u not in archived]
        if unknown:
            return JsonResponse(
                {'error': 'no archived study found for UID(s): '
                           + ', '.join(unknown[:5])},
                status=400,
            )
        try:
            result = dearchive_studies_task.delay(
                study_uids, user_id=request.user.pk,
            )
        except Exception:
            logger.exception('Failed to dispatch dearchive_studies_task')
            return JsonResponse(
                {'error': 'Could not dispatch de-archive task'}, status=500)
        return JsonResponse({
            'task_id': result.id,
            'redirect_url': reverse('client_app:taskrun_list'),
            'message': f'De-archiving {len(study_uids)} study(s) in the '
                       'background.',
        })


class TaskStatusView(ArchivePermissionRequiredMixin, View):
    """GET — poll endpoint over client_app.TaskRun. task_run_id may be a
    TaskRun pk or the celery task id (TaskRun.task_id) returned by the
    trigger views; 404 until the task has created its TaskRun row."""
    permission_required = 'dicom_archive.view_archivedstudy'

    def get(self, request, task_run_id):
        run = TaskRun.objects.filter(pk=task_run_id).first() or (
            TaskRun.objects.filter(task_id=task_run_id).first()
        )
        if run is None:
            return JsonResponse({'error': 'task run not found'}, status=404)
        return JsonResponse({
            'task_run_id': run.pk,
            'task_id': run.task_id,
            'task_name': run.task_name,
            'task_type': run.task_type,
            'status': run.status,
            'progress_current': run.progress_current,
            'progress_total': run.progress_total,
            'progress_percent': run.progress_percent,
            'progress_description': run.progress_description,
            'result_summary': run.result_summary,
            'error_log': run.error_log or '',
            'completed_at': (
                run.completed_at.isoformat() if run.completed_at else None
            ),
        })
```

- [ ] **Step 4: Update the URLConf (final — full contract table)**

Replace `dicom_archive/urls.py` urlpatterns with:

```python
urlpatterns = [
    path('', views.ArchiveDashboardView.as_view(), name='dashboard'),
    path('config/', views.ArchiveConfigUpdateView.as_view(), name='config_edit'),
    path('locations/', views.ArchiveLocationListView.as_view(), name='location_list'),
    path('locations/add/', views.ArchiveLocationCreateView.as_view(), name='location_create'),
    path('locations/<int:pk>/edit/', views.ArchiveLocationUpdateView.as_view(), name='location_update'),
    path('locations/<int:pk>/delete/', views.ArchiveLocationDeleteView.as_view(), name='location_delete'),
    path('browse/', views.LocalStudyBrowserView.as_view(), name='browse'),
    path('archived/', views.ArchivedStudyListView.as_view(), name='archived_list'),
    path('archive/', views.ManualArchiveView.as_view(), name='archive_trigger'),
    path('dearchive/', views.ManualDearchiveView.as_view(), name='dearchive_trigger'),
    path('task-status/<str:task_run_id>/', views.TaskStatusView.as_view(), name='task_status'),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test dicom_archive.tests -v 2`
Expected: PASS (all of Tasks 1–3: 3 + 8 + 6 + 8 + 4 = 29 tests; 6 form tests from Task 2 counted in the 29).

- [ ] **Step 6: Commit** — executes ONLY after explicit user approval

```bash
git add dicom_archive/views.py dicom_archive/urls.py dicom_archive/tests/test_views.py
git commit -m "feat(dicom-archive): manual archive/de-archive triggers + task-status endpoint"
```

---

### Task 4: Templates in `templates/dicom_archive/`

**Files:**
- Create: `templates/dicom_archive/dashboard.html`
- Create: `templates/dicom_archive/config_edit.html`
- Create: `templates/dicom_archive/location_form.html`
- Create: `templates/dicom_archive/location_list.html`
- Create: `templates/dicom_archive/browse.html`
- Create: `templates/dicom_archive/archived_list.html`
- Test: `dicom_archive/tests/test_templates.py`

**Interfaces:**
- Consumes: Task 1–3 view context (Task 1: `config, default_location, status_counts, total_records, in_flight_count, recent_archived`; browse: `studies, locations, page_obj, query_string`; archived: `records, status_choices, locations, page_obj, query_string`; location list rows carry `loc.study_count`); url names `dashboard, config_edit, location_list, location_create, location_update, location_delete, browse, archived_list, archive_trigger, dearchive_trigger, task_status`, plus existing `client_app:taskrun_list`; components from `components/ui.py` (`page_header` title/subtitle/back_url/back_text + actions slot, `card` title/accent + body/footer slots, `button` style/href/icon/size/type, `badge` style, `table` compact + head/body slots, `stat_card` icon/style/label/value, `empty_state` title/description + action slot, `info_box` style + default slot, `icon_button` icon/style/aria_label/href/title/type, `pagination` page_obj/query_string); trigger JSON shapes `{task_id, redirect_url, message}` and task-status JSON from Task 3; permission context keys (e.g. `perms.dicom_archive.add_archivedstudy`).
- Produces: six rendered pages. JS contract inside the pages (used by tests and later manual QA): `browse.html` exposes `#archive-location` select, `#archive-selected-btn`, `.study-uid-check` checkboxes, `#select-all-studies`, `#task-status-box/-msg/-track/-progress`, `#task-run-link`, consts `ARCHIVE_URL`/`TASK_STATUS_URL`; `archived_list.html` exposes `#dearchive-selected-btn`, `.archived-uid-check`, `#select-all-archived`, same `task-status-*` ids and `DEARCHIVE_URL`/`TASK_STATUS_URL`.

- [ ] **Step 1: Write the failing tests**

Create `dicom_archive/tests/test_templates.py`:

```python
"""Render tests for the dicom_archive templates (plan 03, Task 4)."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from client_app.models import DICOMStudy
from dicom_archive.models import ArchivedStudy
from dicom_archive.tests.test_views import ArchiveViewTestCase


class TestPageRendering(ArchiveViewTestCase):
    def setUp(self):
        super().setUp()  # cache.clear() from ArchiveViewTestCase
        self.client.force_login(self.admin)

    def test_dashboard_renders_config_and_recent(self):
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'Archive Configuration')
        self.assertContains(resp, 'Default Archive Location')
        self.assertContains(resp, self.study.study_instance_uid)
        self.assertContains(resp, 'Manage locations')

    def test_dashboard_config_card_reflects_defaults(self):
        # no config row in the DB -> ArchiveConfiguration.load() creates
        # the singleton with defaults (archive_after_days=90, enabled=False)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, '90 days')
        self.assertContains(resp, 'Disabled')

    def test_config_edit_renders_form_fields(self):
        resp = self.client.get(reverse('dicom_archive:config_edit'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'archive_after_days')
        self.assertContains(resp, 'archive_minute')
        self.assertContains(resp, 'batch_limit')

    def test_location_list_shows_location_and_delete_form(self):
        resp = self.client.get(reverse('dicom_archive:location_list'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'NAS archive')
        self.assertContains(
            resp,
            reverse('dicom_archive:location_delete', args=[self.location.pk]))

    def test_location_form_renders_for_create(self):
        resp = self.client.get(reverse('dicom_archive:location_create'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'storage_type')
        self.assertContains(resp, 'path')

    def test_browse_renders_rows_with_checkboxes_and_triggers(self):
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, self.study.study_instance_uid)
        self.assertContains(resp, 'archive-selected-btn')
        self.assertContains(resp, 'study-uid-check')
        self.assertContains(resp, reverse('dicom_archive:archive_trigger'))
        self.assertContains(
            resp, reverse('dicom_archive:task_status', args=['0']))

    def test_browse_hides_trigger_ui_without_add_perm(self):
        self.client.force_login(self.viewer)  # view only, no add_archivedstudy
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'archive-selected-btn')
        self.assertNotContains(
            resp, reverse('dicom_archive:archive_trigger'))

    def test_browse_filters_by_q(self):
        DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            study_date='2025-02-01',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        resp = self.client.get(
            reverse('dicom_archive:browse') + '?q=1.2.3.4.5.6.7.8.42')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.9')

    def test_browse_paginates_at_25(self):
        for i in range(30):
            uid = f'1.2.88.{i:02d}.1'
            DICOMStudy.objects.create(
                patient=self.patient, study_instance_uid=uid,
                folder_path=f'/media/processed_dicom/p/{uid}')
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertEqual(len(resp.context['studies']), 25)
        # fixture study + 30 = 31 rows -> page 2 holds 6
        resp = self.client.get(reverse('dicom_archive:browse') + '?page=2')
        self.assertEqual(len(resp.context['studies']), 6)

    def test_archived_list_renders_with_filters_and_trigger(self):
        resp = self.client.get(reverse('dicom_archive:archived_list'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertContains(resp, 'NAS archive')
        self.assertContains(resp, 'dearchive-selected-btn')
        self.assertContains(resp, reverse('dicom_archive:dearchive_trigger'))

    def test_archived_list_defaults_to_archived_only(self):
        """De-archived studies are local again — the default view must
        not show them; they remain reachable via the status filter."""
        other_study = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        ArchivedStudy.objects.create(
            study=other_study, location=self.location,
            status=ArchivedStudy.Status.DEARCHIVED,
            local_path_before=other_study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.42',
            dearchived_at=timezone.now(),
        )
        # default: ARCHIVED only — the DEARCHIVED study is hidden
        resp = self.client.get(reverse('dicom_archive:archived_list'))
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.42')
        # explicit DEARCHIVED filter shows it
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=DEARCHIVED')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.9')
        # "All statuses" (?status= present but empty) shows both
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')

    def test_archived_list_filters_by_status_and_location(self):
        other_study = DICOMStudy.objects.create(
            patient=self.patient,
            study_instance_uid='1.2.3.4.5.6.7.8.42',
            folder_path='/media/processed_dicom/MR_25_000001/1.2.3.4.5.6.7.8.42',
        )
        ArchivedStudy.objects.create(
            study=other_study, location=self.location,
            status=ArchivedStudy.Status.DEARCHIVED,
            local_path_before=other_study.folder_path,
            archive_rel_path='MR_25_000001/1.2.3.4.5.6.7.8.42',
            dearchived_at=timezone.now(),
        )
        resp = self.client.get(
            reverse('dicom_archive:archived_list') + '?status=ARCHIVED')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.9')
        self.assertNotContains(resp, '1.2.3.4.5.6.7.8.42')
        resp = self.client.get(
            reverse('dicom_archive:archived_list')
            + f'?status=DEARCHIVED&location_id={self.location.pk}')
        self.assertContains(resp, '1.2.3.4.5.6.7.8.42')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test dicom_archive.tests.test_templates -v 2`
Expected: FAIL — `TemplateDoesNotExist: dicom_archive/dashboard.html` (and siblings).

- [ ] **Step 3: Create `templates/dicom_archive/dashboard.html`**

```html
{% extends "base.html" %}
{% block title %}DICOM Archive - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-7xl mx-auto px-4 py-8">
    {% url 'dicom_archive:browse' as browse_url %}
    {% url 'dicom_archive:archived_list' as archived_url %}
    {% url 'dicom_archive:location_list' as locations_url %}
    {% url 'dicom_archive:config_edit' as config_url %}
    {% component "page_header" title="DICOM Archive" icon="fas fa-warehouse" subtitle="Archive local DICOM study folders to a configurable location and restore them on demand" %}
        {% fill "actions" %}
        {% if perms.dicom_archive.view_archivedstudy %}
        {% component "button" style="primary" href=browse_url icon="fas fa-folder-open" %}Browse Studies{% endcomponent %}
        {% component "button" style="secondary" href=archived_url icon="fas fa-list" %}Archived Studies{% endcomponent %}
        {% endif %}
        {% if perms.dicom_archive.view_archivelocation %}
        {% component "button" style="secondary" href=locations_url icon="fas fa-server" %}Locations{% endcomponent %}
        {% endif %}
        {% if perms.dicom_archive.change_archiveconfiguration %}
        {% component "button" style="secondary" href=config_url icon="fas fa-edit" %}Configuration{% endcomponent %}
        {% endif %}
        {% endfill %}
    {% endcomponent %}

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {% component "stat_card" icon="fas fa-database" style="primary" label="Total archive records" value=total_records %}{% endcomponent %}
        {% component "stat_card" icon="fas fa-inbox" style="success" label="Archived" value=status_counts.ARCHIVED %}{% endcomponent %}
        {% component "stat_card" icon="fas fa-hourglass-half" style="warning" label="Archiving / Restoring" value=in_flight_count %}{% endcomponent %}
        {% component "stat_card" icon="fas fa-undo" style="gray" label="De-archived" value=status_counts.DEARCHIVED %}{% endcomponent %}
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {% component "card" title="Archive Configuration" accent="charcoal" %}
            {% fill "body" %}
            <dl class="text-sm space-y-1">
                <div class="flex justify-between"><dt class="text-gray-500">Scheduled archival</dt><dd>{% if config.enabled %}{% component "badge" style="success" %}Enabled{% endcomponent %}{% else %}{% component "badge" style="danger" %}Disabled{% endcomponent %}{% endif %}</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">Archive studies older than</dt><dd>{{ config.archive_after_days }} days</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">After archiving</dt><dd>{% if config.delete_local_after_archive %}Local files are deleted{% else %}Local copy is kept{% endif %}</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">Schedule</dt><dd class="font-mono text-xs">{{ config.archive_minute }} {{ config.archive_hour }} {{ config.archive_day_of_week }} {{ config.archive_day_of_month }} {{ config.archive_month_of_year }}</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">Batch limit per run</dt><dd>{{ config.batch_limit }} studies</dd></div>
            </dl>
            {% endfill %}
            {% if perms.dicom_archive.change_archiveconfiguration %}
            {% fill "footer" %}
                {% component "button" style="link" size="sm" href=config_url icon="fas fa-edit" %}Edit configuration{% endcomponent %}
            {% endfill %}
            {% endif %}
        {% endcomponent %}

        {% component "card" title="Default Archive Location" accent="charcoal" %}
            {% fill "body" %}
            {% if default_location %}
            <dl class="text-sm space-y-1">
                <div class="flex justify-between"><dt class="text-gray-500">Name</dt><dd class="font-medium">{{ default_location.name }}</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">Type</dt><dd>{{ default_location.get_storage_type_display }}</dd></div>
                <div class="flex justify-between"><dt class="text-gray-500">Path</dt><dd class="font-mono text-xs break-all text-right max-w-[70%]">{{ default_location.resolved_path }}</dd></div>
            </dl>
            {% else %}
            <p class="text-sm text-gray-500">No default archive location configured. The scheduled sweep needs a default active location.</p>
            {% endif %}
            {% endfill %}
            {% if perms.dicom_archive.view_archivelocation %}
            {% fill "footer" %}
                {% component "button" style="link" size="sm" href=locations_url icon="fas fa-server" %}Manage locations{% endcomponent %}
            {% endfill %}
            {% endif %}
        {% endcomponent %}
    </div>

    {% component "card" title="Recent Archived Studies" accent="primary" extra_class="mb-8" %}
        {% fill "body" %}
        {% if recent_archived %}
        {% component "table" compact=True %}
            {% fill "head" %}
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Study UID</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Patient</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Status</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Location</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Archived</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">By</th>
            {% endfill %}
            {% fill "body" %}
            {% for record in recent_archived %}
            <tr>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-mono text-xs">{{ record.study.study_instance_uid|truncatechars:24 }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ record.study.patient.patient_id }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">
                    {% if record.status == 'ARCHIVED' %}{% component "badge" style="success" %}{{ record.get_status_display }}{% endcomponent %}
                    {% elif record.status == 'DEARCHIVED' %}{% component "badge" style="gray" %}{{ record.get_status_display }}{% endcomponent %}
                    {% else %}{% component "badge" style="warning" %}{{ record.get_status_display }}{% endcomponent %}
                    {% endif %}
                </td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ record.location.name }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{{ record.archived_at|date:"Y-m-d H:i"|default:"—" }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{{ record.archived_by|default:"—" }}</td>
            </tr>
            {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% else %}
        <p class="text-sm text-gray-500">No studies have been archived yet.</p>
        {% endif %}
        {% endfill %}
        {% if perms.dicom_archive.view_archivedstudy %}
        {% fill "footer" %}
            {% component "button" style="link" size="sm" href=archived_url icon="fas fa-list" %}View all archived studies{% endcomponent %}
        {% endfill %}
        {% endif %}
    {% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 4: Create `templates/dicom_archive/config_edit.html`**

(Mirrors `templates/dicom_server/config_form.html`.)

```html
{% extends "base.html" %}
{% load crispy_forms_tags %}
{% block title %}DICOM Archive Configuration - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto px-4 py-8">
    {% url 'dicom_archive:dashboard' as dash_url %}
    {% component "page_header" title="DICOM Archive Configuration" icon="fas fa-warehouse" back_url=dash_url back_text="Back to archive" %}{% endcomponent %}
    {% component "card" %}{% fill "body" %}
        <form method="post">
            {% csrf_token %}
            {{ form|crispy }}
            <div class="mt-6 flex space-x-3">
                {% component "button" style="primary" type="submit" icon="fas fa-save" %}Save{% endcomponent %}
                {% component "button" style="secondary" href=dash_url %}Cancel{% endcomponent %}
            </div>
        </form>
        {% component "info_box" style="info" %}
            {% fill "default" %}
            Saving updates the django-celery-beat schedule for the periodic sweep automatically (post-save signal in dicom_archive). Cron fields accept digits, commas, dashes, asterisks and forward slashes.
            {% endfill %}
        {% endcomponent %}
    {% endfill %}{% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 5: Create `templates/dicom_archive/location_form.html`**

(Mirrors `templates/dicom_server/node_form.html`.)

```html
{% extends "base.html" %}
{% load crispy_forms_tags %}
{% block title %}{% if object %}Edit{% else %}Add{% endif %} Archive Location - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-2xl mx-auto px-4 py-8">
    {% url 'dicom_archive:location_list' as back_url %}
    {% if object %}
    {% component "page_header" title="Edit Archive Location" icon="fas fa-server" back_url=back_url back_text="Back to locations" %}{% endcomponent %}
    {% else %}
    {% component "page_header" title="Add Archive Location" icon="fas fa-server" back_url=back_url back_text="Back to locations" %}{% endcomponent %}
    {% endif %}
    {% component "card" %}{% fill "body" %}
        <form method="post">
            {% csrf_token %}
            {{ form|crispy }}
            <div class="mt-6 flex space-x-3">
                {% component "button" style="primary" type="submit" icon="fas fa-save" %}Save{% endcomponent %}
                {% component "button" style="secondary" href=back_url %}Cancel{% endcomponent %}
            </div>
        </form>
        {% component "info_box" style="info" %}
            {% fill "default" %}
            The path is checked for write access when you save. Local folders may be absolute or relative to the media root; mounted shares (NAS/LAN) must use an absolute path.
            {% endfill %}
        {% endcomponent %}
    {% endfill %}{% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 6: Create `templates/dicom_archive/location_list.html`**

(Mirrors `templates/dicom_server/node_list.html`; delete is an inline POST form with client-side confirm — design note 2.)

```html
{% extends "base.html" %}
{% block title %}Archive Locations - CHAVI Client{% endblock %}
{% block content %}
<div class="max-w-5xl mx-auto px-4 py-8">
    {% url 'dicom_archive:dashboard' as dash_url %}
    {% url 'dicom_archive:location_create' as add_url %}
    {% component "page_header" title="Archive Locations" icon="fas fa-server" back_url=dash_url back_text="Back to archive" %}
        {% fill "actions" %}
        {% if perms.dicom_archive.add_archivelocation %}
        {% component "button" style="primary" href=add_url icon="fas fa-plus" %}Add Location{% endcomponent %}
        {% endif %}
        {% endfill %}
    {% endcomponent %}

    {% component "card" %}
        {% fill "body" %}
        {% if locations %}
        {% component "table" %}
            {% fill "head" %}
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Name</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Type</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Path</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Default</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Active</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Archived Studies</th>
            <th class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider">Actions</th>
            {% endfill %}
            {% fill "body" %}
            {% for loc in locations %}
            <tr>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{{ loc.name }}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm">{{ loc.get_storage_type_display }}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-xs text-gray-500">{{ loc.resolved_path }}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm">{% if loc.is_default %}{% component "badge" style="success" %}Yes{% endcomponent %}{% else %}{% component "badge" style="gray" %}No{% endcomponent %}{% endif %}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm">{% if loc.is_active %}{% component "badge" style="success" %}Yes{% endcomponent %}{% else %}{% component "badge" style="danger" %}No{% endcomponent %}{% endif %}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm">{{ loc.study_count }}</td>
                <td class="px-6 py-4 whitespace-nowrap text-sm space-x-2">
                    {% if perms.dicom_archive.change_archivelocation %}
                    {% url 'dicom_archive:location_update' loc.pk as edit_url %}
                    {% component "icon_button" icon="fas fa-edit" aria_label="Edit" href=edit_url title="Edit" %}{% endcomponent %}
                    {% endif %}
                    {% if perms.dicom_archive.delete_archivelocation %}
                    <form method="post" action="{% url 'dicom_archive:location_delete' loc.pk %}" class="inline"
                          onsubmit="return confirm('Delete archive location {{ loc.name|escapejs }}? Locations that still hold archived studies cannot be deleted.');">
                        {% csrf_token %}
                        {% component "icon_button" icon="fas fa-trash" style="danger" type="submit" aria_label="Delete" title="Delete" %}{% endcomponent %}
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% else %}
        {% component "empty_state" title="No archive locations configured" description="Add a location (local folder or mounted NAS/LAN share) to enable archiving." %}
            {% fill "action" %}
            {% if perms.dicom_archive.add_archivelocation %}
            {% component "button" style="primary" href=add_url icon="fas fa-plus" %}Add Location{% endcomponent %}
            {% endif %}
            {% endfill %}
        {% endcomponent %}
        {% endif %}
        {% endfill %}
    {% endcomponent %}
</div>
{% endblock %}
```

- [ ] **Step 7: Create `templates/dicom_archive/browse.html`**

(Trigger JS: fetch + 3000 ms polling, pattern from `templates/dicom_server/batch_select.html` — `postJSON`/`pkUrl`/`csrf()` helpers, terminal states from design note 8.)

```html
{% extends "base.html" %}
{% block title %}Local Studies - DICOM Archive{% endblock %}
{% block content %}
<div class="max-w-7xl mx-auto px-4 py-8">
    {% url 'dicom_archive:dashboard' as dash_url %}
    {% url 'dicom_archive:archived_list' as archived_url %}
    {% url 'dicom_archive:location_list' as locations_url %}
    {% component "page_header" title="Local Studies" icon="fas fa-folder-open" subtitle="Studies with a local folder — select to archive" back_url=dash_url back_text="Back to archive" %}
        {% fill "actions" %}
        {% if perms.dicom_archive.view_archivedstudy %}
        {% component "button" style="secondary" href=archived_url icon="fas fa-list" %}Archived Studies{% endcomponent %}
        {% endif %}
        {% if perms.dicom_archive.view_archivelocation %}
        {% component "button" style="secondary" href=locations_url icon="fas fa-server" %}Locations{% endcomponent %}
        {% endif %}
        {% endfill %}
    {% endcomponent %}

    {% component "card" %}
        {% fill "body" %}
        <form method="get" class="flex flex-wrap items-center gap-3 mb-4">
            <input type="search" name="q" value="{{ request.GET.q }}" placeholder="Search patient ID or study UID"
                   class="w-72 px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-chavi-primary focus:border-chavi-primary">
            <button type="submit" class="px-4 py-2 text-sm font-medium bg-chavi-primary-600 text-white rounded-md hover:bg-chavi-primary-700">
                <i class="fas fa-search mr-2"></i>Search
            </button>
            {% if request.GET.q %}
            <a href="{% url 'dicom_archive:browse' %}" class="text-sm text-chavi-primary hover:underline">Clear</a>
            {% endif %}
        </form>

        {% if perms.dicom_archive.add_archivedstudy %}
        <div class="flex items-center justify-between mb-3">
            <label class="flex items-center gap-2 text-sm text-gray-700">
                Archive to:
                <select id="archive-location" class="px-2 py-1 text-sm border border-gray-300 rounded-md">
                    {% for loc in locations %}
                    <option value="{{ loc.pk }}" {% if loc.is_default %}selected{% endif %}>{{ loc.name }} ({{ loc.get_storage_type_display }})</option>
                    {% endfor %}
                </select>
            </label>
            <button type="button" id="archive-selected-btn" disabled
                    class="px-4 py-2 text-sm font-medium bg-chavi-primary-600 text-white rounded-md hover:bg-chavi-primary-700 disabled:bg-gray-300 disabled:cursor-not-allowed">
                <i class="fas fa-upload mr-2"></i>Archive Selected
            </button>
        </div>
        {% endif %}

        {% if studies %}
        {% component "table" %}
            {% fill "head" %}
            <th class="px-4 py-2 w-8"><input type="checkbox" id="select-all-studies" class="align-middle" title="Select all on this page"></th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Patient</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Study UID</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Date</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Local folder</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Archive status</th>
            {% endfill %}
            {% fill "body" %}
            {% for study in studies %}
            <tr>
                <td class="px-4 py-2">
                    <input type="checkbox" class="study-uid-check" value="{{ study.study_instance_uid }}"
                        {% if study.archive_record and study.archive_record.status == 'ARCHIVED' %}disabled title="Already archived — de-archive it first from the Archived list"{% endif %}>
                </td>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-medium">{{ study.patient.patient_id }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-mono text-xs">{{ study.study_instance_uid|truncatechars:24 }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ study.study_date|date:"Y-m-d"|default:"—" }}</td>
                <td class="px-4 py-2 text-sm font-mono text-xs text-gray-500">{{ study.folder_path|truncatechars:48 }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">
                    {% with rec=study.archive_record %}
                    {% if rec is None %}
                    {% component "badge" style="info" %}Local{% endcomponent %}
                    {% elif rec.status == 'ARCHIVING' %}
                    {% component "badge" style="warning" %}Archiving…{% endcomponent %}
                    {% elif rec.status == 'ARCHIVED' %}
                    {% component "badge" style="success" %}Archived{% endcomponent %}
                    {% elif rec.status == 'DEARCHIVING' %}
                    {% component "badge" style="warning" %}Restoring…{% endcomponent %}
                    {% else %}
                    {% component "badge" style="gray" %}De-archived{% endcomponent %}
                    {% endif %}
                    {% endwith %}
                </td>
            </tr>
            {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% else %}
        <p class="text-sm text-gray-500">No local studies found.</p>
        {% endif %}

        {% component "pagination" page_obj=page_obj query_string=query_string is_paginated=True %}{% endcomponent %}
        {% endfill %}
    {% endcomponent %}

    {% if perms.dicom_archive.add_archivedstudy %}
    <div id="task-status-box" class="hidden mt-4 rounded-md border border-chavi-primary-200 bg-chavi-primary-50 p-4">
        <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
        <div class="flex items-center justify-between text-sm gap-3">
            <span id="task-status-msg" class="text-gray-700">Working…</span>
            <a id="task-run-link" href="{% url 'client_app:taskrun_list' %}" class="text-chavi-primary hover:underline whitespace-nowrap">View task runs</a>
        </div>
        <div id="task-status-track" class="hidden mt-2 h-2 rounded bg-chavi-primary-100">
            <div id="task-status-progress" class="h-2 rounded bg-chavi-primary-500" style="width:0%"></div>
        </div>
    </div>
    {% endif %}
</div>
{% endblock %}
{% block extra_js %}
{% if perms.dicom_archive.add_archivedstudy %}
<script>
(function () {
    'use strict';
    const ARCHIVE_URL = '{% url "dicom_archive:archive_trigger" %}';
    const TASK_STATUS_URL = '{% url "dicom_archive:task_status" task_run_id="0" %}';
    const TERMINAL = ['SUCCESS', 'FAILURE', 'STALLED', 'CANCELLED'];
    let pollTimer = null;

    function csrf() {
        const input = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (input) return input.value;
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }
    function pkUrl(url, pk) { return url.replace('/0/', '/' + pk + '/'); }
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
            body: JSON.stringify(body || {}),
        }).then(r => r.text().then(t => {
            let j; try { j = JSON.parse(t); } catch (e) { j = null; }
            return {ok: r.ok, status: r.status, body: j, raw: t};
        }));
    }
    function selectedUids() {
        return Array.from(
            document.querySelectorAll('.study-uid-check:not(:disabled):checked')
        ).map(c => c.value);
    }
    function setBusy(msg) {
        document.getElementById('task-status-box').classList.remove('hidden');
        document.getElementById('task-status-msg').textContent = msg;
        document.getElementById('archive-selected-btn').disabled = true;
    }
    function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
    function finish(body) {
        stopPoll();
        const msg = document.getElementById('task-status-msg');
        if (body.status === 'SUCCESS') {
            msg.textContent = 'Archive run finished. ' + (body.progress_description || '');
        } else {
            msg.textContent = 'Task ended: ' + body.status +
                (body.error_log ? ' — ' + body.error_log : '');
        }
        document.getElementById('archive-selected-btn')
            .disabled = selectedUids().length === 0;
    }
    function pollTask(taskId) {
        fetch(pkUrl(TASK_STATUS_URL, taskId))
            .then(r => r.ok ? r.json() : null)
            .then(body => {
                if (!body) return; // TaskRun row not created yet — keep polling
                if (body.progress_total > 0) {
                    document.getElementById('task-status-track')
                        .classList.remove('hidden');
                    document.getElementById('task-status-progress')
                        .style.width = body.progress_percent + '%';
                }
                if (TERMINAL.includes(body.status)) finish(body);
            })
            .catch(() => {});
    }
    function archiveSelected() {
        const uids = selectedUids();
        if (!uids.length) return;
        const locationId = parseInt(
            document.getElementById('archive-location').value, 10);
        setBusy('Dispatching archive for ' + uids.length + ' study(s)…');
        postJSON(ARCHIVE_URL, {study_uids: uids, location_id: locationId})
            .then(res => {
                if (!res.ok) {
                    setBusy(res.body && res.body.error ? res.body.error
                        : 'Request failed (HTTP ' + res.status + ')');
                    document.getElementById('archive-selected-btn')
                        .disabled = false;
                    return;
                }
                document.getElementById('task-run-link')
                    .href = res.body.redirect_url;
                document.getElementById('task-status-msg')
                    .textContent = res.body.message;
                stopPoll();
                pollTask(res.body.task_id);
                pollTimer = setInterval(
                    () => pollTask(res.body.task_id), 3000);
            });
    }
    document.addEventListener('DOMContentLoaded', function () {
        const btn = document.getElementById('archive-selected-btn');
        if (!btn) return;
        btn.addEventListener('click', archiveSelected);
        const all = document.getElementById('select-all-studies');
        if (all) {
            all.addEventListener('change', function () {
                document.querySelectorAll('.study-uid-check:not(:disabled)')
                    .forEach(c => { c.checked = all.checked; });
                btn.disabled = selectedUids().length === 0;
            });
        }
        document.querySelectorAll('.study-uid-check').forEach(function (c) {
            c.addEventListener('change', function () {
                btn.disabled = selectedUids().length === 0;
            });
        });
    });
})();
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 8: Create `templates/dicom_archive/archived_list.html`**

(Filter form = GET `status` + `location_id`; de-archive trigger JS mirrors the browse page, polling the same task-status endpoint.)

```html
{% extends "base.html" %}
{% block title %}Archived Studies - DICOM Archive{% endblock %}
{% block content %}
<div class="max-w-7xl mx-auto px-4 py-8">
    {% url 'dicom_archive:dashboard' as dash_url %}
    {% url 'dicom_archive:browse' as browse_url %}
    {% component "page_header" title="Archived Studies" icon="fas fa-database" subtitle="Studies stored in an archive location" back_url=dash_url back_text="Back to archive" %}
        {% fill "actions" %}
        {% if perms.dicom_archive.view_archivedstudy %}
        {% component "button" style="secondary" href=browse_url icon="fas fa-folder-open" %}Local Studies{% endcomponent %}
        {% endif %}
        {% endfill %}
    {% endcomponent %}

    {% component "card" %}
        {% fill "body" %}
        <form method="get" class="flex flex-wrap items-center gap-3 mb-4">
            <select name="status" class="px-2 py-1 text-sm border border-gray-300 rounded-md">
                <option value="" {% if active_status == '' %}selected{% endif %}>All statuses</option>
                {% for value, label in status_choices %}
                <option value="{{ value }}" {% if active_status == value %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
            <select name="location_id" class="px-2 py-1 text-sm border border-gray-300 rounded-md">
                <option value="">All locations</option>
                {% for loc in locations %}
                <option value="{{ loc.pk }}" {% if request.GET.location_id == loc.pk|stringformat:"s" %}selected{% endif %}>{{ loc.name }}</option>
                {% endfor %}
            </select>
            <button type="submit" class="px-4 py-2 text-sm font-medium bg-chavi-primary-600 text-white rounded-md hover:bg-chavi-primary-700">
                <i class="fas fa-filter mr-2"></i>Apply
            </button>
            {% if request.GET.status or request.GET.location_id %}
            <a href="{% url 'dicom_archive:archived_list' %}" class="text-sm text-chavi-primary hover:underline">Clear</a>
            {% endif %}
        </form>

        {% if perms.dicom_archive.add_archivedstudy %}
        <div class="flex items-center justify-between mb-3">
            <span class="text-sm text-gray-500">Select archived studies to de-archive (restore locally)</span>
            <button type="button" id="dearchive-selected-btn" disabled
                    class="px-4 py-2 text-sm font-medium bg-chavi-primary-600 text-white rounded-md hover:bg-chavi-primary-700 disabled:bg-gray-300 disabled:cursor-not-allowed">
                <i class="fas fa-download mr-2"></i>De-archive Selected
            </button>
        </div>
        {% endif %}

        {% if records %}
        {% component "table" %}
            {% fill "head" %}
            <th class="px-4 py-2 w-8"><input type="checkbox" id="select-all-archived" class="align-middle" title="Select all archived on this page"></th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Patient</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Study UID</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Status</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Location</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Size</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Instances</th>
            <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wider">Archived</th>
            {% endfill %}
            {% fill "body" %}
            {% for record in records %}
            <tr>
                <td class="px-4 py-2">
                    {% if record.status == 'ARCHIVED' and perms.dicom_archive.add_archivedstudy %}
                    <input type="checkbox" class="archived-uid-check" value="{{ record.study.study_instance_uid }}">
                    {% endif %}
                </td>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-medium">{{ record.study.patient.patient_id }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-mono text-xs">{{ record.study.study_instance_uid|truncatechars:24 }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">
                    {% if record.status == 'ARCHIVING' %}
                    {% component "badge" style="warning" %}{{ record.get_status_display }}{% endcomponent %}
                    {% elif record.status == 'ARCHIVED' %}
                    {% component "badge" style="success" %}{{ record.get_status_display }}{% endcomponent %}
                    {% elif record.status == 'DEARCHIVING' %}
                    {% component "badge" style="warning" %}{{ record.get_status_display }}{% endcomponent %}
                    {% else %}
                    {% component "badge" style="gray" %}{{ record.get_status_display }}{% endcomponent %}
                    {% endif %}
                    {% if record.error_log %}
                    <i class="fas fa-exclamation-triangle text-chavi-peach-500 ml-1" title="{{ record.error_log }}"></i>
                    {% endif %}
                </td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ record.location.name }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ record.size_bytes|filesizeformat }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm">{{ record.instance_count }}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm text-gray-500">{{ record.archived_at|date:"Y-m-d H:i"|default:"—" }}</td>
            </tr>
            {% endfor %}
            {% endfill %}
        {% endcomponent %}
        {% else %}
        <p class="text-sm text-gray-500">No archived studies match the current filters.</p>
        {% endif %}

        {% component "pagination" page_obj=page_obj query_string=query_string is_paginated=True %}{% endcomponent %}
        {% endfill %}
    {% endcomponent %}

    {% if perms.dicom_archive.add_archivedstudy %}
    <div id="task-status-box" class="hidden mt-4 rounded-md border border-chavi-primary-200 bg-chavi-primary-50 p-4">
        <input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf_token }}">
        <div class="flex items-center justify-between text-sm gap-3">
            <span id="task-status-msg" class="text-gray-700">Working…</span>
            <a id="task-run-link" href="{% url 'client_app:taskrun_list' %}" class="text-chavi-primary hover:underline whitespace-nowrap">View task runs</a>
        </div>
        <div id="task-status-track" class="hidden mt-2 h-2 rounded bg-chavi-primary-100">
            <div id="task-status-progress" class="h-2 rounded bg-chavi-primary-500" style="width:0%"></div>
        </div>
    </div>
    {% endif %}
</div>
{% endblock %}
{% block extra_js %}
{% if perms.dicom_archive.add_archivedstudy %}
<script>
(function () {
    'use strict';
    const DEARCHIVE_URL = '{% url "dicom_archive:dearchive_trigger" %}';
    const TASK_STATUS_URL = '{% url "dicom_archive:task_status" task_run_id="0" %}';
    const TERMINAL = ['SUCCESS', 'FAILURE', 'STALLED', 'CANCELLED'];
    let pollTimer = null;

    function csrf() {
        const input = document.querySelector('input[name=csrfmiddlewaretoken]');
        if (input) return input.value;
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }
    function pkUrl(url, pk) { return url.replace('/0/', '/' + pk + '/'); }
    function postJSON(url, body) {
        return fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
            body: JSON.stringify(body || {}),
        }).then(r => r.text().then(t => {
            let j; try { j = JSON.parse(t); } catch (e) { j = null; }
            return {ok: r.ok, status: r.status, body: j, raw: t};
        }));
    }
    function selectedUids() {
        return Array.from(
            document.querySelectorAll('.archived-uid-check:checked')
        ).map(c => c.value);
    }
    function setBusy(msg) {
        document.getElementById('task-status-box').classList.remove('hidden');
        document.getElementById('task-status-msg').textContent = msg;
        document.getElementById('dearchive-selected-btn').disabled = true;
    }
    function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
    function finish(body) {
        stopPoll();
        const msg = document.getElementById('task-status-msg');
        if (body.status === 'SUCCESS') {
            msg.textContent = 'De-archive run finished. ' + (body.progress_description || '');
        } else {
            msg.textContent = 'Task ended: ' + body.status +
                (body.error_log ? ' — ' + body.error_log : '');
        }
        document.getElementById('dearchive-selected-btn')
            .disabled = selectedUids().length === 0;
    }
    function pollTask(taskId) {
        fetch(pkUrl(TASK_STATUS_URL, taskId))
            .then(r => r.ok ? r.json() : null)
            .then(body => {
                if (!body) return; // TaskRun row not created yet — keep polling
                if (body.progress_total > 0) {
                    document.getElementById('task-status-track')
                        .classList.remove('hidden');
                    document.getElementById('task-status-progress')
                        .style.width = body.progress_percent + '%';
                }
                if (TERMINAL.includes(body.status)) finish(body);
            })
            .catch(() => {});
    }
    function dearchiveSelected() {
        const uids = selectedUids();
        if (!uids.length) return;
        setBusy('Dispatching de-archive for ' + uids.length + ' study(s)…');
        postJSON(DEARCHIVE_URL, {study_uids: uids})
            .then(res => {
                if (!res.ok) {
                    setBusy(res.body && res.body.error ? res.body.error
                        : 'Request failed (HTTP ' + res.status + ')');
                    document.getElementById('dearchive-selected-btn')
                        .disabled = false;
                    return;
                }
                document.getElementById('task-run-link')
                    .href = res.body.redirect_url;
                document.getElementById('task-status-msg')
                    .textContent = res.body.message;
                stopPoll();
                pollTask(res.body.task_id);
                pollTimer = setInterval(
                    () => pollTask(res.body.task_id), 3000);
            });
    }
    document.addEventListener('DOMContentLoaded', function () {
        const btn = document.getElementById('dearchive-selected-btn');
        if (!btn) return;
        btn.addEventListener('click', dearchiveSelected);
        const all = document.getElementById('select-all-archived');
        if (all) {
            all.addEventListener('change', function () {
                document.querySelectorAll('.archived-uid-check')
                    .forEach(c => { c.checked = all.checked; });
                btn.disabled = selectedUids().length === 0;
            });
        }
        document.querySelectorAll('.archived-uid-check').forEach(function (c) {
            c.addEventListener('change', function () {
                btn.disabled = selectedUids().length === 0;
            });
        });
    });
})();
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python manage.py test dicom_archive.tests -v 2`
Expected: PASS — all tests from Tasks 1–4 (29 previous + 12 new render tests = 41).

- [ ] **Step 10: Commit** — executes ONLY after explicit user approval

```bash
git add templates/dicom_archive/ dicom_archive/tests/test_templates.py
git commit -m "feat(dicom-archive): templates for dashboard/config/locations/browse/archived"
```

---

### Task 5: Nav integration in `templates/base.html` (DATA IMPORT section)

**Files:**
- Modify: `templates/base.html` (5 exact edits: nav var + desktop gate/dropdown + mobile gate/menu)
- Test: `dicom_archive/tests/test_nav.py`

**Interfaces:**
- Consumes: url name `dicom_archive:dashboard` (Task 1) rendered as `nav_archive`; existing `nav_dropdown` / `nav_dropdown_item` / `nav_mobile_item` components (verified kwargs: `href, icon, label, section, active_on`); context `perms.dicom_archive.view_archiveconfiguration` (auth context processor already in base.html).
- Produces: a "DICOM Archive" item (icon `fa-box-archive`) inside the existing **DATA IMPORT** section in BOTH the desktop dropdown and the mobile menu; the section gate condition in both places extended with `or perms.dicom_archive.view_archiveconfiguration`; the desktop dropdown's `active_on` gains the `dicom_archive` namespace so the underline tracks archive pages.

- [ ] **Step 1: Write the failing test**

Create `dicom_archive/tests/test_nav.py`:

```python
"""Nav integration tests: DICOM Archive entry in DATA IMPORT (plan 03).

The desktop dropdown and mobile menu share templates/base.html, so one
authenticated GET through any base-extending page covers both renderings.
fa-box-archive appears ONLY in the new nav items (page headers use other
icons — design note 5), making it a unique marker.
"""
from django.test import TestCase
from django.urls import reverse

from dicom_archive.tests.test_views import ArchiveViewTestCase


class TestNavIntegration(ArchiveViewTestCase):
    def test_nav_shows_archive_for_user_with_config_view_perm(self):
        # admin has view_archiveconfiguration; dashboard renders base.html
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, 'fa-box-archive')
        self.assertContains(resp, 'DICOM Archive')

    def test_nav_hides_archive_without_config_view_perm(self):
        # viewer has only view_archivedstudy -> no nav entry
        self.client.force_login(self.viewer)
        resp = self.client.get(reverse('dicom_archive:browse'))
        self.assertContains(resp, 'Local Studies')
        self.assertNotContains(resp, 'fa-box-archive')

    def test_section_gate_opens_with_archive_perm_alone(self):
        # user with ONLY view_archiveconfiguration (no other section perms)
        # must still see the DATA IMPORT section via the extended gate.
        from django.contrib.auth.models import Permission, User
        user = User.objects.create_user('archive-only', password='pw')
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='dicom_archive',
            codename__in=['view_archiveconfiguration'],
        ))
        self.client.force_login(user)
        resp = self.client.get(reverse('dicom_archive:dashboard'))
        self.assertContains(resp, 'Data Import')
        self.assertContains(resp, 'fa-box-archive')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test dicom_archive.tests.test_nav -v 2`
Expected: FAIL — `AssertionError: ... 'fa-box-archive' not found` (no archive entry in base.html yet).

- [ ] **Step 3: Edit `templates/base.html` (5 exact edits)**

**Edit 1 — nav var** (inside the `{% url ... as nav_* %}` block near the top of the desktop nav, after the `nav_dicom_srv` line):

Before:

```html
                        {% url 'dicom_server:dashboard' as nav_dicom_srv %}
```

After:

```html
                        {% url 'dicom_server:dashboard' as nav_dicom_srv %}
                        {% url 'dicom_archive:dashboard' as nav_archive %}
```

**Edit 2 — desktop DATA IMPORT gate + dropdown (before)**:

```html
                        {% if perms.data_import.view_fileimportsession or perms.client_app.add_bulkdicomuploadsession or perms.client_app.view_bulkdicomuploadsession or perms.dicom_server.view_remotedicomnode %}
                        {% component "nav_dropdown" icon="fa-file-import" label="Data Import" active_on="data_import,dicom_server,bulk_dicom" %}
```

**After**:

```html
                        {% if perms.data_import.view_fileimportsession or perms.client_app.add_bulkdicomuploadsession or perms.client_app.view_bulkdicomuploadsession or perms.dicom_server.view_remotedicomnode or perms.dicom_archive.view_archiveconfiguration %}
                        {% component "nav_dropdown" icon="fa-file-import" label="Data Import" active_on="data_import,dicom_server,dicom_archive,bulk_dicom" %}
```

**Edit 3 — desktop dropdown items (before)**:

```html
                            {% if perms.dicom_server.view_remotedicomnode %}
                            {% component "nav_dropdown_item" href=nav_dicom_srv icon="fa-network-wired" label="DICOM Server" %}{% endcomponent %}
                            {% endif %}
                            {% endfill %}
```

**After**:

```html
                            {% if perms.dicom_server.view_remotedicomnode %}
                            {% component "nav_dropdown_item" href=nav_dicom_srv icon="fa-network-wired" label="DICOM Server" %}{% endcomponent %}
                            {% endif %}
                            {% if perms.dicom_archive.view_archiveconfiguration %}
                            {% component "nav_dropdown_item" href=nav_archive icon="fa-box-archive" label="DICOM Archive" %}{% endcomponent %}
                            {% endif %}
                            {% endfill %}
```

**Edit 4 — mobile DATA IMPORT gate (before)**:

```html
                {% if perms.data_import.view_fileimportsession or perms.client_app.add_bulkdicomuploadsession or perms.client_app.view_bulkdicomuploadsession or perms.dicom_server.view_remotedicomnode %}
                {% component "nav_mobile_item" section="DATA IMPORT" %}{% endcomponent %}
```

**After**:

```html
                {% if perms.data_import.view_fileimportsession or perms.client_app.add_bulkdicomuploadsession or perms.client_app.view_bulkdicomuploadsession or perms.dicom_server.view_remotedicomnode or perms.dicom_archive.view_archiveconfiguration %}
                {% component "nav_mobile_item" section="DATA IMPORT" %}{% endcomponent %}
```

**Edit 5 — mobile DATA IMPORT items (before)**:

```html
                {% if perms.dicom_server.view_remotedicomnode %}
                {% component "nav_mobile_item" href=nav_dicom_srv icon="fa-network-wired" label="DICOM Server" %}{% endcomponent %}
                {% endif %}
```

**After**:

```html
                {% if perms.dicom_server.view_remotedicomnode %}
                {% component "nav_mobile_item" href=nav_dicom_srv icon="fa-network-wired" label="DICOM Server" %}{% endcomponent %}
                {% endif %}
                {% if perms.dicom_archive.view_archiveconfiguration %}
                {% component "nav_mobile_item" href=nav_archive icon="fa-box-archive" label="DICOM Archive" %}{% endcomponent %}
                {% endif %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test dicom_archive.tests -v 2`
Expected: PASS — full suite (44 tests total: 41 from Tasks 1–4 + 3 nav tests).

- [ ] **Step 5: Commit** — executes ONLY after explicit user approval

```bash
git add templates/base.html dicom_archive/tests/test_nav.py
git commit -m "feat(dicom-archive): DICOM Archive entry in DATA IMPORT nav (desktop + mobile)"
```

---

### Task 6: Permission-grant documentation + smoke-test checklist

**Files:**
- Create: `dicom_archive/PERMISSIONS.md`

**Interfaces:**
- Consumes: the perm/view mapping implemented in Tasks 1–5 (contract URL table); `client_app:taskrun_list` at `/tasks/`; root include prefix `/dicom-archive/` (Task 1).
- Produces: operator-facing documentation: which Django model permission gates which view, recommended role bundles, exact grant commands for a staff user, and a superuser smoke-test checklist with exact URLs.

- [ ] **Step 1: Write `dicom_archive/PERMISSIONS.md`**

```markdown
# DICOM Archive — Permissions & Roles

All names below are plain Django model permissions, auto-created by the
`dicom_archive` app migration. No custom permissions, no RBAC changes.
`is_staff` alone does **not** grant any of them (verified by
`dicom_archive/tests/test_views.py`).

## Which permission gates which view

| View | url name | URL | Required permission |
|---|---|---|---|
| `ArchiveDashboardView` | `dicom_archive:dashboard` | `/dicom-archive/` | `dicom_archive.view_archiveconfiguration` |
| `ArchiveConfigUpdateView` | `dicom_archive:config_edit` | `/dicom-archive/config/` | `dicom_archive.change_archiveconfiguration` |
| `ArchiveLocationListView` | `dicom_archive:location_list` | `/dicom-archive/locations/` | `dicom_archive.view_archivelocation` |
| `ArchiveLocationCreateView` | `dicom_archive:location_create` | `/dicom-archive/locations/add/` | `dicom_archive.add_archivelocation` |
| `ArchiveLocationUpdateView` | `dicom_archive:location_update` | `/dicom-archive/locations/<pk>/edit/` | `dicom_archive.change_archivelocation` |
| `ArchiveLocationDeleteView` | `dicom_archive:location_delete` | `/dicom-archive/locations/<pk>/delete/` (POST) | `dicom_archive.delete_archivelocation` |
| `LocalStudyBrowserView` | `dicom_archive:browse` | `/dicom-archive/browse/` | `dicom_archive.view_archivedstudy` |
| `ArchivedStudyListView` | `dicom_archive:archived_list` | `/dicom-archive/archived/` | `dicom_archive.view_archivedstudy` |
| `ManualArchiveView` | `dicom_archive:archive_trigger` | `/dicom-archive/archive/` (POST JSON) | `dicom_archive.add_archivedstudy` |
| `ManualDearchiveView` | `dicom_archive:dearchive_trigger` | `/dicom-archive/dearchive/` (POST JSON) | `dicom_archive.add_archivedstudy` |
| `TaskStatusView` | `dicom_archive:task_status` | `/dicom-archive/task-status/<id>/` (GET JSON) | `dicom_archive.view_archivedstudy` |

Nav visibility (DATA IMPORT section, desktop dropdown + mobile menu in
`templates/base.html`): the section gate includes
`perms.dicom_archive.view_archiveconfiguration`, and the "DICOM Archive"
item itself is rendered only with that permission. Trigger buttons on the
browse/archived pages additionally require `dicom_archive.add_archivedstudy`;
location edit/delete icons require the matching location permissions.

## Recommended role bundles

- **Archive administrator** — all `dicom_archive` permissions (everything
  above, including `change_archiveconfiguration` and `change_archivedstudy`
  if granted).
- **Archive operator** — `view_archivedstudy`, `add_archivedstudy`,
  `view_archivelocation`: can browse, trigger manual archive/de-archive,
  watch task runs; cannot change config or manage locations.
- **Archive viewer** — `view_archivedstudy`, `view_archiveconfiguration`:
  dashboard and lists only; trigger buttons are hidden.

## Granting to a staff user

Admin UI: *Users → (user) → user permissions* → check the boxes under
**Dicom Archive** (view/change/add/delete on Archive Configuration, Archive
Location, Archived Study) → Save.

Shell (archive administrator):

    python manage.py shell -c "
    from django.contrib.auth.models import Permission, User
    user = User.objects.get(username='jdoe')
    user.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='dicom_archive'))
    "

Shell (archive operator):

    python manage.py shell -c "
    from django.contrib.auth.models import Permission, User
    user = User.objects.get(username='jdoe')
    user.user_permissions.add(*Permission.objects.filter(
        content_type__app_label='dicom_archive',
        codename__in=['view_archivedstudy', 'add_archivedstudy',
                      'view_archivelocation']))
    "

## Smoke-test checklist (superuser, or after granting all permissions)

| # | URL | Expected |
|---|---|---|
| 1 | `/accounts/login/` (log in) | lands back on the app |
| 2 | `/dicom-archive/` | dashboard: Archive Configuration card (Enabled/Disabled badge, "90 days", Move/Copy, cron, batch limit), Default Archive Location card, 4 stat tiles, recent-archived table |
| 3 | `/dicom-archive/config/` | form with enabled / archive-after-days / cron fields / batch limit; save → "DICOM archive configuration saved." flash, redirect to dashboard |
| 4 | `/dicom-archive/locations/` | empty state (or existing rows with type/path/default/active/archived-count columns) |
| 5 | `/dicom-archive/locations/add/` | create a LOCAL location with a writable path → success flash, row appears with Active=Yes |
| 6 | `/dicom-archive/locations/<pk>/edit/` | change path → save → list shows the new path |
| 7 | `/dicom-archive/browse/` | studies with a local folder; per-row checkbox (disabled when ARCHIVED); "Archive Selected" enables on selection; `?q=` search filters |
| 8 | click **Archive Selected** | status box shows the dispatch message and polls; the study folder ends up in the location (moved or copied per config); row badge → **Archived** (refresh) |
| 9 | `/dicom-archive/archived/` | row for the study with location/size/instances; filter by `?status=ARCHIVED` and by location; checkbox only on ARCHIVED rows |
| 10 | click **De-archive Selected** | folder restored to its original local path; badge → **De-archived** |
| 11 | `/tasks/` (`client_app:taskrun_list`) | two runs: task type "DICOM Archive" and "DICOM De-archive", status Success |
| 12 | delete an empty location via its trash icon | confirm dialog → row gone, "deleted" flash; deleting a location that still holds records → error flash, row remains |
| 13 | nav (desktop + mobile) | "DICOM Archive" entry visible under **Data Import** only for users holding `view_archiveconfiguration` |
```

- [ ] **Step 2: Verify the doc matches the code**

Run: `python manage.py test dicom_archive.tests -v 2`
Expected: PASS (documentation task — the suite must still pass untouched: 44 tests).
Cross-check the table above line-by-line against the `permission_required`
strings in `dicom_archive/views.py` and the `name=` values in
`dicom_archive/urls.py` (no drift).

- [ ] **Step 3: Commit** — executes ONLY after explicit user approval

```bash
git add dicom_archive/PERMISSIONS.md
git commit -m "docs(dicom-archive): permission grant guide + smoke-test checklist"
```

---

### Task 7: Docker deployment documentation (how archive paths are specified in containers)

**Files:**
- Create: `docs/dicom_archive_docker_deployment.md`

**Interfaces:**
- Consumes: plan-01 `ArchiveLocation` (`storage_type` LOCAL/MOUNT, `path`),
  `prepare_location` (write-probe in the web container),
  `docker_install/example_docker-compose.yml` (volume layout),
  `chavi_client/settings.py` (`BASE_DIR=/app` in the container, `MEDIA_ROOT=/app/media`).
- Produces: `docs/dicom_archive_docker_deployment.md` — the operator-facing
  reference for specifying archive paths under Docker.

Context: containers run with `BASE_DIR=/app`; compose bind-mounts `./media`
(from the compose project dir on the Docker host) to `/app/media` in every
app container, so `DICOMStudy.folder_path` is
`/app/media/processed_dicom/<patient_id>/<study_uid>` inside the container.
`ArchiveLocation.path` is therefore always a **container-internal** path.

- [ ] **Step 1: Write the failing check — the doc does not exist**

Run: `test ! -f docs/dicom_archive_docker_deployment.md && echo MISSING`
Expected: `MISSING`

- [ ] **Step 2: Create `docs/dicom_archive_docker_deployment.md` with exactly this content**

```markdown
# DICOM Archive — Docker deployment

CHAVI Client containers run with `BASE_DIR=/app` and `MEDIA_ROOT=/app/media`.
In `docker_install/example_docker-compose.yml`, `./media` (relative to the
compose project directory on the Docker host) is bind-mounted to
`/app/media` in every app container, so a study's `folder_path` is

    /app/media/processed_dicom/<patient_id>/<study_uid>

inside the container and `<compose-dir>/media/processed_dicom/...` on the
host. **`ArchiveLocation.path` is always a path inside the container.**

## Scenario 1 — another folder inside the app's media volume

No compose change. Create a location with a relative path:

    name: media-archive, storage_type: LOCAL, path: dicom_archive

→ resolves to `/app/media/dicom_archive` (host: `<compose-dir>/media/dicom_archive`).
Caveat: same physical disk as the source data.

## Scenario 2 — NAS/LAN drive mounted on the Docker host

Mount the share on the host first (NFS or SMB, e.g. `/mnt/nas/chavi-archive`),
then add the bind mount to the `volumes:` of BOTH `chaviclient-celery-worker`
and `chaviclient-django`:

    volumes:
      - chaviclient_app_data:/app
      - ./media:/app/media
      - /mnt/nas/chavi-archive:/archive/dicom

Create the location with: `name: nas-archive, storage_type: MOUNT,
path: /archive/dicom`.

## Scenario 3 — Windows host with an SMB share (Docker Desktop)

Bind the UNC path directly (no host-side mount needed), again in BOTH
`chaviclient-celery-worker` and `chaviclient-django`:

    volumes:
      - //NAS_HOST/chavi-archive:/archive/dicom

Create the location with: `name: nas-archive, storage_type: MOUNT,
path: /archive/dicom`.

## Why the django container needs the mount too

`ArchiveLocationForm.clean()` calls `prepare_location()`, which creates the
directory and probes it for write permission — that runs in the web
container (`chaviclient-django`) when the location form is submitted. If the
path is only mounted in the worker, location creation fails validation with
"location path is not writable".

`chaviclient-celery-beat` only dispatches `task_scheduled_archive` (no file
I/O) and `chaviclient-dicom` (SCP ingest) never touches the archive path —
neither needs the mount.

## Verification

1. `docker compose exec chaviclient-celery-worker ls /archive/dicom` lists the share.
2. In the UI, create the MOUNT location — the form validates without error.
3. Archive one study manually; `docker compose exec chaviclient-celery-worker find /archive/dicom -name '*.dcm' | head` shows the files, and the study's local folder under `/app/media/processed_dicom` is gone when `delete_local_after_archive` is on.
4. De-archive the study; files return under the original `folder_path`.
```

- [ ] **Step 3: Verify the doc exists and its commands match the compose file**

Run: `test -f docs/dicom_archive_docker_deployment.md && grep -c "chaviclient-celery-worker\|chaviclient-django" docs/dicom_archive_docker_deployment.md`
Expected: a count ≥ 6 (both container names appear in the scenario and
explanation sections), and `docker_install/example_docker-compose.yml` was
NOT modified.

- [ ] **Step 4: Commit (ONLY after explicit user approval — see Global Constraints)**

```bash
git add docs/dicom_archive_docker_deployment.md
git commit -m "docs(dicom-archive): docker deployment guide for archive location paths"
```

---

## Self-Review

**1. Spec coverage** (overview contract, "Frontend (plan 03)" section):

- URL table — all 11 routes present with exact paths, view class names, `permission_required`, url names, `app_name='dicom_archive'`: `''`/dashboard (T1), `config/` (T2), `locations/`, `locations/add/`, `locations/<int:pk>/edit/`, `locations/<int:pk>/delete/` (T2), `browse/`, `archived/` (T1), `archive/`, `dearchive/`, `task-status/<task_run_id>/` (T3). Task 3's final URLConf shows the complete table.
- `ArchivePermissionRequiredMixin(LoginRequiredMixin, PermissionRequiredMixin)` mirroring `dicom_server.views.DicomPermissionRequiredMixin` — Task 1 (identical `handle_no_permission`).
- `ArchiveDashboardView` (config status, default location, counts, recent archived) — Task 1 + dashboard template Task 4.
- `LocalStudyBrowserView` (local `DICOMStudy` with `folder_path`, archive status via `archive_record`, pagination, checkbox selection) — Task 1 + browse template Task 4.
- `ArchivedStudyListView` filterable by status/location — Task 1 + archived_list template Task 4.
- Config + location CRUD with forms whose `clean()` calls `services.locations.prepare_location`; `DICOMServerConfiguration`/`RemoteDICOMNode` field patterns used as reference (singleton `get_object`, model-perm gating, form classes) — Task 2.
- Manual triggers: `ManualArchiveView` POST JSON `{study_uids, location_id}` → `archive_studies_task.delay` → `{task_id, redirect_url: reverse('client_app:taskrun_list'), message}`; `ManualDearchiveView` POST `{study_uids}` → `dearchive_studies_task.delay`, same shape; `TaskStatusView` GET JSON over `client_app.TaskRun` — Task 3 (BulkDeidentifyView response shape, mirrored per contract).
- Templates `templates/dicom_archive/{dashboard,config_edit,location_form,location_list,archived_list,browse}.html`, extend `base.html`, use `{% component %}` with names/attrs verified against `components/ui.py` — Task 4; trigger JS fetch + polling pattern taken from `batch_select.html`/`task_progress.html` — Task 4 (design note 8).
- Nav: `{% url 'dicom_archive:dashboard' as nav_archive %}` + "DICOM Archive" entries in BOTH desktop dropdown and mobile menu inside DATA IMPORT, section gate extended with `perms.dicom_archive.view_archiveconfiguration`, exact before/after snippets for both places — Task 5.
- Permission-grant documentation (which model perms gate which view; how to grant to a staff user) + smoke-test checklist with exact superuser URLs — Task 6.
- Docker deployment doc `docs/dicom_archive_docker_deployment.md` (container-internal path semantics, relative→`/app/media`, host-NAS and UNC bind-mount scenarios for `chaviclient-celery-worker` + `chaviclient-django`, validation-in-web-container caveat, verification steps) — Task 7.

No contract gaps found. No requirement contradicts the overview: names, signatures, response shape, app_name all copied verbatim.

**2. Placeholder scan:** no "TBD"/"TODO"/"implement later"; no "add appropriate error handling" (every error path has its exact status code + JSON body); no "similar to Task N" (JS and templates are repeated in full in each step); every code step contains the code; every referenced type/function (`prepare_location`, `archive_studies_task.delay`, `dearchive_studies_task.delay`, `ArchiveConfiguration.load`, `TaskRun.progress_percent`, `reverse('client_app:taskrun_list')`) is defined by plan 01 / `client_app` and quoted in the consuming task's Interfaces block.

**3. Type/name consistency:** `ArchiveViewTestCase` (Task 1) is imported verbatim by `test_templates.py` (Task 4) and `test_nav.py` (Task 5); `status_choices`/`locations`/`query_string` context keys set in Task 1 views match template usage in Task 4; `study_count` annotation (Task 2) is the only extra location-list key used in the location template; trigger response keys `task_id`/`redirect_url`/`message` (Task 3) are exactly what the Task 4 JS reads (`res.body.task_id`, `res.body.redirect_url`, `res.body.message`); task-status JSON keys (Task 3) match JS field access (`body.status`, `body.progress_total`, `body.progress_percent`, `body.error_log`, `body.progress_description`); url names referenced in templates (`archive_trigger`, `dearchive_trigger`, `task_status`, `location_*`, `config_edit`) all exist in the final URLConf shown in Task 3; `fa-box-archive` is the nav-only icon asserted by Task 5 and is deliberately absent from the page templates (page headers use `fa-warehouse`/`fa-folder-open`/`fa-server`/`fa-database`; the dashboard "Archived" stat tile uses `fa-inbox`).

Known environment caveats (recorded, not fixed): `test_archive_trigger_rejects_*` and the location-form writability tests rely on plan-01 `prepare_location` raising `ValidationError` (contract-guaranteed) and on a Unix-style test host where `/nonexistent-no-permission/...` cannot be created.
