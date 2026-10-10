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
