"""Classify DICOMStudy.study_type using staff-configurable StudyTypeRule rows."""
import logging
import re
from datetime import timedelta

from client_app.models import (
    DICOMStudy,
    StudyTypeRule,
    StudyTypeChoices,
    StudyTypeSource,
    Diagnosis,
    Radiotherapy,
    SystemicTherapy,
)

logger = logging.getLogger(__name__)


def _matches_operator(value: str, pattern: str, operator: str) -> bool:
    if not pattern:
        return True
    value = (value or '').strip()
    pattern = pattern.strip()
    if operator == StudyTypeRule.Operator.EXACT:
        return value.upper() == pattern.upper()
    if operator == StudyTypeRule.Operator.REGEX:
        try:
            return bool(re.search(pattern, value, re.IGNORECASE))
        except re.error:
            logger.exception('Invalid regex in StudyTypeRule: %r', pattern)
            return False
    return pattern.lower() in value.lower()


def _reference_dates(patient, event: str):
    if event == StudyTypeRule.ReferenceEvent.NONE or not patient:
        return []

    dates = []
    if event == StudyTypeRule.ReferenceEvent.DIAGNOSIS_DATE:
        dates = [d.diagnosis_date for d in patient.diagnosis_set.all() if d.diagnosis_date]
    elif event == StudyTypeRule.ReferenceEvent.RADIOTHERAPY_START:
        dates = [r.radiotherapy_start_date for r in Radiotherapy.objects.filter(diagnosis__patient=patient) if r.radiotherapy_start_date]
    elif event == StudyTypeRule.ReferenceEvent.RADIOTHERAPY_END:
        dates = [r.radiotherapy_end_date for r in Radiotherapy.objects.filter(diagnosis__patient=patient) if r.radiotherapy_end_date]
    elif event == StudyTypeRule.ReferenceEvent.SYSTEMIC_THERAPY_START:
        dates = [s.systemic_therapy_start_date for s in SystemicTherapy.objects.filter(diagnosis__patient=patient) if s.systemic_therapy_start_date]
    elif event == StudyTypeRule.ReferenceEvent.SYSTEMIC_THERAPY_END:
        dates = [s.systemic_therapy_end_date for s in SystemicTherapy.objects.filter(diagnosis__patient=patient) if s.systemic_therapy_end_date]
    return dates


def _rule_matches(rule: StudyTypeRule, study: DICOMStudy) -> bool:
    if not rule.enabled:
        return False

    if not _matches_operator(study.study_modalities, rule.match_modality, rule.modality_operator):
        return False
    if not _matches_operator(study.study_description, rule.match_study_description, rule.study_description_operator):
        return False
    if not _matches_operator(study.series_descriptions, rule.match_series_description, rule.series_description_operator):
        return False

    if rule.reference_event != StudyTypeRule.ReferenceEvent.NONE:
        if study.study_date is None:
            return False
        ref_dates = _reference_dates(study.patient, rule.reference_event)
        if not ref_dates:
            return False
        start_delta = timedelta(days=rule.date_window_start_days)
        end_delta = timedelta(days=rule.date_window_end_days)
        for ref in ref_dates:
            window_start = ref + start_delta
            window_end = ref + end_delta
            if window_start <= study.study_date <= window_end:
                break
        else:
            return False

    return True


def classify_study(study: DICOMStudy):
    """Apply the first matching StudyTypeRule; fallback to OTHER. Respects MANUAL."""
    if study.study_type_source == StudyTypeSource.MANUAL:
        return study.study_type

    rules = StudyTypeRule.objects.filter(enabled=True).order_by('priority', 'created_at')
    for rule in rules:
        if _rule_matches(rule, study):
            study.study_type = rule.study_type
            study.save(auto_classified=True, update_fields=['study_type', 'study_type_source'])
            return study.study_type

    if study.study_type != StudyTypeChoices.OTHER:
        study.study_type = StudyTypeChoices.OTHER
        study.save(auto_classified=True, update_fields=['study_type', 'study_type_source'])
    return study.study_type


def classify_patient_studies(patient):
    for study in DICOMStudy.objects.filter(patient=patient):
        classify_study(study)


def classify_all_studies(queryset=None):
    qs = queryset or DICOMStudy.objects.all()
    for study in qs:
        classify_study(study)
