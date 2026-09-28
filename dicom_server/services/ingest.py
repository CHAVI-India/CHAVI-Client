import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import transaction
from pydicom.dataset import Dataset

from client_app.models import (
    Patient, DICOMStudy, DICOMSeries, DICOMInstance, _make_canonical_id,
)
from dicom_server.models import InboundDICOMInstance
from dicom_server.services.classifier import classify_study

logger = logging.getLogger(__name__)

_SANITIZE_RE = re.compile(r'[/\\:*?"<>|]')

# C-STORE status codes
STATUS_SUCCESS = 0x0000
STATUS_MISSING_ATTRIBUTE = 0xA900   # required attribute missing/invalid
STATUS_UNKNOWN_PATIENT = 0xA700     # policy rejection: patient not in database
STATUS_NO_CONSENT = 0xA7FD          # policy rejection: patient has not consented
STATUS_SERVER_DISABLED = 0xA7FE     # policy rejection: server is_enabled=False
STATUS_INTERNAL_ERROR = 0xC000      # cannot understand / internal failure


def sanitize(value) -> str:
    return _SANITIZE_RE.sub('_', str(value))


def find_patient(dicom_patient_id: str):
    """Resolve a DICOM PatientID to a client_app.Patient.

    Stage 1: exact match on patient_id.
    Stage 2: canonical normalised match (same rule as the bulk import services):
    canonical_db == canonical_dicom or canonical_db.endswith(canonical_dicom).
    """
    try:
        return Patient.objects.get(patient_id=dicom_patient_id)
    except Patient.DoesNotExist:
        pass
    canonical_dicom = _make_canonical_id(dicom_patient_id)
    if not canonical_dicom:
        return None
    # Indexed equality covers format variants of the same ID; the suffix rule
    # (site-prefixed IDs) runs as a single-column LIKE scan in the DB instead
    # of a Python loop hydrating every Patient row per instance.
    return (
        Patient.objects.filter(canonical_patient_id=canonical_dicom).first()
        or Patient.objects.filter(canonical_patient_id__endswith=canonical_dicom).first()
    )


@dataclass
class IngestResult:
    status: int                      # DICOM C-STORE status code
    reason: str = ''
    file_path: str | None = None
    patient: Patient | None = None


def ingest_dataset(ds: Dataset, *, calling_ae='', called_ae='', remote_addr='') -> IngestResult:
    """Validate, gate on known patient, write to processed_dicom/, upsert
    DICOMStudy, and audit-log the instance. Never raises.

    Callers running in pynetdicom association threads must call
    django.db.close_old_connections() before invoking this — it is done in
    scp/handlers.py at handler entry.
    """

    log_fields = dict(
        calling_ae_title=str(calling_ae or '')[:16],
        called_ae_title=str(called_ae or '')[:16],
        remote_addr=str(remote_addr or '')[:64],
        dicom_patient_id=str(getattr(ds, 'PatientID', '') or '')[:255],
        study_instance_uid=str(getattr(ds, 'StudyInstanceUID', '') or '')[:128],
        series_instance_uid=str(getattr(ds, 'SeriesInstanceUID', '') or '')[:128],
        sop_instance_uid=str(getattr(ds, 'SOPInstanceUID', '') or '')[:128],
        modality=str(getattr(ds, 'Modality', '') or '')[:16],
    )

    def reject(status, reason):
        logger.warning("Rejecting instance %s: %s", log_fields['sop_instance_uid'], reason)
        InboundDICOMInstance.objects.create(
            status=InboundDICOMInstance.Status.REJECTED,
            reject_reason=reason[:255], **log_fields,
        )
        return IngestResult(status=status, reason=reason)

    raw_patient_id = str(getattr(ds, 'PatientID', '') or '').strip()
    if not raw_patient_id:
        return reject(STATUS_MISSING_ATTRIBUTE, 'Missing PatientID')
    study_uid = str(getattr(ds, 'StudyInstanceUID', '') or '').strip()
    sop_uid = str(getattr(ds, 'SOPInstanceUID', '') or '').strip()
    if not study_uid or not sop_uid:
        return reject(STATUS_MISSING_ATTRIBUTE, 'Missing StudyInstanceUID or SOPInstanceUID')

    patient = find_patient(raw_patient_id)
    if patient is None:
        return reject(STATUS_UNKNOWN_PATIENT, f'Unknown PatientID {raw_patient_id}')
    if not patient.chavi_consent:
        return reject(STATUS_NO_CONSENT, f'Patient {raw_patient_id} has not consented')

    dest = None
    try:
        # Align with existing import services: stored files carry the
        # database PatientID (manual import also rewrites PatientName).
        ds.PatientID = patient.patient_id
        if 'PatientName' in ds:
            ds.PatientName = patient.patient_id
        study_dir = (
            Path(settings.MEDIA_ROOT) / 'processed_dicom'
            / sanitize(patient.patient_id) / sanitize(study_uid)
        )
        study_dir.mkdir(parents=True, exist_ok=True)
        dest = study_dir / f"{sanitize(sop_uid)}.dcm"
        ds.save_as(dest, enforce_file_format=True)

        with transaction.atomic():
            study = _upsert_study(patient, ds, study_dir)
            _upsert_series_instance(ds, study)
            InboundDICOMInstance.objects.create(
                status=InboundDICOMInstance.Status.STORED,
                matched_patient=patient, file_path=str(dest), **log_fields,
            )
        try:
            classify_study(DICOMStudy.objects.get(study_instance_uid=str(ds.StudyInstanceUID)))
        except Exception:
            logger.exception("Failed to classify study %s", study_uid)
        logger.info("Stored %s for patient %s (%s)", sop_uid, patient.patient_id, calling_ae)
        return IngestResult(status=STATUS_SUCCESS, file_path=str(dest), patient=patient)
    except Exception:
        logger.exception("Failed to ingest instance %s", sop_uid)
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)  # no orphan .dcm after a DB failure
            except OSError:
                logger.warning("Could not remove orphaned file %s", dest)
        InboundDICOMInstance.objects.create(
            status=InboundDICOMInstance.Status.REJECTED,
            reject_reason='Internal storage error', matched_patient=patient, **log_fields,
        )
        return IngestResult(status=STATUS_INTERNAL_ERROR, reason='Internal storage error')


def _upsert_study(patient: Patient, ds: Dataset, study_dir: Path) -> DICOMStudy:
    """Merge this instance's metadata into the DICOMStudy row (comma-joined sets)."""
    uid = str(ds.StudyInstanceUID)
    study = DICOMStudy.objects.filter(study_instance_uid=uid).first()
    if study is None:
        study = DICOMStudy.objects.create(patient=patient, study_instance_uid=uid)
    elif study.patient_id != patient.patient_id:
        # Same StudyInstanceUID stored under a different patient (ID alias or
        # canonical mismatch) — the patient matched from this dataset wins.
        logger.warning(
            'Study %s was stored under patient %s; reassigning to %s',
            uid, study.patient_id, patient.patient_id,
        )
        study.patient = patient

    def merge(field, new_value):
        if not new_value:
            return
        existing = set(filter(None, (getattr(study, field) or '').split(', ')))
        existing.add(str(new_value))
        setattr(study, field, ', '.join(sorted(existing)))

    merge('study_modalities', getattr(ds, 'Modality', None))
    merge('series_descriptions', getattr(ds, 'SeriesDescription', None))
    if getattr(ds, 'StudyDescription', None) and not study.study_description:
        study.study_description = str(ds.StudyDescription)
    if getattr(ds, 'StudyDate', None) and not study.study_date:
        try:
            study.study_date = datetime.strptime(str(ds.StudyDate), '%Y%m%d').date()
        except ValueError:
            pass
    study.folder_path = str(study_dir.absolute())
    study.save()
    return study


def _upsert_series_instance(ds: Dataset, study: DICOMStudy) -> None:
    """Populate the DICOMSeries/DICOMInstance hierarchy for a stored
    instance, so series/instance records exist immediately after retrieval
    rather than only after de-identification Pass 0 (which get_or_creates
    the same rows)."""
    series_uid = str(getattr(ds, 'SeriesInstanceUID', '') or '').strip()
    sop_uid = str(getattr(ds, 'SOPInstanceUID', '') or '').strip()
    if not series_uid or not sop_uid:
        return

    date_str = str(
        getattr(ds, 'SeriesDate', '') or getattr(ds, 'StudyDate', '') or ''
    )
    series_date = None
    if date_str:
        try:
            series_date = datetime.strptime(date_str, '%Y%m%d').date()
        except ValueError:
            pass

    frame_uid = getattr(ds, 'FrameOfReferenceUID', None)
    series, _ = DICOMSeries.objects.get_or_create(
        series_instance_uid=series_uid,
        defaults={
            'study': study,
            'series_date': series_date,
            'modality': str(getattr(ds, 'Modality', '') or '')[:16],
            'frame_of_reference_uid': str(frame_uid) if frame_uid else None,
        },
    )
    DICOMInstance.objects.get_or_create(
        sop_instance_uid=sop_uid, defaults={'series': series},
    )
