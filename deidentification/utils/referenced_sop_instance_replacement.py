import logging
from typing import Dict

import pydicom

logger = logging.getLogger(__name__)

DEFAULT_UID = "1.2.826.0.1.3680043.10.1561.999.99.999"

REFERENCED_SOP_TAGS = [
    (0x0008, 0x1155),
    (0x0020, 0x000E),
    (0x0020, 0x000D),
]


def referenced_sop_callback(ds, elem, uid_mapping: Dict[str, str]):
    if elem.tag in REFERENCED_SOP_TAGS:
        original_uid = elem.value
        if original_uid in uid_mapping:
            elem.value = uid_mapping[original_uid]
            logger.debug(f"Replaced UID for tag {elem.tag}: {original_uid} -> {uid_mapping[original_uid]}")
        else:
            elem.value = DEFAULT_UID
            logger.warning(f"No mapping found for UID {original_uid} in tag {elem.tag}, replaced with default value")


def replace_referenced_sop_instances(dcm: pydicom.Dataset, uid_mapping: Dict[str, str]) -> bool:
    try:
        if not uid_mapping:
            logger.warning("No SOP Instance UID mapping provided")
            return False

        dcm.walk(lambda ds, elem: referenced_sop_callback(ds, elem, uid_mapping))
        return True

    except Exception as e:
        logger.error(f"Error replacing Referenced SOP Instance UIDs: {str(e)}")
        return False
