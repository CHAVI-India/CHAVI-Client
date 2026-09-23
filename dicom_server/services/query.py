"""C-FIND query matching against client_app.Patient / DICOMStudy.

Supports DICOM single-value matching, universal (empty) matching, wildcard
matching ('*' any sequence, '?' single char) and DA range matching
('YYYYMMDD-YYYYMMDD'). Attributes we cannot answer (e.g. PatientName,
AccessionNumber) are treated as return keys and echoed back empty.
"""
import logging
import re
from datetime import datetime, date
from pathlib import Path

from pydicom.dataset import Dataset

from client_app.models import Patient, DICOMStudy, _make_canonical_id

logger = logging.getLogger(__name__)

# Attributes we can actually answer per level
_PATIENT_KEYS = ('PatientID', 'PatientName', 'PatientBirthDate', 'PatientSex')
_STUDY_KEYS = (
    'PatientID', 'PatientName', 'StudyInstanceUID', 'StudyDate', 'StudyTime',
    'StudyDescription', 'AccessionNumber', 'ModalitiesInStudy',
    'NumberOfStudyRelatedSeries', 'NumberOfStudyRelatedInstances',
)


def _wildcard_regex(pattern: str):
    return re.compile(
        '^' + re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.') + '$',
        re.IGNORECASE,
    )


def match_value(query_value, db_value) -> bool:
    """DICOM single-value / universal / wildcard matching."""
    if query_value is None or str(query_value) == '':
        return True  # universal — acts as a return-key request
    q, v = str(query_value), str(db_value or '')
    if '*' in q or '?' in q:
        return bool(_wildcard_regex(q).match(v))
    return q.upper() == v.upper()


def match_date(query_value, db_date) -> bool:
    """DA matching: exact 'YYYYMMDD' or range 'A-B' (open-ended allowed)."""
    if query_value is None or str(query_value) == '' or db_date is None:
        return True if query_value in (None, '') else False
    q = str(query_value)

    def parse(d):
        return datetime.strptime(d, '%Y%m%d').date()

    try:
        if '-' in q:
            lo, hi = q.split('-', 1)
            if lo and db_date < parse(lo):
                return False
            if hi and db_date > parse(hi):
                return False
            return True
        return db_date == parse(q)
    except ValueError:
        return False


def _patient_matches(identifier):
    """Patients matching the query's patient-level keys."""
    q_pid = getattr(identifier, 'PatientID', None)
    candidates = Patient.objects.all()
    if q_pid not in (None, ''):
        q = str(q_pid)
        if '*' in q or '?' in q:
            regex = _wildcard_regex(q)
            candidates = [p for p in candidates if regex.match(p.patient_id)]
        else:
            candidates = candidates.filter(patient_id=q)
            if not candidates.exists():
                # canonical fallback — same rule as ingest
                canon = _make_canonical_id(q)
                candidates = [
                    p for p in Patient.objects.only('patient_id')
                    if _make_canonical_id(p.patient_id) == canon
                    or _make_canonical_id(p.patient_id).endswith(canon)
                ]
    return list(candidates)


def _fill(ds: Dataset, identifier, level: str, values: dict) -> Dataset:
    """Build a response identifier: every requested key we know gets its value,
    other requested keys come back empty."""
    ds.QueryRetrieveLevel = level
    keys = _PATIENT_KEYS if level == 'PATIENT' else _STUDY_KEYS
    requested = {e.keyword for e in identifier if e.keyword}
    for kw in keys:
        if kw in requested or kw in values:
            setattr(ds, kw, str(values.get(kw, '') or ''))
    # echo empty for any other requested key we cannot answer
    for e in identifier:
        if e.keyword and e.keyword not in ds and e.keyword != 'QueryRetrieveLevel':
            ds.add_new(e.tag, e.VR, '')
    return ds


def iter_find_responses(identifier, level: str):
    """Yield response identifier Datasets for a C-FIND query."""
    if level == 'PATIENT':
        for patient in _patient_matches(identifier):
            yield _fill(Dataset(), identifier, level, {
                'PatientID': patient.patient_id,
                'PatientName': '',
                'PatientBirthDate': (
                    patient.date_of_birth.strftime('%Y%m%d')
                    if patient.date_of_birth else ''
                ),
                'PatientSex': (patient.gender or '')[:1].upper(),
            })
        return

    # STUDY level — patient keys scope the study search
    q_pid = getattr(identifier, 'PatientID', None)
    studies = DICOMStudy.objects.select_related('patient').all()
    if q_pid not in (None, ''):
        patient_ids = [p.patient_id for p in _patient_matches(identifier)]
        studies = studies.filter(patient__patient_id__in=patient_ids)

    for study in studies:
        if not match_value(getattr(identifier, 'StudyInstanceUID', None), study.study_instance_uid):
            continue
        if not match_value(getattr(identifier, 'StudyDescription', None), study.study_description):
            continue
        if not match_value(getattr(identifier, 'ModalitiesInStudy', None), study.study_modalities):
            continue
        if not match_date(getattr(identifier, 'StudyDate', None), study.study_date):
            continue

        n_instances = None
        if study.folder_path and Path(study.folder_path).is_dir():
            n_instances = len(list(Path(study.folder_path).glob('*.dcm')))

        yield _fill(Dataset(), identifier, level, {
            'PatientID': study.patient.patient_id,
            'PatientName': '',
            'StudyInstanceUID': study.study_instance_uid,
            'StudyDate': study.study_date.strftime('%Y%m%d') if study.study_date else '',
            'StudyTime': '',
            'StudyDescription': study.study_description or '',
            'AccessionNumber': '',
            'ModalitiesInStudy': study.study_modalities or '',
            'NumberOfStudyRelatedInstances': n_instances if n_instances is not None else '',
        })
