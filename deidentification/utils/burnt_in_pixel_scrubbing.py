import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_engine = None

DEFAULT_SKIP_MODALITIES = {'MR', 'RTPLAN', 'RTDOSE', 'RTSTRUCT', 'REG'}
DEFAULT_FILL = "contrast"


def _get_skip_modalities():
    return getattr(settings, 'DEID_SKIP_PIXEL_SCRUB_MODALITIES', DEFAULT_SKIP_MODALITIES)


def _get_ocr():
    """Build the OCR object, title-casing words when DEID_PIXEL_NORMALIZE_CASE.

    DICOM burnt-in annotations are frequently ALL CAPS, which degrades cased
    NER models (spaCy en_core_web_lg and HF token-classification alike).
    Normalization happens on ocr_result["text"] before the text is joined and
    analyzed, so char offsets and the case-sensitive bbox mapping in
    ImageAnalyzerEngine.map_analyzer_results_to_bounding_boxes stay
    consistent. Words whose title-cased form changes length (e.g. 'ß'->'Ss')
    are left untouched to keep positional math exact.
    """
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
                device="cpu",
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


def _get_engine():
    global _engine
    if _engine is None:
        from presidio_image_redactor import (
            DicomImageRedactorEngine,
            ImageAnalyzerEngine,
        )

        image_analyzer = ImageAnalyzerEngine(
            analyzer_engine=_build_analyzer_engine(),
            ocr=_get_ocr(),
        )
        _engine = DicomImageRedactorEngine(image_analyzer_engine=image_analyzer)
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
