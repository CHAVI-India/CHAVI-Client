"""Fix DICOMStudy.folder_path values that point to the wrong directory.

Every import path (bulk upload, per-patient import, unprocessed re-processing,
DICOM C-STORE ingest) stores files under:

    {MEDIA_ROOT}/processed_dicom/{sanitize(patient_id)}/{sanitize(study_instance_uid)}

where sanitize() replaces the characters / \\ : * ? " < > | with '_'.
Patient.patient_id is the primary key, so the patient FK on DICOMStudy
carries the exact value used to build the path.

A bug in the per-patient import services stored the *last* study's directory
for every study found in a multi-study archive, so some rows have a
folder_path that does not belong to them.

This data migration recomputes the expected path from the patient FK and the
study instance UID for every study:
  - if that directory exists on disk, folder_path is corrected to it;
  - if it does not exist, the study and its child rows (series, instances)
    are deleted, because there is no on-disk data left to reference.
"""
import logging
import re
from pathlib import Path

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)

_SANITIZE_RE = re.compile(r'[/\\:*?"<>|]')


def _sanitize(value):
    return _SANITIZE_RE.sub('_', str(value))


def _expected_folder_path(patient_id, study_instance_uid):
    return (
        Path(settings.MEDIA_ROOT)
        / 'processed_dicom'
        / _sanitize(patient_id)
        / _sanitize(study_instance_uid)
    )


def fix_dicomstudy_folder_paths(apps, schema_editor):
    DICOMStudy = apps.get_model('client_app', 'DICOMStudy')
    DICOMSeries = apps.get_model('client_app', 'DICOMSeries')
    DICOMInstance = apps.get_model('client_app', 'DICOMInstance')

    fixed = 0
    deleted_studies = 0
    deleted_series = 0
    deleted_instances = 0

    for study in DICOMStudy.objects.iterator(chunk_size=500):
        expected = _expected_folder_path(study.patient_id, study.study_instance_uid)
        if expected.is_dir():
            if study.folder_path != str(expected):
                (DICOMStudy.objects
                 .filter(study_instance_uid=study.study_instance_uid)
                 .update(folder_path=str(expected)))
                fixed += 1
        else:
            # No data on disk for this study: remove it and its children.
            n_instances, _ = (
                DICOMInstance.objects.filter(series__study=study).delete()
            )
            deleted_instances += n_instances
            n_series, _ = DICOMSeries.objects.filter(study=study).delete()
            deleted_series += n_series
            study.delete()
            deleted_studies += 1

    if fixed or deleted_studies:
        logger.info(
            'folder_path migration: fixed %d, deleted %d studies / '
            '%d series / %d instances',
            fixed, deleted_studies, deleted_series, deleted_instances,
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('client_app', '0033_alter_adverseeffects_adverse_effect_end_date_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_dicomstudy_folder_paths, noop),
    ]
