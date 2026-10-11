"""Pluggable OCR engines for burnt-in pixel scrubbing.

The presidio image-redactor pipeline expects an OCR object whose
``perform_ocr(pil_image)`` returns a dict of word/line-level boxes:
``text / left / top / width / height / conf``.  These adapters implement that
contract so alternative OCR engines can be swapped in via
``settings.DEID_PIXEL_OCR_ENGINE``.

Currently shipped:
    * EasyOCROCR  — on-prem deep-learning OCR (recommended for burnt-in text).
"""

from __future__ import annotations

__all__ = ["EasyOCROCR", "titlecase_word"]


def titlecase_word(text: str) -> str:
    """Length-preserving title-case.

    Burnt-in annotations are usually ALL CAPS, which degrades cased NER models.
    Normalizing to title case *only when the length is preserved* keeps the
    character offsets (and thus the bbox mapping) exact.
    """
    if not text:
        return text
    norm = text.title()
    return norm if len(norm) == len(text) else text


class EasyOCROCR:
    """EasyOCR adapter (on-prem, no PHI leaves the box).

    EasyOCR returns **line-level** boxes with the full line text.  presidio's
    span->box mapper handles this: a multi-word PHI maps to its containing
    line box (coarser, but fine for redaction and better for long/multi-word
    PHI like addresses).
    """

    def __init__(self, lang: str = "en", gpu: bool = False,
                 normalize_case: bool = True):
        import easyocr

        self._reader = easyocr.Reader([lang], gpu=gpu, verbose=False)
        self._normalize_case = normalize_case

    # ---- interface bits the presidio analyzer engine expects ----
    @staticmethod
    def get_text_from_ocr_dict(ocr_result, separator: str = " ") -> str:
        if not ocr_result:
            return ""
        return separator.join(ocr_result["text"])

    def perform_ocr(self, image, **kwargs):
        import numpy as np
        from PIL import Image

        img = image if isinstance(image, Image.Image) else Image.open(image)
        arr = np.array(img.convert("RGB"))
        out = {"text": [], "left": [], "top": [], "width": [],
               "height": [], "conf": []}
        for box, text, conf in self._reader.readtext(arr):
            if not text or not text.strip():
                continue
            t = text.strip()
            if self._normalize_case:
                t = titlecase_word(t)
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out["text"].append(t)
            out["left"].append(int(min(xs)))
            out["top"].append(int(min(ys)))
            out["width"].append(int(max(xs) - min(xs)))
            out["height"].append(int(max(ys) - min(ys)))
            out["conf"].append(round(float(conf), 4))
        return out
