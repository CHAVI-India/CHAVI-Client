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
    WRITE_TEST_FILENAME,
    candidate_studies,
    prepare_location,
    resolve_location_path,
    study_age_days,
    test_location,
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


class TestLocationProbe(TestCase):
    """test_location(): reachable / writable / visible write test that
    leaves a persistent verification file the user can open on the share."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='dicom_archive_probe_'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_probe_creates_directory_and_leaves_test_file(self):
        base = self.tmp / 'probe'
        result = test_location(ArchiveLocation(
            name='ok', storage_type='LOCAL', path=str(base)))
        self.assertTrue(result['ok'])
        self.assertTrue(result['created'])
        self.assertEqual(
            [c['name'] for c in result['checks']],
            ['Reachable', 'Writable', 'Write test'])
        self.assertTrue(all(c['ok'] for c in result['checks']))
        test_file = base / WRITE_TEST_FILENAME
        self.assertTrue(test_file.is_file(),
                        'the verification file must persist after the probe')
        self.assertEqual(result['test_file'], str(test_file))
        content = test_file.read_text(encoding='utf-8')
        self.assertIn('token:', content)
        self.assertIn('written by:', content)
        self.assertIn(str(base), content)
        self.assertGreaterEqual(result['elapsed_ms'], 0)
        self.assertIsNone(result['error'])

    def test_probe_on_existing_directory_reports_not_created(self):
        base = self.tmp / 'existing'
        base.mkdir()
        result = test_location(ArchiveLocation(
            name='ok', storage_type='LOCAL', path=str(base)))
        self.assertTrue(result['ok'])
        self.assertFalse(result['created'])

    def test_probe_fails_when_parent_is_a_file(self):
        blocker = self.tmp / 'blocker'
        blocker.write_text('i am a file, not a directory')
        result = test_location(ArchiveLocation(
            name='bad', storage_type='LOCAL',
            path=str(blocker / 'sub')))
        self.assertFalse(result['ok'])
        self.assertIsNone(result['test_file'])
        self.assertFalse((blocker / 'sub').exists())
        self.assertIn('Cannot create', result['checks'][0]['detail'])

    def test_probe_rejects_empty_path(self):
        result = test_location(ArchiveLocation(
            name='bad', storage_type='LOCAL', path=''))
        self.assertFalse(result['ok'])
        self.assertFalse(result['checks'][0]['ok'])
        self.assertIsNone(result['test_file'])

    def test_probe_rejects_relative_mount_path(self):
        result = test_location(ArchiveLocation(
            name='bad', storage_type='MOUNT', path='relative/share'))
        self.assertFalse(result['ok'])
        self.assertIsNone(result['test_file'])
