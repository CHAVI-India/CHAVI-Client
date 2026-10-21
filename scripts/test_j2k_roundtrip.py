#!/usr/bin/env python
"""Standalone round-trip test for JPEG 2000 lossless compress/decompress.

Uses REAL DICOM files from the local media/ folder. Instances are isolated
with the Django ORM (DICOMSeries.modality -> DICOMInstance -> file on disk)
for CT, MR, RTPLAN, RTDOSE, RTSTRUCT. Each file is checked according to
what it actually contains:
  - instances WITH pixel data (CT/MR — and mislabelled legacy files that
    carry image pixels despite an RT modality): the round trip must be
    pixel-for-pixel lossless;
  - instances WITHOUT pixel data (RT objects): the ingest compression
    helper must be a no-op, and the file must still save + reload cleanly
    (C-STORE receives these SOPs too).

The script exercises the SHARED helper (client_app/services/dicom_codec.py)
that the ingest pathways call, so it verifies the exact production code.

Intentionally NOT a Django TestCase: `manage.py test` creates a fresh test
database and the migration set is too heavy to run here. This script only
READS the live database and writes to a temp directory — it never touches
the media/ folder.

Run:  ./venv/bin/python scripts/test_j2k_roundtrip.py [--max-per-modality N]
"""
import os
import sys
import shutil
import tempfile
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Make the repo importable (script lives in scripts/) before importing app code.
sys.path.insert(0, str(BASE_DIR))


# --------------------------------------------------------------------------
# Environment / Django bootstrap (read-only DB usage, no test database)
# --------------------------------------------------------------------------

def load_dotenv(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip())


def setup_django() -> None:
    load_dotenv(BASE_DIR / '.env')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
    import django
    django.setup()


# --------------------------------------------------------------------------
# The helper under test — the shared production module used by every
# ingest pathway (imported here, not duplicated).
# --------------------------------------------------------------------------

from client_app.services.dicom_codec import (  # noqa: E402
    compress_to_j2k_lossless,
    is_compressible,
)


# --------------------------------------------------------------------------
# Instance discovery via the ORM
# --------------------------------------------------------------------------

def resolve_instance_file(study, sop_uid: str):
    """Ingest services save files as <study folder>/<sanitized sop uid>.dcm."""
    if not study.folder_path:
        return None
    base = Path(study.folder_path)
    if not base.exists():
        return None
    # '/' etc. are sanitised away in filenames by the ingest services.
    sanitized = (sop_uid.replace('/', '_').replace('\\', '_').replace(':', '_')
                 .replace('*', '_').replace('?', '_').replace('"', '_')
                 .replace('<', '_').replace('>', '_').replace('|', '_'))
    cand = base / f"{sanitized}.dcm"
    if cand.is_file():
        return cand
    hits = sorted(base.rglob(f"{sanitized}.dcm"))
    return hits[0] if hits else None


def discover(modalities, max_per_modality):
    from client_app.models import DICOMSeries

    found = {}
    for mod in modalities:
        rows = []
        for series in DICOMSeries.objects.filter(modality=mod).select_related('study'):
            study = series.study
            for inst in series.instances.all():
                path = resolve_instance_file(study, inst.sop_instance_uid)
                if path is not None:
                    rows.append((mod, inst.sop_instance_uid, path))
                if len(rows) >= max_per_modality:
                    break
            if len(rows) >= max_per_modality:
                break
        found[mod] = rows
    return found


# --------------------------------------------------------------------------
# Round-trip checks
# --------------------------------------------------------------------------

def check_image(ds, mod, sop_uid, path, workdir):
    """Full lossless round trip for an instance WITH pixel data."""
    import numpy as np
    from pydicom import dcmread
    from pydicom.uid import JPEG2000Lossless, ExplicitVRLittleEndian

    orig_ts = str(ds.file_meta.TransferSyntaxUID)
    orig_sop = str(ds.SOPInstanceUID)
    orig_size = path.stat().st_size

    # Reference pixels (auto-decompresses if the stored file is compressed).
    ref = ds.pixel_array

    compress_to_j2k_lossless(ds)

    # 1. transfer syntax is now J2K lossless
    assert str(ds.file_meta.TransferSyntaxUID) == str(JPEG2000Lossless), \
        f"TS after compress: {ds.file_meta.TransferSyntaxUID}"
    # 2. SOP UID preserved (DB rows + filenames are keyed on it)
    assert str(ds.SOPInstanceUID) == orig_sop, \
        f"SOP UID regenerated: {orig_sop} -> {ds.SOPInstanceUID}"
    assert str(ds.file_meta.MediaStorageSOPInstanceUID) == orig_sop, \
        f"MediaStorageSOPInstanceUID regenerated: {ds.file_meta.MediaStorageSOPInstanceUID}"

    out = Path(workdir) / f"{Path(path).name}.j2k"
    ds.save_as(str(out), enforce_file_format=True)

    reloaded = dcmread(str(out))
    assert str(reloaded.file_meta.TransferSyntaxUID) == str(JPEG2000Lossless), \
        f"saved file TS: {reloaded.file_meta.TransferSyntaxUID}"
    assert str(reloaded.file_meta.MediaStorageSOPInstanceUID) == orig_sop
    # fast metadata-only read path (used by deid pass 0/1) must still work
    assert str(dcmread(str(out), stop_before_pixels=True).SOPInstanceUID) == orig_sop

    # 3. decompress -> pixels must match the original exactly
    reloaded.decompress(generate_instance_uid=False)
    assert str(reloaded.file_meta.TransferSyntaxUID) == str(ExplicitVRLittleEndian), \
        f"TS after decompress: {reloaded.file_meta.TransferSyntaxUID}"
    assert np.array_equal(reloaded.pixel_array, ref), \
        "LOSS FOUND: decompressed pixels differ from the original"

    new_size = out.stat().st_size
    ratio = (new_size - orig_size) / orig_size * 100 if orig_size else 0.0
    return (f"lossless round-trip OK "
            f"(orig TS={orig_ts}, {orig_size}B -> {new_size}B, {ratio:+.1f}%, "
            f"shape={ref.shape}, dtype={ref.dtype})")


def check_file(mod, sop_uid, path, workdir):
    """Dispatch on what the instance actually contains (not the modality
    label — legacy data mislabels RTDOSE with MR Image Storage SOPs,
    some of them 32-bit and uncompressible by J2K)."""
    from pydicom import dcmread
    ds = dcmread(str(path))
    if is_compressible(ds):
        return check_image(ds, mod, sop_uid, path, workdir)
    if hasattr(ds, 'PixelData'):
        # wide pixels: helper must skip, file must save/reload unchanged
        return check_uncompressible(ds, mod, sop_uid, path, workdir)
    return check_no_pixel(ds, mod, sop_uid, path, workdir)


def check_uncompressible(ds, mod, sop_uid, path, workdir):
    """Pixel data J2K cannot encode (BitsStored > 24): helper must no-op
    and the file must still save + reload intact."""
    from pydicom import dcmread

    orig_ts = str(ds.file_meta.TransferSyntaxUID)
    orig_sop = str(ds.SOPInstanceUID)
    ref = ds.pixel_array
    import numpy as np

    compress_to_j2k_lossless(ds)

    assert str(ds.file_meta.TransferSyntaxUID) == orig_ts, \
        f"TS changed for uncompressible instance: {orig_ts} -> {ds.file_meta.TransferSyntaxUID}"
    assert str(ds.SOPInstanceUID) == orig_sop

    out = Path(workdir) / f"{Path(path).name}.keep"
    ds.save_as(str(out), enforce_file_format=True)
    reloaded = dcmread(str(out))
    assert np.array_equal(reloaded.pixel_array, ref), \
        "pixels changed for uncompressible instance"
    return (f"uncompressible no-op OK "
            f"(BitsStored={ds.BitsStored}, {orig_ts} kept)")


def check_no_pixel(ds, mod, sop_uid, path, workdir):
    """No pixel data: helper must no-op, file must still save and reload
    intact (these SOP classes arrive via C-STORE)."""
    from pydicom import dcmread

    assert not hasattr(ds, 'PixelData'), "expected no pixel data"
    orig_ts = str(ds.file_meta.TransferSyntaxUID)
    orig_sop = str(ds.SOPInstanceUID)

    compress_to_j2k_lossless(ds)

    assert str(ds.file_meta.TransferSyntaxUID) == orig_ts, \
        f"TS changed for pixel-less instance: {orig_ts} -> {ds.file_meta.TransferSyntaxUID}"
    assert str(ds.SOPInstanceUID) == orig_sop

    out = Path(workdir) / f"{Path(path).name}.keep"
    ds.save_as(str(out), enforce_file_format=True)
    reloaded = dcmread(str(out))
    for tag in ('PatientID', 'StudyInstanceUID', 'SeriesInstanceUID',
                'SOPInstanceUID', 'Modality'):
        if tag in ds:
            assert str(getattr(reloaded, tag)) == str(getattr(ds, tag)), \
                f"{tag} changed on save/reload"
    return "no-pixel no-op OK (saved + reloaded intact)"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run_synthetic_scenarios(src_path, workdir):
    """Compressed-input scenarios built from one real image file.

    1. already-J2K: helper must be a no-op (no double encode).
    2. other compressed syntax (RLE lossless): helper must decompress
       and re-encode to J2K losslessly.
    """
    import numpy as np
    from pydicom import dcmread
    from pydicom.uid import JPEG2000Lossless, RLELossless

    failures = []
    src = dcmread(str(src_path))
    ref = src.pixel_array

    # 1. already J2K -> no-op
    try:
        a = dcmread(str(src_path))
        a.compress(JPEG2000Lossless, generate_instance_uid=False)
        p1 = Path(workdir) / 'synthetic_already_j2k.dcm'
        a.save_as(str(p1), enforce_file_format=True)
        b = dcmread(str(p1))
        sop_before = str(b.SOPInstanceUID)
        compress_to_j2k_lossless(b)
        assert str(b.file_meta.TransferSyntaxUID) == str(JPEG2000Lossless)
        assert str(b.SOPInstanceUID) == sop_before
        b.decompress(generate_instance_uid=False)
        assert np.array_equal(b.pixel_array, ref)
        print("PASS  synthetic/already-J2K-no-op\n        no-op OK (no double encode, lossless)")
    except Exception as e:
        print(f"FAIL  synthetic/already-J2K-no-op\n        {type(e).__name__}: {e}")
        failures.append('synthetic/already-J2K-no-op')

    # 2. RLE lossless -> decompress + re-encode to J2K
    try:
        c = dcmread(str(src_path))
        c.compress(RLELossless, generate_instance_uid=False)
        p2 = Path(workdir) / 'synthetic_rle.dcm'
        c.save_as(str(p2), enforce_file_format=True)
        d = dcmread(str(p2))
        assert str(d.file_meta.TransferSyntaxUID) == str(RLELossless)
        compress_to_j2k_lossless(d)
        assert str(d.file_meta.TransferSyntaxUID) == str(JPEG2000Lossless), \
            f"TS after helper: {d.file_meta.TransferSyntaxUID}"
        p3 = Path(workdir) / 'synthetic_rle_reencoded.dcm'
        d.save_as(str(p3), enforce_file_format=True)
        e = dcmread(str(p3))
        e.decompress(generate_instance_uid=False)
        assert np.array_equal(e.pixel_array, ref)
        print("PASS  synthetic/RLE-reencode-to-J2K\n        re-encoded OK (lossless)")
    except Exception as e:
        print(f"FAIL  synthetic/RLE-reencode-to-J2K\n        {type(e).__name__}: {e}")
        failures.append('synthetic/RLE-reencode-to-J2K')

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-per-modality', type=int, default=3,
                        help='instances to test per modality (default 3)')
    parser.add_argument('--modalities', default='CT,MR,RTPLAN,RTDOSE,RTSTRUCT')
    args = parser.parse_args()

    setup_django()
    modalities = [m.strip().upper() for m in args.modalities.split(',') if m.strip()]

    print(f"Discovering instances for: {', '.join(modalities)} "
          f"(max {args.max_per_modality}/modality) ...")
    found = discover(modalities, args.max_per_modality)
    total = sum(len(v) for v in found.values())
    if total == 0:
        print("ERROR: no DICOM files found for any requested modality")
        return 1
    for mod in modalities:
        print(f"  {mod}: {len(found[mod])} file(s)")

    workdir = tempfile.mkdtemp(prefix='j2k_roundtrip_')
    failures = []
    image_rows = []
    try:
        for mod in modalities:
            for sop_uid, path in [(s, p) for (_, s, p) in found[mod]]:
                label = f"{mod}/{sop_uid}"
                try:
                    result = check_file(mod, sop_uid, path, workdir)
                    print(f"PASS  {label}\n        {result}")
                except Exception as e:
                    print(f"FAIL  {label}\n        {type(e).__name__}: {e}")
                    failures.append(label)

        # Synthetic scenarios that the live corpus (currently 100% raw)
        # cannot exercise:
        #  1. file already stored as J2K (re-ingest of already-stored data)
        #  2. file stored in another compressed syntax (legacy RLE/JPEG)
        image_rows = [row for mod in modalities
                      for row in found[mod]
                      if mod not in ('RTPLAN', 'RTDOSE', 'RTSTRUCT')]
        if image_rows:
            _, sop_uid, path = image_rows[0]
            failures += run_synthetic_scenarios(path, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    grand_total = total + (2 if image_rows else 0)
    print(f"\n{grand_total - len(failures)}/{grand_total} passed, {len(failures)} failed")
    if failures:
        print("Failed:", *failures, sep='\n  - ')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
