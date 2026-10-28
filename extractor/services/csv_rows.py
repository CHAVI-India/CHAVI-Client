"""CSV row pipeline: expand a CSV upload into per-row patient documents.

A CSV is expected to carry one patient per row (a mix of structured and
unstructured columns). Each data row is converted into a standalone
markdown document in which every column header becomes a labelled field
and each cell value is its content — empty cells, zeros, NULLs and NAs are
emitted verbatim so the extraction LLM sees the field and its value.

Each row document is a ``ProcessedText`` under the same ``FileUpload``,
identified by ``source_sheet='row-NNNN'`` and linked to its patient (exact
match on the configured patient-id column). It then flows through the
standard text deidentification + extraction pipeline exactly like a
PDF-derived document: one random date shift per row, NER deid (dates are
never redacted), and per-row extraction.

The patient-id column is chosen by the user; rows whose id has no exact
match are surfaced as warnings (they are still processed, unlinked).
"""

import csv
import io
import logging
import re
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_ROW_SHEET_RE = re.compile(r'^row-(\d+)$')
# Marker used for blank cells so the extraction LLM can tell a field was
# empty rather than missing from the document.
_EMPTY_MARKER = '(not recorded)'


def row_number(source_sheet):
    """1-based data-row number from a 'row-NNNN' sheet key; None otherwise."""
    m = _ROW_SHEET_RE.match(source_sheet or '')
    return int(m.group(1)) + 1 if m else None


def is_row_document(processed_text):
    """True when this ProcessedText is a CSV row document (not the raw CSV
    source alias nor a whole-file document)."""
    return bool(_ROW_SHEET_RE.match(processed_text.source_sheet or ''))


def _read_csv(file_upload):
    """(headers, data_rows) from the uploaded CSV. ([], []) when the upload
    is not a readable CSV. Blank lines are dropped; the BOM is stripped."""
    if not file_upload.file:
        return [], []
    if not file_upload.file.name.lower().endswith('.csv'):
        return [], []
    try:
        raw = Path(file_upload.file.path).read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            import chardet
            detected = chardet.detect(raw).get('encoding') or 'latin-1'
            text = raw.decode(detected, errors='replace')
        rows = [r for r in csv.reader(io.StringIO(text))
                if any(cell.strip() for cell in r)]
        if not rows:
            return [], []
        headers = [h.strip() for h in rows[0]]
        return headers, rows[1:]
    except Exception as e:
        logger.error(f"CSV read failed for upload {file_upload.id}: {e}")
        return [], []


def _find_column(headers, column_name):
    """Index of the header matching `column_name` (case-insensitive,
    trimmed); None when not found."""
    if not column_name:
        return None
    target = column_name.strip().lower()
    for i, h in enumerate(headers):
        if h.strip().lower() == target:
            return i
    return None


def _match_patients(data_rows, col_index):
    """Per-row Patient (exact match on the patient-id column) or None.

    'Exact match' means the cell value (whitespace-trimmed) equals
    ``Patient.patient_id`` — no case folding, no fuzzy matching.
    """
    from client_app.models import Patient
    values = []
    for row in data_rows:
        v = row[col_index].strip() if col_index is not None and col_index < len(row) else ''
        if v and v not in values:
            values.append(v)
    lookup = {p.patient_id: p for p in
              Patient.objects.filter(patient_id__in=values)}
    out = []
    for row in data_rows:
        v = row[col_index].strip() if col_index is not None and col_index < len(row) else ''
        out.append(lookup.get(v))
    return out


def build_row_markdown(headers, row):
    """One labelled markdown field per column. Values are emitted verbatim
    (zeros, NULLs, NAs kept as written); blank cells become the explicit
    '(not recorded)' marker so the field's emptiness is visible."""
    lines = ['# Patient record', '']
    for i, header in enumerate(headers):
        value = row[i].strip() if i < len(row) else ''
        if value == '':
            value = _EMPTY_MARKER
        safe = re.sub(r'[^\w\- ]', '', header).strip() or f'field_{i + 1}'
        lines.append(f'- **{safe}**: {value}')
    return '\n'.join(lines) + '\n'


def csv_header_names(file_upload):
    """The header names of the uploaded CSV (for the patient-id column
    selector); [] when unreadable or not a CSV."""
    headers, _ = _read_csv(file_upload)
    return headers


def expand_csv_to_row_documents(file_upload, user, patient_id_column,
                                review_required=False):
    """Convert every CSV data row into a per-row patient document.

    Writes one markdown file per row under a versioned output dir and
    creates a ``ProcessedText`` per row (``source_sheet='row-NNNN'``,
    linked to its patient when the id column exact-matches).

    Returns ``(row_processed_texts, unmatched)`` where ``unmatched`` is a
    list of ``{'row': <1-based data row number>, 'value': <id as written>}``
    for rows whose patient id had no exact match (still processed, unlinked).
    """
    from extractor.models import ProcessedText
    from extractor.services.file_processor import FileProcessorService

    headers, data_rows = _read_csv(file_upload)
    if not headers:
        return [], []

    col_index = _find_column(headers, patient_id_column)
    patients = _match_patients(data_rows, col_index) if col_index is not None else [None] * len(data_rows)

    out_dir = FileProcessorService._versioned_output_dir('csv_rows', file_upload, 1)
    row_pts = []
    unmatched = []
    for idx, row in enumerate(data_rows):
        md = build_row_markdown(headers, row)
        out_path = out_dir / f'row_{idx:04d}.md'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding='utf-8')
        rel_path = str(out_path.relative_to(settings.MEDIA_ROOT))

        pt = ProcessedText.objects.create(
            file_upload=file_upload,
            processed_file_path=rel_path,
            source_sheet=f'row-{idx:04d}',
            processed_by_user=user,
            content_length=len(md),
            version=1,
            is_source_alias=False,
            deid_review_required=review_required,
            patient_id=patients[idx],
        )
        row_pts.append(pt)

        if patients[idx] is None and col_index is not None:
            val = row[col_index].strip() if col_index < len(row) else ''
            unmatched.append({'row': idx + 1, 'value': val})

    if col_index is None and patient_id_column:
        logger.warning(
            f"CSV upload {file_upload.id}: patient-id column "
            f"{patient_id_column!r} not found among headers {headers}")
    logger.info(
        f"CSV upload {file_upload.id} expanded into {len(row_pts)} row "
        f"documents ({len(unmatched)} unmatched patient ids)")
    return row_pts, unmatched
