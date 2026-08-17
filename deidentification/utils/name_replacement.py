import logging
from typing import Callable

import pydicom

logger = logging.getLogger(__name__)

NAME_FIELDS = {
    'PatientName',
    'ReferringPhysicianName',
    'InstitutionName',
    'PerformingPhysicianName',
    'OperatorsName',
    'StationName',
    'InstitutionalDepartmentName',
    'PhysiciansOfRecord',
    'RequestingPhysician',
    'ReferringPhysicianIdentificationSequence',
    'ConsultingPhysicianName',
    'ResponsiblePerson',
    'ReviewerName',
    'InstitutionCodeSequence',
    'PhysiciansReadingStudyIdentificationSequence',
    'OperatorIdentificationSequence',
}

HASH_FIELDS = {
    'OtherPatientIDs',
    'OtherPatientIDsSequence',
    'MedicalRecordLocator',
    'PatientInsurancePlanCodeSequence',
    'ContentCreatorName',
    'ContentDescription'
}


def name_callback_factory() -> Callable:
    def name_callback(ds: pydicom.Dataset, elem: pydicom.DataElement) -> None:
        if elem.keyword in NAME_FIELDS:
            try:
                if not elem.value:
                    return
                original_value = str(elem.value)
                elem.value = "Anonymous"
                logger.debug(f"Anonymized {elem.keyword} ({elem.tag}) from '{original_value}' to 'Anonymous'")
            except Exception as e:
                logger.error(f"Error processing name in tag {elem.tag}: {str(e)}")

        if elem.keyword in HASH_FIELDS:
            try:
                if not elem.value:
                    return
                original_value = str(elem.value)
                elem.value = "#"
                logger.debug(f"Replaced {elem.keyword} ({elem.tag}) from '{original_value}' to '#'")
            except Exception as e:
                logger.error(f"Error processing patient identifier in tag {elem.tag}: {str(e)}")

    return name_callback


def deidentify_names(dcm: pydicom.Dataset) -> bool:
    try:
        callback = name_callback_factory()
        dcm.walk(callback)

        for field in ['PatientName', 'ReferringPhysicianName']:
            if hasattr(dcm, field):
                original = getattr(dcm, field)
                if original:
                    setattr(dcm, field, f"Anonymous {field}")
                    logger.debug(f"Directly anonymized {field} from '{original}' to 'Anonymous {field}'")

        return True

    except Exception as e:
        logger.error(f"Error deidentifying names: {str(e)}", exc_info=True)
        return False
