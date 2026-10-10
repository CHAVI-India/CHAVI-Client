"""Wire the DICOM archive permissions into the existing
``DICOM Administrator`` role group (created by 0029_rbac_roles).

Archival / de-archival management — archive configuration, locations,
manual archive triggers and the archived-study list — is part of DICOM
data administration, so instead of introducing a new group the archive
model permissions are added to the existing role.

The change is *additive*: permissions an administrator later customised on
the group in the admin are kept. ``dicom_archive``'s Permission rows are
normally created by the post_migrate signal *after* all migrations run, so
they are created manually here first (idempotent — no-op when they exist).
"""
from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUP = 'DICOM Administrator'

# The exact permission set the archive frontend gates on (see
# dicom_archive/views.py). delete/change on archivedstudy are admin-only
# and not used by any frontend view, so they are intentionally excluded.
ARCHIVE_PERMISSIONS = [
    'dicom_archive.view_archiveconfiguration',
    'dicom_archive.change_archiveconfiguration',
    'dicom_archive.view_archivelocation',
    'dicom_archive.add_archivelocation',
    'dicom_archive.change_archivelocation',
    'dicom_archive.delete_archivelocation',
    'dicom_archive.view_archivedstudy',
    'dicom_archive.add_archivedstudy',
]


def _archive_perm_codenames():
    return [p.split('.', 1)[1] for p in ARCHIVE_PERMISSIONS]


def add_archive_perms_to_dicom_admin(apps, schema_editor):
    db_alias = schema_editor.connection.alias

    app_config = apps.get_app_config('dicom_archive')
    app_config.models_module = True
    create_permissions(
        app_config, verbosity=0, interactive=False,
        using=db_alias, apps=apps,
    )
    app_config.models_module = None

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    group, _ = Group.objects.using(db_alias).get_or_create(name=GROUP)

    perms = list(Permission.objects.using(db_alias).filter(
        content_type__app_label='dicom_archive',
        codename__in=_archive_perm_codenames(),
    ))
    missing = set(_archive_perm_codenames()) - {p.codename for p in perms}
    if missing:
        raise RuntimeError(
            f'Cannot extend {GROUP!r} with archive permissions: unknown '
            f'{sorted(missing)}'
        )
    group.permissions.add(*perms)


def remove_archive_perms_from_dicom_admin(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    group = Group.objects.using(db_alias).filter(name=GROUP).first()
    if group is None:
        return
    perms = list(Permission.objects.using(db_alias).filter(
        content_type__app_label='dicom_archive',
        codename__in=_archive_perm_codenames(),
    ))
    group.permissions.remove(*perms)


class Migration(migrations.Migration):

    dependencies = [
        ('client_app', '0030_alter_taskrun_task_type'),
        ('dicom_archive', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            add_archive_perms_to_dicom_admin,
            remove_archive_perms_from_dicom_admin,
        ),
    ]
