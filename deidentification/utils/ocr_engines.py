"""Pluggable OCR engines for burnt-in pixel scrubbing.

The presidio image-redactor pipeline expects an OCR object whose
``perform_ocr(pil_image)`` returns a dict of word/line-level boxes:
``text / left / top / width / height / conf``.  These adapters implement
that contract so alternative OCR engines can be swapped in via
``settings.DEID_PIXEL_OCR_ENGINE``.

Currently shipped:
    * EasyOCROCR  — on-prem deep-learning OCR (recommended for burnt-in text).
"""

from __future__ import annotations

import logging

__all__ = ["EasyOCROCR"]

logger = logging.getLogger(__name__)


class EasyOCROCR:
    """EasyOCR adapter (on-prem, no PHI leaves the box).

    Device auto-detection: runs on CUDA whenever the container can see a
    GPU (nvidia-container-toolkit + the GPU reservation in the compose
    file); otherwise falls back to CPU with a capped thread count so a
    deid batch can't pin every core on the host.

    EasyOCR returns **line-level** boxes with the full line text, which is
    exactly what whole-text scrubbing wants: every detected line is
    redacted in its entirety.
    """

    def __init__(self, lang: str = "en", model_store: str = None):
        import easyocr
        import torch

        # Auto-detect the best available device; on the CPU path cap torch
        # threads (torch defaults to all cores, which would saturate a
        # shared host during a deid run).
        self.gpu = torch.cuda.is_available()
        if not self.gpu:
            from django.conf import settings as _s
            threads = getattr(_s, 'DEID_OCR_CPU_THREADS', 4)
            if threads and threads > 0:
                torch.set_num_threads(threads)

        # model_store keeps the weight download on-prem: point it at a
        # pre-seeded local dir (DEID_EASYOCR_MODEL_STORE) instead of letting
        # EasyOCR hit the internet at runtime. If the dir is unset/empty, use
        # EasyOCR's own default. Note: with a model_store EasyOCR looks for
        # "<store>/det/detect_cRAFT.pth" and "<store>/rec/en.pth".
        kwargs = {"gpu": self.gpu, "verbose": False}
        if model_store:
            kwargs["model_storage_directory"] = model_store
        self._reader = easyocr.Reader([lang], **kwargs)
        logger.info(
            "EasyOCR ready (device=%s)",
            "cuda" if self.gpu else "cpu",
        )

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
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            out["text"].append(text.strip())
            out["left"].append(int(min(xs)))
            out["top"].append(int(min(ys)))
            out["width"].append(int(max(xs) - min(xs)))
            out["height"].append(int(max(ys) - min(ys)))
            out["conf"].append(round(float(conf), 4))
        return out
