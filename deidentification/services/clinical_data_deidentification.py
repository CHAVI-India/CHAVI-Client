"""
Clinical data deidentification service.

Ports the JSON-walking logic from the legacy desktop app's
`dicomutils/clinical_data_deidentification.py` and rewrites the driving
logic to operate on an in-memory dict built from Django querysets /
serializers instead of an uploaded JSON file.

Deidentification steps (per the plan in deid_app_plan.md, Section 13):
  1. Patient ID mapping  — replace all patient_id / patient values
  2. Study UID mapping    — replace all study_instance_uid values
  3. Date shifting        — shift all date fields by the patient's date_shift_value
"""

import copy
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON walker helpers (ported as-is from legacy)
# ---------------------------------------------------------------------------

def find_patient_id_keys(data: Any, found_keys: List[str] = None, path: str = "") -> List[str]:
    if found_keys is None:
        found_keys = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            if 'patient_id' in key.lower() or key.lower() == 'patient':
                found_keys.append(new_path)
            if isinstance(value, (dict, list)):
                find_patient_id_keys(value, found_keys, new_path)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                find_patient_id_keys(item, found_keys, new_path)

    return found_keys


def find_study_uid_keys(data: Any, found_keys: List[str] = None, path: str = "") -> List[str]:
    if found_keys is None:
        found_keys = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            if 'study_instance_uid' in key.lower():
                found_keys.append(new_path)
            if isinstance(value, (dict, list)):
                find_study_uid_keys(value, found_keys, new_path)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                find_study_uid_keys(item, found_keys, new_path)

    return found_keys


def find_date_fields(data: Any, found_fields: List[str] = None, path: str = "") -> List[str]:
    if found_fields is None:
        found_fields = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            if 'date' in key.lower():
                found_fields.append(new_path)
            elif isinstance(value, str) and is_date_format(value):
                found_fields.append(new_path)
            if isinstance(value, (dict, list)):
                find_date_fields(value, found_fields, new_path)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{path}[{i}]"
            if isinstance(item, (dict, list)):
                find_date_fields(item, found_fields, new_path)

    return found_fields


def is_date_format(value: str) -> bool:
    try:
        if value and isinstance(value, str):
            datetime.strptime(value, '%Y-%m-%d')
            return True
    except ValueError:
        pass
    return False


def get_nested_value(data: Any, path: str) -> Any:
    current = data
    for part in path.replace(']', '').replace('[', '.').split('.'):
        if part:
            if part.isdigit():
                current = current[int(part)]
            else:
                current = current.get(part)
    return current


def set_nested_value(data: Any, path: str, value: Any):
    parts = path.replace(']', '').replace('[', '.').split('.')
    current = data

    for i, part in enumerate(parts[:-1]):
        if part:
            if part.isdigit():
                current = current[int(part)]
            else:
                if parts[i + 1].isdigit():
                    current = current.setdefault(part, [])
                else:
                    current = current.setdefault(part, {})

    last_part = parts[-1]
    if last_part.isdigit():
        current[int(last_part)] = value
    else:
        current[last_part] = value


def shift_date(date_str: str, shift_days: int) -> str:
    if not date_str or date_str == 'null':
        return date_str
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        shifted_date = date_obj + timedelta(days=shift_days)
        return shifted_date.strftime('%Y-%m-%d')
    except ValueError:
        return date_str


# ---------------------------------------------------------------------------
# Django-native driving logic
# ---------------------------------------------------------------------------

def deidentify_clinical_data(patient, clinical_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deidentify an in-memory clinical data dict for a given patient.

    Requires that the patient has already been DICOM-deidentified
    (i.e. a DeidPatient row exists with mappings).

    Args:
        patient: client_app.Patient instance
        clinical_data: dict built from serializers (same structure as
                       patient_data_export.py output)

    Returns:
        Deidentified copy of the clinical data dict.

    Raises:
        ValueError: if no DeidPatient mapping exists for this patient.
    """
    from deidentification.models import DeidPatient, DeidStudy

    deid_patient = DeidPatient.objects.filter(patient=patient).first()
    if not deid_patient:
        raise ValueError(
            f"Patient {patient.patient_id} has not been deidentified yet. "
            "DICOM deidentification must complete before clinical data deidentification."
        )

    deidentified_data = copy.deepcopy(clinical_data)

    # --- Step 1: Replace patient IDs ---
    patient_id_paths = find_patient_id_keys(clinical_data)
    deid_patient_id = deid_patient.deidentified_patient_id

    for path in patient_id_paths:
        original_id = get_nested_value(clinical_data, path)
        if original_id and isinstance(original_id, str):
            set_nested_value(deidentified_data, path, deid_patient_id)

    # --- Step 2: Replace study UIDs ---
    study_uid_paths = find_study_uid_keys(clinical_data)
    study_uid_map: Dict[str, str] = {}

    for deid_study in DeidStudy.objects.filter(deid_patient=deid_patient):
        original_uid = deid_study.study.study_instance_uid
        study_uid_map[original_uid] = deid_study.deidentified_study_instance_uid

    for path in study_uid_paths:
        original_uid = get_nested_value(deidentified_data, path)
        if isinstance(original_uid, list):
            deid_list = []
            for uid in original_uid:
                if isinstance(uid, str) and uid in study_uid_map:
                    deid_list.append(study_uid_map[uid])
                else:
                    deid_list.append(uid)
            set_nested_value(deidentified_data, path, deid_list)
        elif isinstance(original_uid, str) and original_uid in study_uid_map:
            set_nested_value(deidentified_data, path, study_uid_map[original_uid])

    # --- Step 3: Shift dates ---
    days_shift = deid_patient.date_shift_value
    date_paths = find_date_fields(clinical_data)

    for date_path in date_paths:
        date_value = get_nested_value(deidentified_data, date_path)
        if date_value and date_value != 'null':
            shifted = shift_date(date_value, days_shift)
            set_nested_value(deidentified_data, date_path, shifted)

    return deidentified_data
