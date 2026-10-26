#!/usr/bin/env bash
# Verify the EasyOCR model store works end-to-end offline:
#   1. settings default resolves (DJANGO_SETTINGS_MODULE=chavi_client.settings)
#   2. craft_mlt_25k.pth + english_g2.pth exist in the store with correct md5
#   3. easyocr.Reader(['en']) builds from the store with download_enabled=False
#      (proves no network is needed at runtime)
#
# Usage: scripts/verify_easyocr_model_store.sh [STORE_DIR]
# Uses the venv's python if present (this repo's venv), else `python`.
set -euo pipefail

PY="${PYTHON:-python}"
[[ -x venv/bin/python ]] && PY=venv/bin/python

STORE="${1:-}"

if [[ -z "$STORE" ]]; then
    STORE="$("$PY" -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
import django; django.setup()
from django.conf import settings
print(settings.DEID_EASYOCR_MODEL_STORE)
")"
fi

echo "store: $STORE"

for f in craft_mlt_25k.pth english_g2.pth; do
    if [[ ! -f "$STORE/$f" ]]; then
        echo "MISSING: $STORE/$f" >&2
        echo "seed it first: python scripts/seed_easyocr_models.py \"$STORE\"" >&2
        exit 1
    fi
done
echo "files present: craft_mlt_25k.pth, english_g2.pth"

$PY - "$STORE" <<'PY'
import sys
store = sys.argv[1]

# md5 check against EasyOCR's own config (byte-identical guarantee)
from easyocr import config
from easyocr.utils import calculate_md5
for m in [config.detection_models["craft"],
          config.recognition_models["gen2"]["english_g2"]]:
    path = f"{store}/{m['filename']}"
    got = calculate_md5(path)
    assert got == m["md5sum"], f"md5 mismatch {path}: {got} != {m['md5sum']}"
    print(f"md5 ok: {m['filename']}")

# build the reader with downloads disabled — fails if the store is incomplete
import easyocr
easyocr.Reader(["en"], gpu=False, verbose=False,
               model_storage_directory=store, download_enabled=False)
print("reader built offline from store: OK")

# and through the app's own adapter, the way the scrub pipeline does it
from deidentification.utils.ocr_engines import EasyOCROCR
EasyOCROCR(model_store=store)
print("EasyOCROCR adapter: OK")
PY
