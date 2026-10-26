"""Pixel-level deidentification: scrub ALL burnt-in text from DICOM images.

Instead of running NER/PII detection on the OCR output, every word OCR
finds is redacted from the pixels — burnt-in annotations are scrubbed in
full (names, IDs, dates, free text alike), so nothing OCR reads is left
in the image.
"""

import logging
import threading

from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

_engine = None
_engine_lock = threading.Lock()

DEFAULT_SKIP_MODALITIES = {'MR', 'RTIMAGE', 'RTPLAN', 'RTDOSE', 'RTSTRUCT', 'REG'}
DEFAULT_FILL = "contrast"
# Portion of the image (corners) considered when selecting the fill color;
# must stay in sync with DicomImageRedactorEngine.redact_and_return_bbox()'s
# default so the fill color matches the redaction pipeline's choice.
DEFAULT_CROP_RATIO = 0.75
# Must stay in sync with DicomImageRedactorEngine.redact_and_return_bbox()'s
# default padding so the OCR runs on exactly the image the redaction
# pipeline would OCR.
DEFAULT_PADDING_WIDTH = 25


def _get_skip_modalities():
    return getattr(settings, 'DEID_SKIP_PIXEL_SCRUB_MODALITIES', DEFAULT_SKIP_MODALITIES)


def _get_ocr():
    """Build the OCR object.

    Engine selected by settings.DEID_PIXEL_OCR_ENGINE:
        "easyocr" (default) — on-prem EasyOCR (better on small/all-caps
            burnt-in text).
        "tesseract" — Tesseract.

    The OCR text is only used to locate text in the image — it is never
    parsed or matched — so no case normalization is applied.
    """
    engine = getattr(settings, 'DEID_PIXEL_OCR_ENGINE', 'easyocr')
    if engine == 'easyocr':
        try:
            from deidentification.utils.ocr_engines import EasyOCROCR
            # Weights are served from the on-prem model store configured in
            # settings (DEID_EASYOCR_MODEL_STORE, default /opt/easyocr-model,
            # baked into the Docker image). Any EasyOCR failure — e.g. store
            # missing on an offline box — falls back to Tesseract, so deid
            # jobs keep running instead of failing the series.
            return EasyOCROCR(
                model_store=getattr(settings, 'DEID_EASYOCR_MODEL_STORE')
            )
        except Exception as e:
            logger.warning(f"EasyOCR unavailable ({e}); falling back to Tesseract OCR")

    # Tesseract (explicit engine, or EasyOCR fallback)
    from presidio_image_redactor import TesseractOCR
    return TesseractOCR()


class _UnusedAnalyzer:
    """Placeholder analyzer engine.

    Pixel scrubbing redacts every word OCR finds, so no Presidio text
    analysis (spaCy/HF NER, pattern recognizers) is ever run. Passing this
    keeps ImageAnalyzerEngine from lazily building a default AnalyzerEngine
    (which would load the spaCy model for nothing).
    """


def _get_engine():
    global _engine
    if _engine is None:
        # Double-checked lock: the engine (EasyOCR reader) is expensive to
        # build — concurrent tasks in the same process must not build it in
        # parallel.
        with _engine_lock:
            if _engine is None:
                from presidio_image_redactor import (
                    DicomImageRedactorEngine,
                    ImageAnalyzerEngine,
                )

                image_analyzer = ImageAnalyzerEngine(
                    analyzer_engine=_UnusedAnalyzer(),
                    ocr=_get_ocr(),
                )
                _engine = DicomImageRedactorEngine(image_analyzer_engine=image_analyzer)
    return _engine


def _burnt_in_annotation_is_no(dcm):
    """True when (0028,0301) BurnedInAnnotation is explicitly 'NO'.

    An absent attribute means unknown — the image still needs checking.
    """
    value = getattr(dcm, 'BurnedInAnnotation', None)
    if value is None:
        return False
    return str(value).strip().upper() == 'NO'


def _ocr_burnt_in_text_bboxes(dcm, engine):
    """OCR the image once and return a redaction box for every word found.

    Builds exactly the image the redaction pipeline would OCR (rescaled
    pixel array -> PIL -> padding -> preprocessor), runs the OCR engine
    once, and converts every OCR word box into a redaction bbox in the
    original image coordinates (OCR padding removed).

    :return: list of bbox dicts (coordinates only — no OCR'd text, which
        must never be logged or persisted), or None when the image
        contains no text.
    """
    from presidio_image_redactor import ImageAnalyzerEngine

    is_greyscale = engine._check_if_greyscale(dcm)
    image_np = engine._rescale_dcm_pixel_array(dcm, is_greyscale)
    image_pil = Image.fromarray(image_np, mode="L" if is_greyscale else "RGB")
    padded_image_pil = engine._add_padding(image_pil, is_greyscale, DEFAULT_PADDING_WIDTH)

    analyzer = engine.image_analyzer_engine
    image, meta = analyzer.image_preprocessor.preprocess_image(padded_image_pil)
    ocr_result = analyzer.ocr.perform_ocr(image)
    ocr_result = ImageAnalyzerEngine.remove_space_boxes(ocr_result)

    if meta and "scale_factor" in meta:
        # A scaling preprocessor reports boxes in the scaled image — map
        # them back to the padded image coordinates.
        ocr_result = ImageAnalyzerEngine._scale_bbox_results(
            ocr_result, meta["scale_factor"]
        )

    bboxes = engine.bbox_processor.get_bboxes_from_ocr_results(ocr_result)
    if not bboxes:
        return None

    bboxes = engine.bbox_processor.remove_bbox_padding(bboxes, DEFAULT_PADDING_WIDTH)
    # Coordinates only — the OCR'd text itself must not leak into logs,
    # job records or the DB.
    return [
        {"left": b["left"], "top": b["top"], "width": b["width"], "height": b["height"]}
        for b in bboxes
    ]


def scrub_burnt_in_pixels(dcm, modality=None, job=None):
    skip_modalities = _get_skip_modalities()

    if modality and modality in skip_modalities:
        logger.debug(f"Skipping pixel scrubbing for modality {modality}")
        return dcm, None

    # (0028,0301) BurnedInAnnotation == 'NO': the modality declares that it
    # carries no burnt-in annotations, so there is nothing for OCR to
    # redact. Skip the whole pipeline (no engine build, no OCR).
    if _burnt_in_annotation_is_no(dcm):
        logger.debug("Skipping pixel scrubbing: BurnedInAnnotation is 'NO'")
        return dcm, None

    # No pixel data -> no burnt-in pixels to redact.
    try:
        dcm.PixelData
    except Exception:
        logger.debug("Skipping pixel scrubbing: instance has no pixel data")
        return dcm, None

    engine = _get_engine()

    # Single OCR pass: redact every word OCR finds — no NER.
    bboxes = _ocr_burnt_in_text_bboxes(dcm, engine)
    if not bboxes:
        logger.debug("Skipping pixel scrubbing: no burnt-in text detected by OCR")
        return dcm, None

    if getattr(settings, 'DEID_LOG_PIXEL_REDACTION_BBOXES', True):
        logger.debug(f"Pixel scrubbing: redacting {len(bboxes)} burnt-in text regions")

    redacted = engine._add_redact_box(dcm, bboxes, DEFAULT_CROP_RATIO, DEFAULT_FILL)
    return redacted, bboxes
