"""Tests for migration 0034_fix_dicomstudy_folder_paths.

Seeds dummy DICOMStudy/DICOMSeries/DICOMInstance rows (reproducing the
real on-disk layout {MEDIA_ROOT}/processed_dicom/{sanitize(patient_id)}/
{sanitize(study_uid)}) in the test database and a temp MEDIA_ROOT, runs the
migration function, and verifies:

  * a study whose stored folder_path points at the wrong (stale) directory
    is corrected when its correct directory exists on disk;
  * a study already pointing at the correct directory is left alone;
  * a study whose correct directory does not exist on disk is deleted
    together with its series and instances;
  * paths are built with the same sanitize() rule as the import services
    (special characters in patient IDs).
"""
import importlib
import re
import tempfile
from pathlib import Path

from django.apps import apps
from django.test import TestCase, override_settings

from client_app.models import (
    DICOMInstance,
    DICOMSeries,
    DICOMStudy,
    Patient,
    SiteConfiguration,
)

migration = importlib.import_module(
    'client_app.migrations.0034_fix_dicomstudy_folder_paths'
)

_SANITIZE_RE = re.compile(r'[/\\:*?"<>|]')


def sanitize(value):
    return _SANITIZE_RE.sub('_', str(value))


class FolderPathMigrationTests(TestCase):

    def setUp(self):
        self.media_root = Path(tempfile.mkdtemp(prefix='chavi_media_'))
        self.addCleanup(self._rmtree, self.media_root)
        self.site = SiteConfiguration.objects.create(
            chavi_center_id='TEST01', center_name='Test Site'
        )

        # Patient with special characters -> exercises the sanitize rule.
        self.patient = Patient.objects.create(
            patient_id='MR/25:004771', center=self.site
        )
        # Second patient for the delete case.
        self.patient2 = Patient.objects.create(
            patient_id='P/9', center=self.site
        )

        p = sanitize(self.patient.patient_id)
        self.study_uids = ['1.2.3.4.5.6.1', '1.2.3.4.5.6.2', '1.2.3.4.5.6.3']

        # On-disk layout: only studies 1 and 2 exist on disk for patient 1.
        for uid in self.study_uids[:2]:
            (self.media_root / 'processed_dicom' / p / sanitize(uid)).mkdir(parents=True)

    def _rmtree(self, path):
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    def _expected(self, patient, uid):
        return (
            self.media_root / 'processed_dicom'
            / sanitize(patient.patient_id) / sanitize(uid)
        )

    def _make_study(self, patient, uid, folder_path):
        return DICOMStudy.objects.create(
            patient=patient,
            study_instance_uid=uid,
            folder_path=folder_path,
        )

    def _add_series_instances(self, study, n_series=1, n_instances=2):
        series_list = []
        for i in range(n_series):
            s = DICOMSeries.objects.create(
                study=study,
                series_instance_uid=f'10.{study.study_instance_uid}.{i}',
                modality='CT',
            )
            series_list.append(s)
            for j in range(n_instances):
                DICOMInstance.objects.create(
                    series=s, sop_instance_uid=f'100.{s.series_instance_uid}.{j}'
                )
        return series_list

    # ------------------------------------------------------------------

    def test_stale_folder_path_corrected_when_dir_exists(self):
        """Multi-study zip bug: every study stored the LAST study's dir.
        Study 1's correct dir exists on disk -> path corrected."""
        uid1, uid2 = self.study_uids[0], self.study_uids[1]
        stale = str(self._expected(self.patient, uid2))  # what the buggy import stored

        study1 = self._make_study(self.patient, uid1, folder_path=stale)
        self._add_series_instances(study1, n_series=2, n_instances=3)
        study2 = self._make_study(self.patient, uid2, folder_path=stale)

        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.fix_dicomstudy_folder_paths(apps, None)

        study1.refresh_from_db()
        self.assertEqual(study1.folder_path, str(self._expected(self.patient, uid1)))
        # Correct rows untouched.
        self.assertEqual(study2.folder_path, str(self._expected(self.patient, uid2)))
        # Children of the corrected study survive.
        self.assertEqual(DICOMSeries.objects.filter(study=study1).count(), 2)
        self.assertEqual(DICOMInstance.objects.filter(series__study=study1).count(), 6)

    def test_study_without_dir_on_disk_deleted_with_children(self):
        """No directory on disk for the study -> study + series + instances
        deleted."""
        uid = self.study_uids[2]
        study = self._make_study(
            self.patient, uid, folder_path=str(self._expected(self.patient, uid)),
        )
        series = self._add_series_instances(study, n_series=1, n_instances=2)
        study2 = self._make_study(
            self.patient2, '1.2.3.4.5.6.9',
            folder_path='/nonexistent/somewhere',
        )
        series2 = self._add_series_instances(study2, n_series=1, n_instances=1)

        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.fix_dicomstudy_folder_paths(apps, None)

        self.assertFalse(DICOMStudy.objects.filter(pk=uid).exists())
        self.assertFalse(DICOMSeries.objects.filter(pk__in=[s.pk for s in series]).exists())
        self.assertFalse(DICOMInstance.objects.filter(series__study=study).exists())
        # study2 also has no on-disk dir -> deleted too.
        self.assertFalse(DICOMStudy.objects.filter(pk='1.2.3.4.5.6.9').exists())
        self.assertFalse(DICOMSeries.objects.filter(pk__in=[s.pk for s in series2]).exists())
        # Valid row of another patient, dir exists: create + verify untouched.
        p2dir = self.media_root / 'processed_dicom' / sanitize(self.patient2.patient_id) / '1.2.3.4.5.6.8'
        p2dir.mkdir(parents=True)
        self._make_study(self.patient2, '1.2.3.4.5.6.8', folder_path=str(p2dir))
        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.fix_dicomstudy_folder_paths(apps, None)
        ok = DICOMStudy.objects.get(pk='1.2.3.4.5.6.8')
        self.assertEqual(ok.folder_path, str(p2dir))

    def test_sanitized_special_character_patient_id(self):
        """Patient 'MR/25:004771' -> dir 'MR_25_004771'; a path built from
        the UNSANITIZED id is wrong but must be corrected."""
        uid = self.study_uids[0]
        wrong = str(self.media_root / 'processed_dicom' / 'MR/25:004771' / sanitize(uid))
        study = self._make_study(self.patient, uid, folder_path=wrong)

        with override_settings(MEDIA_ROOT=str(self.media_root)):
            migration.fix_dicomstudy_folder_paths(apps, None)

        study.refresh_from_db()
        self.assertEqual(
            study.folder_path,
            str(self.media_root / 'processed_dicom' / 'MR_25_004771' / sanitize(uid)),
        )
