import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_engine = None

DEFAULT_SKIP_MODALITIES = {'MR', 'RTPLAN', 'RTDOSE', 'RTSTRUCT', 'REG'}
DEFAULT_FILL = "contrast"


def _get_skip_modalities():
    return getattr(settings, 'DEID_SKIP_PIXEL_SCRUB_MODALITIES', DEFAULT_SKIP_MODALITIES)


def _get_engine():
    global _engine
    if _engine is None:
        from presidio_image_redactor import DicomImageRedactorEngine
        _engine = DicomImageRedactorEngine()
    return _engine


def scrub_burnt_in_pixels(dcm, modality=None, job=None):
    skip_modalities = _get_skip_modalities()

    if modality and modality in skip_modalities:
        logger.debug(f"Skipping pixel scrubbing for modality {modality}")
        return dcm, None

    engine = _get_engine()

    log_bboxes = getattr(settings, 'DEID_LOG_PIXEL_REDACTION_BBOXES', True)

    if log_bboxes:
        try:
            redacted, bboxes = engine.redact_and_return_bbox(dcm, use_metadata=True, fill=DEFAULT_FILL)
            logger.debug(f"Pixel scrubbing completed with {len(bboxes) if bboxes else 0} redaction regions")
            return redacted, bboxes
        except Exception as e:
            logger.warning(f"redact_and_return_bbox failed, falling back to redact: {e}")
            redacted = engine.redact(dcm, use_metadata=True, fill=DEFAULT_FILL)
            return redacted, None
    else:
        redacted = engine.redact(dcm, use_metadata=True, fill=DEFAULT_FILL)
        return redacted, None
