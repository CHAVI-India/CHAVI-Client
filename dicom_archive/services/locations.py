"""Archive location path resolution and validation.

Storage backends are path-based only: LOCAL (any folder — absolute or
MEDIA_ROOT-relative) and MOUNT (mounted NAS/LAN share — must be absolute).
DICOMStudy.folder_path is always an absolute path; archive code never
re-joins MEDIA_ROOT when touching study folders.
"""
import os
import socket
import tempfile
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from client_app.models import DICOMStudy
from dicom_archive.models import ArchiveConfiguration, ArchivedStudy, ArchiveLocation

#: Small persistent file written by the location "Test" button so an
#: operator can verify (by eye, on the share) that writes reach it.
WRITE_TEST_FILENAME = 'chavi_archive_write_test.txt'


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


def test_location(location: ArchiveLocation) -> dict:
    """Live probe of an archive location: reachable, writable, and a real
    write that leaves a small persistent file (WRITE_TEST_FILENAME) so the
    user can verify on the share itself (open it in Windows Explorer, or
    ``ls`` it from the host).

    Side effect (documented): like prepare_location(), the directory is
    created when missing — the app does the same when the location is saved
    or an archive runs. Returns a JSON-safe dict::

        {ok, path, created, checks: [{name, ok, detail} x3],
         test_file, error, elapsed_ms}
    """
    start = time.monotonic()
    checks: list[dict] = []
    result = {'ok': True, 'path': None, 'created': False,
              'checks': checks, 'test_file': None, 'error': None,
              'elapsed_ms': 0}

    def finish():
        result['elapsed_ms'] = int((time.monotonic() - start) * 1000)
        result['ok'] = all(c['ok'] for c in checks)
        return result

    def add(name, ok, detail):
        checks.append({'name': name, 'ok': ok, 'detail': detail})
        if not ok and result['error'] is None:
            result['error'] = f'{name}: {detail}'
        return ok

    try:
        base = resolve_location_path(location)
    except ValidationError as exc:
        add('Reachable', False, exc.messages[0])
        return finish()
    result['path'] = str(base)

    existed = base.exists()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        add('Reachable', False, f'Cannot create {base}: {exc}')
        return finish()
    result['created'] = not existed
    if base.is_dir():
        add('Reachable', True,
            f'{base} is a directory'
            + (' (created by this test)' if result['created'] else ''))
    else:
        add('Reachable', False, f'{base} exists but is not a directory')
        return finish()

    if not os.access(base, os.W_OK):
        add('Writable', False, f'{base} is not writable by the current user')
        return finish()
    add('Writable', True, f'{base} is writable')

    test_file = base / WRITE_TEST_FILENAME
    token = f'{socket.gethostname()}/{os.getpid()}'
    token_line = f'token: {token}'
    stamp = datetime.now(dt_timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    content = (
        'CHAVI archive location write test\n'
        f'written at:    {stamp}\n'
        f'written by:    {socket.gethostname()} (pid {os.getpid()})\n'
        f'storage type:  {location.storage_type}\n'
        f'resolved path: {base}\n'
        f'{token_line}\n'
        '\nThis file was created by the archive location "Test" button.\n'
        'Seeing it on the share proves writes from the CHAVI app reach it.\n'
        'It is safe to delete.\n'
    )
    try:
        test_file.write_text(content, encoding='utf-8')
        if token_line not in test_file.read_text(encoding='utf-8'):
            raise OSError('read-back verification of the file failed')
    except (OSError, UnicodeError) as exc:
        add('Write test', False,
            f'Could not write/verify {WRITE_TEST_FILENAME}: {exc}')
        return finish()
    add('Write test', True,
        f'{WRITE_TEST_FILENAME} written and verified — open it on the '
        'share to confirm')
    result['test_file'] = str(test_file)
    return finish()


def study_age_days(study) -> int | None:
    """Days since the study was performed (study_date) or, when the study
    has no date, since it was created (created_at).

    Both dates are taken in the project's local time zone — created_at comes
    back from the database in UTC, so .date() on it raw would disagree with
    timezone.localdate() around the IST/UTC day boundary (off-by-one)."""
    reference = study.study_date or timezone.localtime(study.created_at).date()
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
