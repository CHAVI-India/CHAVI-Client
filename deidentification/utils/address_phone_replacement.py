import logging
from typing import Callable

import pydicom

logger = logging.getLogger(__name__)

ADDRESS_TAGS = {
    (0x0040, 0x1102): "Anonymous Address",
    (0x0008, 0x0081): "Anonymous Address",
    (0x0008, 0x0092): "Anonymous Address",
}

PHONE_TAGS = {
    (0x0040, 0x1103): "1234567890",
    (0x0010, 0x2154): "1234567890",
}


def address_phone_callback_factory() -> Callable:
    def callback(ds: pydicom.Dataset, elem: pydicom.DataElement) -> None:
        if elem.tag in ADDRESS_TAGS:
            try:
                if not elem.value:
                    return
                original_value = str(elem.value)
                elem.value = ADDRESS_TAGS[elem.tag]
                logger.debug(f"Anonymized {elem.keyword} ({elem.tag}) from '{original_value}' to '{elem.value}'")
            except Exception as e:
                logger.error(f"Error anonymizing address field: {str(e)}")

        if elem.tag in PHONE_TAGS:
            try:
                if not elem.value:
                    return
                original_value = str(elem.value)
                elem.value = PHONE_TAGS[elem.tag]
                logger.debug(f"Anonymized {elem.keyword} ({elem.tag}) from '{original_value}' to '{elem.value}'")
            except Exception as e:
                logger.error(f"Error anonymizing phone field: {str(e)}")

    return callback


def deidentify_address_phone(dcm: pydicom.Dataset) -> bool:
    try:
        callback = address_phone_callback_factory()
        dcm.walk(callback)
        return True

    except Exception as e:
        logger.error(f"Error deidentifying address and phone: {str(e)}", exc_info=True)
        return False
