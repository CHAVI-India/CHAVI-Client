import logging
from typing import Dict

from deidentification.models import DeidPatient

logger = logging.getLogger(__name__)


def get_sop_instance_mapping(deid_patient: DeidPatient) -> Dict[str, str]:
    uid_mapping = {}

    for deid_study in DeidPatient.objects.filter(pk=deid_patient.pk).first().deid_studies.all():
        original_study_uid = deid_study.study.study_instance_uid
        uid_mapping[original_study_uid] = deid_study.deidentified_study_instance_uid

        for deid_series in deid_study.deid_series.all():
            original_series_uid = deid_series.series.series_instance_uid
            uid_mapping[original_series_uid] = deid_series.deidentified_series_instance_uid

            for deid_instance in deid_series.deid_instances.all():
                original_sop_uid = deid_instance.instance.sop_instance_uid
                uid_mapping[original_sop_uid] = deid_instance.deidentified_sop_instance_uid

    logger.debug(f"Built UID mapping with {len(uid_mapping)} entries for patient {deid_patient.patient.patient_id}")
    return uid_mapping
