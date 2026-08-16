import logging
from typing import Dict

from deidentification.models import DeidPatient

logger = logging.getLogger(__name__)


def get_frame_of_reference_mapping(deid_patient: DeidPatient) -> Dict[str, str]:
    uid_mapping = {}

    deid_series_qs = (
        DeidPatient.objects.filter(pk=deid_patient.pk)
        .first()
        .deid_studies.all()
        .values_list('pk', flat=True)
    )

    for deid_study_id in deid_series_qs:
        from deidentification.models import DeidStudy
        deid_study = DeidStudy.objects.get(pk=deid_study_id)
        for deid_series in deid_study.deid_series.all():
            original_for = deid_series.series.frame_of_reference_uid
            deid_for = deid_series.deidentified_frame_of_reference_uid
            if original_for and deid_for:
                uid_mapping[original_for] = deid_for

    logger.debug(f"Built Frame of reference mapping with {len(uid_mapping)} entries for patient {deid_patient.patient.patient_id}")
    return uid_mapping
