import logging

import pydicom

logger = logging.getLogger(__name__)

DEVICE_TAGS = {
    'DeviceSerialNumber',
    'PlateID',
    'GeneratorID',
    'CassetteID',
    'GantryID',
}

PROCEDURE_TAGS = {
    'RequestedProcedureID',
    'ScheduledProcedureStepID',
    'FillerOrderNumberImagingServiceRequest',
    'PlacerOrderNumberImagingServiceRequest',
}

FREE_TEXT_TAGS = {
    'StudyDescription',
    'SeriesDescription',
    'ImageComments',
    'AdditionalPatientHistory',
    'StudyComments',
    'PatientComments',
    'RequestedProcedureDescription',
    'PerformedProcedureStepDescription',
    'ProtocolName',
    'AcquisitionProtocolDescription',
}

ALL_REPLACEMENT_TAGS = DEVICE_TAGS | PROCEDURE_TAGS | FREE_TEXT_TAGS


def tag_replacement_callback_factory() -> callable:
    def callback(ds: pydicom.Dataset, elem: pydicom.DataElement) -> None:
        if elem.keyword in ALL_REPLACEMENT_TAGS:
            try:
                if not elem.value:
                    return
                original_value = str(elem.value)
                elem.value = "#"
                logger.debug(f"Replaced {elem.keyword} ({elem.tag}) from '{original_value}' to '#'")
            except Exception as e:
                logger.error(f"Error replacing tag {elem.keyword}: {str(e)}")

    return callback


def deidentify_tags(dcm: pydicom.Dataset) -> bool:
    try:
        callback = tag_replacement_callback_factory()
        dcm.walk(callback)
        return True

    except Exception as e:
        logger.error(f"Error in tag replacement: {str(e)}", exc_info=True)
        return False
