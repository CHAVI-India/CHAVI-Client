# Stage 1: Base build stage
FROM python:3.13-slim-bookworm AS builder
 
# Create the app directory
RUN mkdir /app
 
# Set the working directory
WORKDIR /app

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

# Install dependencies first for caching benefit
COPY requirements.txt /app/ 
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-download the EasyOCR detection + recognition weights into a dedicated,
# on-prem model store so the deid pipeline can use them offline at runtime
# instead of hitting storage.googleapis.com (which is blocked on many
# corporates' proxies). Runs in the builder stage: the download happens
# exactly once per layer, is cached by Docker, and the runtime image only
# receives the finished files. If the build host has no internet the build
# fails fast here (with a clear error) rather than every deid job failing
# at runtime. Uses EasyOCR's own download+unzip+md5-check so the files are
# byte-identical to what the runtime verifies against.
ENV EASYOCR_MODEL_STORE=/opt/easyocr-model
RUN mkdir -p "$EASYOCR_MODEL_STORE" && \
    python - <<'PY'
import os
import time
import urllib.request
from zipfile import ZipFile

# EasyOCR ships its weights as GitHub release zips (github.com/JaidedAI/...).
# CI hosts have variable egress — retry each download a few times with
# backoff, verify the archive before unzipping, and fail with a message that
# names the exact URL (so the next failure is diagnosable from the log).
import hashlib

URLS = [
    ("craft_mlt_25k.pth",
     "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
     "2f8227d2def4037cdb3b34389dcf9ec1"),
    ("english_g2.pth",
     "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip",
     "5864788e1821be9e454ec108d61b887d"),
]

store = os.environ["EASYOCR_MODEL_STORE"]
for filename, url, md5 in URLS:
    dest = os.path.join(store, filename)
    if os.path.isfile(dest):
        continue
    last_err = None
    for attempt in range(1, 5):
        try:
            tmp = os.path.join(store, f".tmp-{filename}")
            urllib.request.urlretrieve(url, tmp)
            with ZipFile(tmp) as z:
                # fail fast on a truncated/corrupt download before unzipping
                bad = z.testzip()
                assert bad is None, f"corrupt zip member {bad}"
                z.extract(filename, store)
            os.remove(tmp)
            break
        except Exception as e:
            last_err = e
            print(f"download attempt {attempt}/4 failed for {filename}: {e}")
            time.sleep(5 * attempt)
    else:
        raise SystemExit(
            f"easyocr model download failed after 4 attempts: {filename} from {url} "
            f"(last error: {last_err}). Re-run the build or set up a proxy. "
            f"The runtime falls back to Tesseract OCR if this store is missing, "
            f"but EasyOCR is the preferred engine."
        )
    with open(dest, "rb") as f:
        got = hashlib.md5(f.read()).hexdigest()
    assert got == md5, f"md5 mismatch {dest}: {got} != {md5}"
    print(f"seeded {filename} ({os.path.getsize(dest)} bytes)")
print("easyocr models seeded into", store)
PY
 
# Stage 2: Production stage
FROM python:3.13-slim-bookworm
 
RUN useradd -m -r appuser && \
   mkdir /app && \
   chown -R appuser /app

# Install system packages required by pytesseract / Presidio / pydicom
# tesseract-ocr: OCR engine; poppler-utils: pdftoppm (pdf2image PDF→image rendering)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && \
    rm -rf /var/lib/apt/lists/*

# Copy the Python dependencies from the builder stage
COPY --from=builder /install /usr/local

# Copy the pre-downloaded EasyOCR model store seeded in the builder stage.
# settings.DEID_EASYOCR_MODEL_STORE defaults to this path (see
# chavi_client/settings.py), so the pixel-scrubbing OCR never attempts a
# runtime download; override the env var to seed models elsewhere.
COPY --from=builder --chown=appuser:appuser /opt/easyocr-model /opt/easyocr-model
 
# Set the working directory
WORKDIR /app
 
# Copy application code and config files
COPY --chown=appuser:appuser . .
COPY --chown=appuser:appuser gunicorn.conf.py /app/gunicorn.conf.py
 
# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 
 
# Make entry file and scripts executable (before switching user)
RUN chmod +x /app/entrypoint.docker.sh && \
    chmod +x /app/scripts/diagnose-migrations.sh && \
    chmod +x /app/scripts/repair-migrations.sh

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 8000
 
# Start the application using the entrypoint script
CMD ["/app/entrypoint.docker.sh"]