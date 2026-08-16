import logging
from typing import Dict

import pydicom

logger = logging.getLogger(__name__)

REFERENCED_FOR_TAGS = [
    (0x0020, 0x0052),
    (0x3006, 0x0024),
]


def referenced_frame_of_reference_callback(ds, elem, uid_mapping: Dict[str, str]):
    if elem.tag in REFERENCED_FOR_TAGS:
        original_uid = elem.value
        if original_uid in uid_mapping:
            elem.value = uid_mapping[original_uid]
            logger.debug(f"Replaced Referenced Frame of Reference UID: {original_uid} -> {uid_mapping[original_uid]}")


def replace_referenced_frame_of_reference(dcm: pydicom.Dataset, uid_mapping: Dict[str, str]) -> bool:
    try:
        if not uid_mapping:
            logger.warning("No Frame of Reference UID mapping provided")
            return False

        dcm.walk(lambda ds, elem: referenced_frame_of_reference_callback(ds, elem, uid_mapping))
        return True

    except Exception as e:
        logger.error(f"Error replacing Referenced Frame of Reference UIDs: {str(e)}")
        return False
