#!/usr/bin/env python
"""Seed a local EasyOCR model store so OCR runs fully offline.

Downloads EasyOCR's detection (craft_mlt_25k.pth) and English recognition
(english_g2.pth) weights into a flat directory using EasyOCR's own
download+unzip+md5-check, so the files are byte-identical to what the
runtime verifies against (no subdirs — EasyOCR reads the store directly).

Usage:
    python scripts/seed_easyocr_models.py [DEST_DIR]

DEST_DIR defaults to ./easyocr-model. Afterwards point
DEID_EASYOCR_MODEL_STORE at the directory. The same seeding happens
automatically at Docker build time (see Dockerfile).
"""

import os
import sys


def main():
    dest = sys.argv[1] if len(sys.argv) > 1 else "easyocr-model"
    os.makedirs(dest, exist_ok=True)

    from easyocr import config
    from easyocr.utils import download_and_unzip

    models = [
        config.detection_models["craft"],
        config.recognition_models["gen2"]["english_g2"],
    ]

    for m in models:
        path = os.path.join(dest, m["filename"])
        if os.path.isfile(path):
            print(f"exists, skipping: {path}")
            continue
        print(f"downloading {m['url']} -> {path} (verbose=False)")
        download_and_unzip(m["url"], m["filename"], dest, verbose=False)
        from easyocr.utils import calculate_md5
        assert calculate_md5(path) == m["md5sum"], f"md5 mismatch: {path}"

    print(f"seeded: {dest}")
    print(f"export DEID_EASYOCR_MODEL_STORE={os.path.abspath(dest)}")


if __name__ == "__main__":
    main()
