import logging
from datetime import datetime, timedelta
from typing import Callable

import pydicom

logger = logging.getLogger(__name__)


def date_callback_factory(days_shifted: int) -> Callable:
    def date_callback(ds: pydicom.Dataset, elem: pydicom.DataElement) -> None:
        if 'date' in elem.name.lower():
            if elem.VR in ['DA', 'DT']:
                try:
                    if not elem.value:
                        return

                    if isinstance(elem.value, pydicom.multival.MultiValue) or isinstance(elem.value, list):
                        shifted_dates = []
                        for date_value in elem.value:
                            if not date_value:
                                shifted_dates.append(date_value)
                                continue

                            original_value = str(date_value)

                            if elem.VR == 'DA':
                                date_obj = datetime.strptime(original_value, "%Y%m%d")
                                shifted_date = date_obj + timedelta(days=days_shifted)
                                shifted_dates.append(shifted_date.strftime("%Y%m%d"))

                            elif elem.VR == 'DT':
                                date_part = original_value[:8]
                                time_part = original_value[8:]
                                date_obj = datetime.strptime(date_part, "%Y%m%d")
                                shifted_date = date_obj + timedelta(days=days_shifted)
                                shifted_dates.append(shifted_date.strftime("%Y%m%d") + time_part)

                        elem.value = shifted_dates
                        logger.debug(f"Shifted multi-valued date in tag {elem.tag}")
                    else:
                        original_value = str(elem.value)

                        if elem.VR == 'DA':
                            date_obj = datetime.strptime(original_value, "%Y%m%d")
                            shifted_date = date_obj + timedelta(days=days_shifted)
                            elem.value = shifted_date.strftime("%Y%m%d")
                            logger.debug(f"Shifted date {original_value} to {elem.value}")

                        elif elem.VR == 'DT':
                            date_part = original_value[:8]
                            time_part = original_value[8:]
                            date_obj = datetime.strptime(date_part, "%Y%m%d")
                            shifted_date = date_obj + timedelta(days=days_shifted)
                            elem.value = shifted_date.strftime("%Y%m%d") + time_part
                            logger.debug(f"Shifted datetime {original_value} to {elem.value}")

                except ValueError as e:
                    logger.error(f"Error processing date in tag {elem.tag}: {str(e)}")

    return date_callback


def deidentify_dates(dcm: pydicom.Dataset, days_shifted: int) -> bool:
    try:
        if days_shifted == 0:
            logger.warning("Using no date shift as shift value is 0")

        callback = date_callback_factory(days_shifted)
        dcm.walk(callback)

        return True

    except Exception as e:
        logger.error(f"Error deidentifying dates: {str(e)}")
        return False
