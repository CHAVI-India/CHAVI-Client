import logging
from datetime import datetime, timedelta
from typing import Tuple

from client_app.models import Patient
from deidentification.models import DeidPatient
from deidentification.utils.uid_generation import (
    generate_deidentified_patient_id,
    calculate_shifted_date,
    parse_dicom_age,
)

logger = logging.getLogger(__name__)


def deidentify_patient_data(
    patient: Patient,
    birth_date: str = "",
    study_date: str = "",
    age: str = "",
) -> Tuple[str, str, int]:
    existing = DeidPatient.objects.filter(patient=patient).first()
    if existing:
        return (
            existing.deidentified_patient_id,
            existing.deidentified_date_of_birth,
            existing.date_shift_value,
        )

    dob_str = None

    if patient.date_of_birth is not None:
        dob_str = patient.date_of_birth.strftime("%Y%m%d")
    elif birth_date and birth_date.strip() != "":
        dob_str = birth_date
        patient.date_of_birth = datetime.strptime(birth_date, "%Y%m%d").date()
        patient.save(update_fields=['date_of_birth'])
    elif age and age.strip() != "":
        try:
            age_in_days = parse_dicom_age(age)
            study_date_obj = datetime.strptime(study_date, "%Y%m%d")
            calculated_birth_date = study_date_obj - timedelta(days=age_in_days)
            dob_str = calculated_birth_date.strftime("%Y%m%d")
            if patient.date_of_birth is None:
                patient.date_of_birth = calculated_birth_date.date()
                patient.save(update_fields=['date_of_birth'])
        except ValueError:
            dob_str = study_date
    else:
        dob_str = study_date

    deidentified_dob, days_shift = calculate_shifted_date(dob_str)
    deidentified_id = generate_deidentified_patient_id()

    DeidPatient.objects.create(
        patient=patient,
        deidentified_patient_id=deidentified_id,
        date_shift_value=days_shift,
        deidentified_date_of_birth=deidentified_dob,
    )

    logger.info(f"Created DeidPatient for {patient.patient_id}: deid_id={deidentified_id}, days_shift={days_shift}")
    return deidentified_id, deidentified_dob, days_shift
