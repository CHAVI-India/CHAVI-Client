import random
import uuid
from datetime import datetime, timedelta
from typing import Tuple


def generate_deidentified_patient_id() -> str:
    unique_id = str(uuid.uuid4())
    return ".".join(unique_id.split("-"))


def calculate_shifted_date(original_date: str) -> Tuple[str, int]:
    date_obj = datetime.strptime(original_date, "%Y%m%d")
    days_shift = random.randint(-100, 100)
    shifted_date = date_obj + timedelta(days=days_shift)
    shifted_date_str = shifted_date.strftime("%Y%m%d")
    return shifted_date_str, days_shift


def parse_dicom_age(age_string: str) -> int:
    if not age_string or len(age_string) < 2:
        raise ValueError("Invalid age string format")

    value = int(age_string[:-1])
    unit = age_string[-1].upper()

    if unit == 'D':
        return value
    elif unit == 'W':
        return value * 7
    elif unit == 'M':
        return value * 30
    elif unit == 'Y':
        return value * 365
    else:
        raise ValueError(f"Invalid age unit: {unit}")


def validate_and_correct_uid(uid: str) -> str:
    uid = ''.join(c for c in uid if c.isdigit() or c == '.')
    uid = uid[:64]
    if len(uid.encode('ascii')) % 2 != 0:
        uid = f"{uid}0"
    return uid


def generate_deidentified_study_uid(deidentified_patient_id: str = "") -> str:
    random_part1 = str(random.randint(100, 999))
    random_part2 = str(random.randint(1000, 9999))
    random_part3 = str(random.randint(100, 999))
    return f"1.2.826.0.1.3680043.10.1561.{random_part1}.{random_part2}.{random_part3}"


def generate_deidentified_series_uid(deidentified_study_uid: str, series_number: int) -> str:
    uid = f"{deidentified_study_uid}.{series_number}"
    return validate_and_correct_uid(uid)


def generate_deidentified_frame_of_reference_uid(deidentified_series_uid: str) -> str:
    random_part = str(random.randint(1000, 9999))
    uid = f"{deidentified_series_uid}.{random_part}"
    return validate_and_correct_uid(uid)


def generate_deidentified_sop_instance_uid(deidentified_series_uid: str) -> str:
    random_part1 = str(random.randint(1000000, 9999999))
    random_part2 = str(random.randint(100, 999))
    return f"{deidentified_series_uid}.{random_part1}.{random_part2}"
