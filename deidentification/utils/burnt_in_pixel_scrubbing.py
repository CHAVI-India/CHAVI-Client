import logging
import threading

from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

_engine = None
_engine_lock = threading.Lock()

DEFAULT_SKIP_MODALITIES = {'MR', 'RTPLAN', 'RTDOSE', 'RTSTRUCT', 'REG'}
DEFAULT_FILL = "contrast"
# Must stay in sync with DicomImageRedactorEngine.redact_and_return_bbox()'s
# default padding so the OCR pre-check sees exactly the image the redaction
# pipeline will OCR.
DEFAULT_PADDING_WIDTH = 25


def _get_skip_modalities():
    return getattr(settings, 'DEID_SKIP_PIXEL_SCRUB_MODALITIES', DEFAULT_SKIP_MODALITIES)


def _get_ocr():
    """Build the OCR object.

    Engine selected by settings.DEID_PIXEL_OCR_ENGINE:
        "tesseract" (default) — Tesseract, title-cased when
            DEID_PIXEL_NORMALIZE_CASE.
        "easyocr" — on-prem EasyOCR (better on small/all-caps burnt-in text).

    Note: burnt-in annotations are frequently ALL CAPS, which degrades cased
    NER models (spaCy en_core_web_lg and HF token-classification alike).
    Normalization happens on ocr_result["text"] before the text is joined and
    analyzed, so char offsets and the case-sensitive bbox mapping in
    ImageAnalyzerEngine.map_analyzer_results_to_bounding_boxes stay
    consistent. Words whose title-cased form changes length (e.g. 'ß'->'Ss')
    are left untouched to keep positional math exact.
    """
    engine = getattr(settings, 'DEID_PIXEL_OCR_ENGINE', 'easyocr')
    if engine == 'easyocr':
        try:
            from deidentification.utils.ocr_engines import EasyOCROCR
        except Exception as e:
            logger.warning(f"EasyOCR unavailable ({e}); falling back to Tesseract OCR")
        else:
            return EasyOCROCR(
                normalize_case=getattr(settings, 'DEID_PIXEL_NORMALIZE_CASE', True),
            )

    # Tesseract (explicit engine, or EasyOCR fallback)
    from presidio_image_redactor import TesseractOCR

    if not getattr(settings, 'DEID_PIXEL_NORMALIZE_CASE', True):
        return TesseractOCR()

    class CaseNormalizingTesseractOCR(TesseractOCR):
        def perform_ocr(self, image, **kwargs):
            result = super().perform_ocr(image, **kwargs)
            for i, word in enumerate(result.get("text", [])):
                if word:
                    normalized = word.title()
                    if len(normalized) == len(word):
                        result["text"][i] = normalized
            return result

    return CaseNormalizingTesseractOCR()


def _build_analyzer_engine():
    from presidio_analyzer import AnalyzerEngine

    # Default AnalyzerEngine: spaCy en_core_web_lg provides NlpArtifacts
    # (tokens/lemmas) for LemmaContextAwareEnhancer context boosting, and
    # SpacyRecognizer detections union with the HF model's.
    analyzer = AnalyzerEngine(supported_languages=["en"])

    backend = getattr(settings, 'DEID_PIXEL_NER_BACKEND', 'hf')
    if backend == 'hf':
        from presidio_analyzer.predefined_recognizers.ner import (
            HuggingFaceNerRecognizer,
        )
        from extractor.services.embeddings import _resolve_device

        try:
            # EntityRecognizer.__init__ calls load() — the HF model is
            # downloaded and loaded here, at engine build (first scrub),
            # not lazily inside the per-image analyze loop.
            recognizer = HuggingFaceNerRecognizer(
                model_name=getattr(
                    settings, 'DEID_HF_NER_MODEL',
                    'Isotonic/deberta-v3-base_finetuned_ai4privacy_v2',
                ),
                label_mapping=getattr(settings, 'DEID_HF_LABEL_MAP', None),
                threshold=getattr(settings, 'DEID_HF_NER_THRESHOLD', 0.20),
                aggregation_strategy="simple",
                device=_resolve_device(),
                supported_language="en",
            )
        except Exception as e:
            logger.warning(
                f"HF NER model failed to load ({e}) — "
                "continuing with spaCy-only analyzer"
            )
        else:
            analyzer.registry.add_recognizer(recognizer)
    elif backend != 'none':
        logger.warning(
            f"Unknown DEID_PIXEL_NER_BACKEND={backend!r} — spaCy-only analyzer"
        )

    if getattr(settings, 'DEID_LENIENT_INDIAN_IDS', True):
        from deidentification.utils.indian_id_recognizers import (
            build_indian_id_recognizers,
        )

        for recognizer in build_indian_id_recognizers():
            analyzer.registry.add_recognizer(recognizer)

    return analyzer


class _PrimedOCR:
    """Thread-local wrapper around the real OCR engine.

    ``scrub_burnt_in_pixels()`` runs a fast OCR-only text-presence pre-check
    before invoking the full redaction pipeline. When text is found, that
    OCR result is *primed* on the calling thread and the pipeline's own
    ``perform_ocr()`` call returns it instead of re-running OCR (EasyOCR
    inference otherwise runs twice per image). A prime is consumed by the
    very next ``perform_ocr()`` on the same thread — and is only set right
    before the pipeline call — so it can never leak into another image or
    another thread.
    """

    def __init__(self, ocr):
        self._ocr = ocr
        self._local = threading.local()

    def prime(self, ocr_result):
        self._local.ocr_result = ocr_result

    def perform_ocr(self, image, **kwargs):
        result = getattr(self._local, "ocr_result", None)
        if result is not None:
            self._local.ocr_result = None
            return result
        return self._ocr.perform_ocr(image, **kwargs)

    def __getattr__(self, name):
        # Delegate everything else (e.g. get_text_from_ocr_dict).
        return getattr(self._ocr, name)


def _burnt_in_annotation_is_no(dcm):
    """True when (0028,0301) BurnedInAnnotation is explicitly 'NO'.

    An absent attribute means unknown — the image still needs checking.
    """
    value = getattr(dcm, 'BurnedInAnnotation', None)
    if value is None:
        return False
    return str(value).strip().upper() == 'NO'


def _image_has_burnt_in_text(dcm, engine):
    """OCR-only check for whether the image contains any text at all.

    Builds exactly the image the redaction pipeline will OCR (rescaled
    pixel array -> PIL -> padding -> preprocessor) and runs the OCR engine
    once. If text is found, the OCR result is primed on the (thread-local)
    OCR wrapper so the pipeline's internal OCR call reuses it and OCR runs
    only once per image.
    """
    is_greyscale = engine._check_if_greyscale(dcm)
    image_np = engine._rescale_dcm_pixel_array(dcm, is_greyscale)
    image_pil = Image.fromarray(image_np, mode="L" if is_greyscale else "RGB")
    padded_image_pil = engine._add_padding(image_pil, is_greyscale, DEFAULT_PADDING_WIDTH)

    analyzer = engine.image_analyzer_engine
    image, _meta = analyzer.image_preprocessor.preprocess_image(padded_image_pil)
    ocr_result = analyzer.ocr.perform_ocr(image)

    has_text = any(
        word and not word.isspace() for word in ocr_result.get("text", [])
    )
    if has_text and isinstance(analyzer.ocr, _PrimedOCR):
        analyzer.ocr.prime(ocr_result)

    return has_text


def _get_engine():
    global _engine
    if _engine is None:
        # Double-checked lock: the engine (EasyOCR reader + Stanford NER
        # model) is expensive to build — concurrent tasks in the same
        # process must not build it in parallel.
        with _engine_lock:
            if _engine is None:
                from presidio_image_redactor import (
                    DicomImageRedactorEngine,
                    ImageAnalyzerEngine,
                )

                image_analyzer = ImageAnalyzerEngine(
                    analyzer_engine=_build_analyzer_engine(),
                    ocr=_PrimedOCR(_get_ocr()),
                )
                _engine = DicomImageRedactorEngine(image_analyzer_engine=image_analyzer)
    return _engine


def scrub_burnt_in_pixels(dcm, modality=None, job=None):
    skip_modalities = _get_skip_modalities()

    if modality and modality in skip_modalities:
        logger.debug(f"Skipping pixel scrubbing for modality {modality}")
        return dcm, None

    # (0028,0301) BurnedInAnnotation == 'NO': the modality declares that it
    # carries no burnt-in annotations, so there is nothing for OCR/NER to
    # find. Skip the whole pipeline (no engine build, no OCR, no NER).
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

    # Fast OCR-only gate: when the image contains no text at all the full
    # redaction pipeline (NER inference, dataset deep-copies, pixel
    # re-encode/recompress) would be a no-op — skip it entirely.
    try:
        has_text = _image_has_burnt_in_text(dcm, engine)
    except Exception as e:
        logger.warning(f"OCR text-presence pre-check failed ({e}) — running full pipeline")
        has_text = True
    if not has_text:
        logger.debug("Skipping pixel scrubbing: no burnt-in text detected by OCR")
        return dcm, None

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
