import logging
from datetime import datetime, timedelta
from typing import Tuple

from client_app.models import DICOMStudy
from deidentification.models import DeidPatient, DeidStudy
from deidentification.utils.uid_generation import generate_deidentified_study_uid

logger = logging.getLogger(__name__)


def deidentify_study_data(
    deid_patient: DeidPatient,
    study: DICOMStudy,
    study_date: str,
    days_shift: int,
) -> Tuple[str, str]:
    existing = DeidStudy.objects.filter(study=study).first()
    if existing:
        return (
            existing.deidentified_study_instance_uid,
            existing.deidentified_study_date,
        )

    deidentified_study_uid = generate_deidentified_study_uid(deid_patient.deidentified_patient_id)

    study_date_obj = datetime.strptime(study_date, "%Y%m%d")
    shifted_date = study_date_obj + timedelta(days=days_shift)
    deidentified_study_date = shifted_date.strftime("%Y%m%d")

    DeidStudy.objects.create(
        study=study,
        deid_patient=deid_patient,
        deidentified_study_instance_uid=deidentified_study_uid,
        deidentified_study_date=deidentified_study_date,
    )

    logger.info(f"Created DeidStudy for {study.study_instance_uid[:30]}...: deid_uid={deidentified_study_uid}")
    return deidentified_study_uid, deidentified_study_date
