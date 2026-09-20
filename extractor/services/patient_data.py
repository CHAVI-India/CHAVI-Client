"""
Patient-page data assembly.

Builds the per-patient view of extracted staging data organized by the
client_app model hierarchy, alongside the records that already exist in
client_app, so reviewers can compare "exists vs extracted" per table.
"""

import json
import os
from logging import getLogger

from django.contrib.contenttypes.models import ContentType

from extractor.models import (
    DatabaseTable, DatabaseField, ExtractedRecord, ExtractionResult,
    ExtractionJob, RecordCreation,
)
from extractor.services.schema_discovery import SchemaDiscoveryService
from extractor.services.semantic_search import build_lookup_label
from extractor.services.record_writer import find_duplicate_candidates

log = getLogger(__name__)

# Model fields never shown as grid columns
_SKIP_FIELD_NAMES = {'id', 'created_at', 'updated_at'}


def _is_lookup_json(value):
    return isinstance(value, dict) and 'code' in value


def _cell_value(result):
    """Effective display value for an ExtractionResult."""
    if result.result_state == 'not_found':
        return {'text': '—', 'kind': 'not_found'}
    raw = result.edited_data if result.data_edited and result.edited_data else result.extracted_data
    try:
        parsed = json.loads(raw) if raw is not None else None
    except (TypeError, json.JSONDecodeError):
        parsed = raw
    if _is_lookup_json(parsed):
        label = parsed.get('label') or ''
        code = parsed.get('code')
        text = f"{label} ({code})" if code not in (None, '') else str(label)
        return {'text': text, 'kind': 'unresolved' if result.result_state == 'unresolved' else 'lookup',
                'code': code, 'label': label}
    if parsed is None or parsed == '':
        return {'text': '—', 'kind': 'not_found'}
    kind = 'unresolved' if result.result_state == 'unresolved' else 'value'
    return {'text': str(parsed), 'kind': kind}


def _grid_columns(db_table):
    """Extractable columns for a table's grid, ordered by field name."""
    cols = []
    for f in db_table.databasefield_set.filter(is_active=True).order_by('clientapp_field_name'):
        validation = f.field_validation or {}
        if validation.get('is_relationship'):
            continue
        if f.clientapp_field_name in _SKIP_FIELD_NAMES:
            continue
        cols.append(f)
    return cols


def _lookup_options_map(db_table):
    """{database_field_id: [{'code','label'}]} — dropdown options for lookup corrections."""
    out = {}
    for f in db_table.databasefield_set.filter(is_active=True, lookup_field=True).select_related('lookup_content_type'):
        model_class = f.lookup_content_type.model_class() if f.lookup_content_type else None
        if not model_class:
            continue
        pk_field = f.lookup_table_pk_field_name or 'pk'
        out[f.id] = [
            {'code': getattr(obj, pk_field), 'label': build_lookup_label(obj, f)}
            for obj in model_class.objects.all()
        ]
    return out


def _format_existing_cell(row, db_field):
    """Value of a live client_app row for one configured column."""
    name = db_field.clientapp_field_name
    try:
        value = getattr(row, name)
    except AttributeError:
        return {'text': '—', 'kind': 'not_found'}
    if db_field.lookup_field and value is not None:
        label = getattr(value, db_field.lookup_table_value_field_name or 'label', str(value))
        code = getattr(value, db_field.lookup_table_pk_field_name or 'pk', '')
        return {'text': f"{label} ({code})", 'kind': 'lookup'}
    if value is None or value == '':
        return {'text': '—', 'kind': 'not_found'}
    return {'text': str(value), 'kind': 'existing'}


def get_existing_rows(db_table, patient, columns):
    """
    Live client_app rows for this patient in the given table.
    Uses the table's recorded patient_path FK chain to filter.
    """
    model_class = db_table.clientapp_content_type.model_class()
    if not model_class:
        return []
    path = (db_table.clientapp_table_fk_fields or {}).get('patient_path')
    if not path:
        return []
    lookup = '__'.join(step['field'] for step in path)
    rows = model_class.objects.filter(**{lookup: patient})
    out = []
    for row in rows:
        out.append({
            'pk': row.pk,
            'cells': [_format_existing_cell(row, c) for c in columns],
        })
    return out


def resolve_lookup_row(db_field, code):
    """
    Fetch the lookup object for a stored code and return ordered
    (field_name, value) pairs — all fields except pk and audit stamps —
    for the expandable "lookup details" display.
    """
    if not db_field.lookup_field or not db_field.lookup_content_type or code in (None, ''):
        return None
    model_class = db_field.lookup_content_type.model_class()
    if not model_class:
        return None
    pk_field = db_field.lookup_table_pk_field_name or 'pk'
    try:
        obj = model_class.objects.get(**{pk_field: code})
    except model_class.DoesNotExist:
        return None
    skip = {pk_field, 'created_at', 'updated_at'}
    pairs = []
    for f in model_class._meta.get_fields():
        if f.name in skip or not hasattr(f, 'attname'):
            continue
        pairs.append((f.name, getattr(obj, f.name)))
    return pairs


def _patient_jobs(patient):
    """All extraction jobs whose source file belongs to this patient."""
    return ExtractionJob.objects.filter(
        processed_file__file_upload__patient_id=patient
    ).select_related('processed_file__file_upload', 'response_model__client')


def build_patient_data_tree(patient):
    """
    Per-table grid data for the patient page, nested by the client_app
    hierarchy (depth ordering from discovery; deeper tables nest under the
    nearest shallower table that has data).
    """
    jobs = _patient_jobs(patient)
    records = ExtractedRecord.objects.filter(
        extraction_job__in=jobs
    ).select_related(
        'database_table__clientapp_content_type',
        'extraction_job__processed_file__file_upload',
    ).order_by('extraction_job_id', 'record_index')

    records_by_table = {}
    for rec in records:
        records_by_table.setdefault(rec.database_table_id, []).append(rec)

    # Only tables that actually produced extracted records
    tables = (DatabaseTable.objects
              .filter(id__in=records_by_table.keys())
              .select_related('clientapp_content_type'))

    # Reuse discovery's depth ordering (patient=0, direct children=1, ...)
    structure = SchemaDiscoveryService.get_hierarchical_table_structure()
    depth_of = {t['id']: (t['depth'] or 99) for t in structure}

    created_map = {
        rc.extracted_record_id: rc.created_record_pk
        for rc in RecordCreation.objects.filter(
            extracted_record__in=records, operation='create', record_created=True)
    }

    nodes = []
    for table in sorted(tables, key=lambda t: (depth_of.get(t.id, 99),
                                               t.clientapp_content_type.model)):
        columns = _grid_columns(table)
        grid_records = []
        for rec in records_by_table.get(table.id, []):
            results = {
                r.database_field_id: r
                for r in ExtractionResult.objects.filter(record=rec)
                        .select_related('database_field')
            }
            cells = []
            for col in columns:
                res = results.get(col.id)
                cells.append(_cell_value(res) if res else {'text': '—', 'kind': 'not_found'})
            state = {
                'unreviewed': sum(1 for r in results.values() if r.data_accuracy == 'unreviewed'),
                'unresolved': sum(1 for r in results.values() if r.result_state == 'unresolved'),
                'not_found': sum(1 for r in results.values() if r.result_state == 'not_found'),
            }
            upload = rec.extraction_job.processed_file.file_upload
            fname = upload.original_filename or os.path.basename(upload.file.name)
            # Resolved lookup details per lookup result (expandable panel data)
            lookup_details = {}
            for col in columns:
                res = results.get(col.id)
                if not res or not col.lookup_field:
                    continue
                raw = res.edited_data if res.data_edited and res.edited_data else res.extracted_data
                try:
                    parsed = json.loads(raw) if raw else None
                except (TypeError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict) and parsed.get('code') not in (None, ''):
                    pairs = resolve_lookup_row(col, parsed['code'])
                    if pairs:
                        lookup_details[col.id] = pairs
            # Detail rows for the expandable panel: (column, result, cell, lookup pairs)
            detail = []
            for col, cell in zip(columns, cells):
                detail.append({
                    'field': col,
                    'result': results.get(col.id),
                    'cell': cell,
                    'lookup_detail': lookup_details.get(col.id),
                })
            grid_records.append({
                'record': rec,
                'cells': cells,
                'detail': detail,
                'state': state,
                'source': fname,
                'created_pk': created_map.get(rec.id),
                'lookup_details': lookup_details,
                'dup_count': len(find_duplicate_candidates(table, rec)),
            })

        nodes.append({
            'table': table,
            'depth': depth_of.get(table.id, 99),
            'display_name': table.clientapp_content_type.model_class()._meta.verbose_name.title()
                            if table.clientapp_content_type.model_class() else str(table),
            'columns': columns,
            'existing': get_existing_rows(table, patient, columns),
            'records': grid_records,
            'lookup_options': _lookup_options_map(table),
        })
        # Attach dropdown options to column objects for template access
        options = nodes[-1]['lookup_options']
        for col in columns:
            col.options = options.get(col.id)

    # Nest deeper nodes under the nearest shallower node (list order is by depth)
    roots = []
    for node in nodes:
        parent = None
        for candidate in reversed(roots):
            if candidate['depth'] < node['depth']:
                parent = candidate
                break
        node['children'] = []
        if parent:
            parent['children'].append(node)
        else:
            roots.append(node)
    return roots
