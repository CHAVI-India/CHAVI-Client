"""Shared DICOM pixel-codec helpers for the ingest pathways.

Every pathway that persists a DICOM instance to disk runs it through
:func:`compress_to_j2k_lossless` before ``save_as`` so the instance is
stored as *JPEG 2000 Image Compression (Lossless Only)*
(1.2.840.10008.1.2.4.90) — roughly 75% smaller for typical CT/MR slices
while the pixel data stays exactly recoverable.

Verified against the live media/ corpus (CT, MR, RTPLAN, RTDOSE,
RTSTRUCT instances) by ``scripts/test_j2k_roundtrip.py``:
the compress -> save -> read -> decompress round trip is pixel-for-pixel
lossless, and the helper is a no-op for instances J2K cannot encode.
"""
from pydicom.uid import JPEG2000Lossless, UID


def is_compressible(ds) -> bool:
    """True when the instance carries pixel data that JPEG 2000 can encode.

    OpenJPEG only accepts 1..24-bit samples; instances with wider pixel
    data (e.g. the legacy 32-bit files mislabelled as RTDOSE) or without
    any pixel data (RTPLAN/RTDOSE/RTSTRUCT/SR/...) must be stored as-is.
    """
    if not (hasattr(ds, 'PixelData')
            and hasattr(ds, 'Rows')
            and hasattr(ds, 'Columns')
            and hasattr(ds, 'BitsAllocated')):
        return False
    bits_allocated = int(getattr(ds, 'BitsAllocated', 0) or 0)
    bits_stored = int(getattr(ds, 'BitsStored', bits_allocated) or bits_allocated)
    return 1 <= bits_stored <= 24 and bits_allocated <= 24


def compress_to_j2k_lossless(ds) -> None:
    """Compress ``ds`` in-place to JPEG 2000 lossless before saving.

    - Not :func:`is_compressible` (no pixel data / samples too wide) -> no-op.
    - Already stored as JPEG2000Lossless -> no-op.
    - Any other compressed syntax -> decompress first (compressing an
      already-compressed dataset raises ``ValueError``) then re-encode.
    - The (0008,0018) SOP Instance UID is preserved
      (``generate_instance_uid=False``): filenames and DB rows are keyed on
      the original UID.

    See https://pydicom.github.io/pydicom/stable/guides/encoding/jpeg_2k.html
    """
    if not is_compressible(ds):
        return

    ts_el = ds.file_meta.get('TransferSyntaxUID')
    ts = ts_el.value if hasattr(ts_el, 'value') else ts_el
    if ts:
        ts_uid = ts if isinstance(ts, UID) else UID(str(ts))
        if ts_uid == JPEG2000Lossless:
            return
        if ts_uid.is_compressed:
            ds.decompress(generate_instance_uid=False)

    ds.compress(JPEG2000Lossless, generate_instance_uid=False)
