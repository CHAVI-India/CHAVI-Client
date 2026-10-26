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
from easyocr.utils import download_and_unzip
from easyocr import config

store = os.environ["EASYOCR_MODEL_STORE"]
det = config.detection_models["craft"]
if not os.path.isfile(os.path.join(store, det["filename"])):
    download_and_unzip(det["url"], det["filename"], store, verbose=False)
rec = config.recognition_models["gen2"]["english_g2"]
if not os.path.isfile(os.path.join(store, rec["filename"])):
    download_and_unzip(rec["url"], rec["filename"], store, verbose=False)
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