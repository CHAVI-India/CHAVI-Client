import logging

from client_app.models import DICOMInstance
from deidentification.models import DeidSeries, DeidInstance
from deidentification.utils.uid_generation import generate_deidentified_sop_instance_uid

logger = logging.getLogger(__name__)


def deidentify_instance_data(
    deid_series: DeidSeries,
    dicom_instance: DICOMInstance,
) -> str:
    existing = DeidInstance.objects.filter(instance=dicom_instance).first()
    if existing:
        return existing.deidentified_sop_instance_uid

    deid_series_uid = deid_series.deidentified_series_instance_uid
    deid_sop_uid = generate_deidentified_sop_instance_uid(deid_series_uid)

    DeidInstance.objects.create(
        instance=dicom_instance,
        deid_series=deid_series,
        deidentified_sop_instance_uid=deid_sop_uid,
    )

    logger.info(f"Created DeidInstance for {dicom_instance.sop_instance_uid[:30]}...: deid_uid={deid_sop_uid}")
    return deid_sop_uid
