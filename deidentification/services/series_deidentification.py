import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional

from client_app.models import DICOMSeries
from deidentification.models import DeidStudy, DeidSeries
from deidentification.utils.uid_generation import (
    generate_deidentified_series_uid,
    generate_deidentified_frame_of_reference_uid,
)

logger = logging.getLogger(__name__)


def deidentify_series_data(
    deid_study: DeidStudy,
    dicom_series: DICOMSeries,
    days_shift: int,
) -> Tuple[str, str, Optional[str]]:
    existing = DeidSeries.objects.filter(series=dicom_series).first()
    if existing:
        return (
            existing.deidentified_series_instance_uid,
            existing.deidentified_series_date,
            existing.deidentified_frame_of_reference_uid,
        )

    deid_study_uid = deid_study.deidentified_study_instance_uid

    series_count = DeidSeries.objects.filter(deid_study=deid_study).count()
    new_series_number = series_count + 1
    deid_series_uid = generate_deidentified_series_uid(deid_study_uid, new_series_number)

    deid_frame_uid = None
    if dicom_series.frame_of_reference_uid:
        existing_for = DeidSeries.objects.filter(
            series__frame_of_reference_uid=dicom_series.frame_of_reference_uid,
            deidentified_frame_of_reference_uid__isnull=False,
        ).exclude(deidentified_frame_of_reference_uid='').first()

        if existing_for:
            deid_frame_uid = existing_for.deidentified_frame_of_reference_uid
        else:
            deid_frame_uid = generate_deidentified_frame_of_reference_uid(deid_series_uid)

    deid_series_date = None
    if dicom_series.series_date:
        series_date_str = dicom_series.series_date.strftime("%Y%m%d")
        shifted = datetime.strptime(series_date_str, "%Y%m%d") + timedelta(days=days_shift)
        deid_series_date = shifted.strftime("%Y%m%d")

    DeidSeries.objects.create(
        series=dicom_series,
        deid_study=deid_study,
        deidentified_series_instance_uid=deid_series_uid,
        deidentified_series_date=deid_series_date,
        deidentified_frame_of_reference_uid=deid_frame_uid,
    )

    logger.info(f"Created DeidSeries for {dicom_series.series_instance_uid[:30]}...: deid_uid={deid_series_uid}")
    return deid_series_uid, deid_series_date, deid_frame_uid
