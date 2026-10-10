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
| `LocationTestView` | `dicom_archive:location_test` | `/dicom-archive/locations/test/` (POST JSON `{location_id}` or `{storage_type, path}`) | `dicom_archive.view_archivelocation` |
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

## Roles and granting

The full archive permission set above is shipped as part of the
**DICOM Administrator** role group — migration
``client_app/0031_dicom_administrator_archive_permissions.py`` adds these
permissions to that existing group (no separate archive group). Assign the
role under *Users → (user) → groups*, or from the shell:

    python manage.py shell -c "
    from django.contrib.auth.models import Group, User
    user = User.objects.get(username='jdoe')
    user.groups.add(Group.objects.get(name='DICOM Administrator'))
    "

Partial access (e.g. may archive but not reconfigure) is granted with
individual model permissions under *Users → (user) → user permissions*:

- **Archive operator** — `view_archivedstudy`, `add_archivedstudy`,
  `view_archivelocation`: can browse, trigger manual archive/de-archive,
  watch task runs; cannot change config or manage locations.
- **Archive viewer** — `view_archivedstudy`, `view_archiveconfiguration`:
  dashboard and lists only; trigger buttons are hidden.

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
| 8 | click **Archive Selected** | status box shows the dispatch message and polls; the study folder ends up in the location (moved or copied per config); row badge → **Archived** (refresh); empty per-patient folders are cleaned up in `processed_dicom` and in the archive location after de-archive |
| 9 | `/dicom-archive/archived/` | row for the study with location/size/instances; filter by `?status=ARCHIVED` and by location; checkbox only on ARCHIVED rows |
| 10 | click **De-archive Selected** | folder restored to its original local path; badge → **De-archived** |
| 11 | `/tasks/` (`client_app:taskrun_list`) | two runs: task type "DICOM Archive" and "DICOM De-archive", status Success |
| 12 | delete an empty location via its trash icon | confirm dialog → row gone, "deleted" flash; deleting a location that still holds records → error flash, row remains |
| 13 | nav (desktop + mobile) | "DICOM Archive" entry visible under **Data Import** only for users holding `view_archiveconfiguration` |
