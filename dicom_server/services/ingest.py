import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import transaction
from pydicom.dataset import Dataset

from client_app.models import Patient, DICOMStudy, _make_canonical_id
from dicom_server.models import InboundDICOMInstance

logger = logging.getLogger(__name__)

_SANITIZE_RE = re.compile(r'[/\\:*?"<>|]')

# C-STORE status codes
STATUS_SUCCESS = 0x0000
STATUS_MISSING_ATTRIBUTE = 0xA900   # required attribute missing/invalid
STATUS_UNKNOWN_PATIENT = 0xA700     # policy rejection: patient not in database
STATUS_INTERNAL_ERROR = 0xC000      # cannot understand / internal failure
STATUS_SERVER_DISABLED = 0xA700     # server is_enabled=False


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
    for db_patient in Patient.objects.only('patient_id'):
        canonical_db = _make_canonical_id(db_patient.patient_id)
        if canonical_db == canonical_dicom or canonical_db.endswith(canonical_dicom):
            return db_patient
    return None


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

    try:
        # Align with existing import services: stored files carry the canonical ID.
        ds.PatientID = patient.patient_id
        study_dir = (
            Path(settings.MEDIA_ROOT) / 'processed_dicom'
            / sanitize(patient.patient_id) / sanitize(study_uid)
        )
        study_dir.mkdir(parents=True, exist_ok=True)
        dest = study_dir / f"{sanitize(sop_uid)}.dcm"
        ds.save_as(dest, enforce_file_format=True)

        with transaction.atomic():
            _upsert_study(patient, ds, study_dir)
            InboundDICOMInstance.objects.create(
                status=InboundDICOMInstance.Status.STORED,
                matched_patient=patient, file_path=str(dest), **log_fields,
            )
        logger.info("Stored %s for patient %s (%s)", sop_uid, patient.patient_id, calling_ae)
        return IngestResult(status=STATUS_SUCCESS, file_path=str(dest), patient=patient)
    except Exception:
        logger.exception("Failed to ingest instance %s", sop_uid)
        InboundDICOMInstance.objects.create(
            status=InboundDICOMInstance.Status.REJECTED,
            reject_reason='Internal storage error', matched_patient=patient, **log_fields,
        )
        return IngestResult(status=STATUS_INTERNAL_ERROR, reason='Internal storage error')


def _upsert_study(patient: Patient, ds: Dataset, study_dir: Path) -> None:
    """Merge this instance's metadata into the DICOMStudy row (comma-joined sets)."""
    study, _ = DICOMStudy.objects.get_or_create(
        patient=patient, study_instance_uid=str(ds.StudyInstanceUID),
    )

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
